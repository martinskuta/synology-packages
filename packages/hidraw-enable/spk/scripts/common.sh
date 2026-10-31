#!/bin/sh

HIDRAW_ROOT="${HIDRAW_ROOT:-}"

hidraw_root_path() {
    if [ -n "$HIDRAW_ROOT" ]; then
        printf '%s%s\n' "${HIDRAW_ROOT%/}" "$1"
    else
        printf '%s\n' "$1"
    fi
}

hidraw_load_target_env() {
    target_file="$1"
    [ -r "$target_file" ] || {
        printf 'Missing package target metadata: %s\n' "$target_file" >&2
        return 1
    }

    EXPECTED_PLATFORM=
    EXPECTED_DSM_BUILDS=
    EXPECTED_KERNEL=
    EXPECTED_VERMAGIC=

    while IFS= read -r target_line || [ -n "$target_line" ]; do
        case "$target_line" in
            *=*)
                target_key=${target_line%%=*}
                target_value=${target_line#*=}
                case "$target_key" in
                    EXPECTED_PLATFORM) EXPECTED_PLATFORM=$target_value ;;
                    EXPECTED_DSM_BUILDS) EXPECTED_DSM_BUILDS=$target_value ;;
                    EXPECTED_KERNEL) EXPECTED_KERNEL=$target_value ;;
                    EXPECTED_VERMAGIC) EXPECTED_VERMAGIC=$target_value ;;
                esac
                ;;
        esac
    done < "$target_file"

    if [ -z "$EXPECTED_PLATFORM" ] || [ -z "$EXPECTED_DSM_BUILDS" ] \
        || [ -z "$EXPECTED_KERNEL" ] || [ -z "$EXPECTED_VERMAGIC" ]; then
        printf 'Incomplete package target metadata: %s\n' "$target_file" >&2
        return 1
    fi
}

hidraw_current_platform() {
    synoinfo_file=$(hidraw_root_path /etc.defaults/synoinfo.conf)
    unique_value=$(awk -F '"' '/^unique=/{print $2; exit}' "$synoinfo_file" 2>/dev/null || true)
    unique_value=${unique_value#synology_}
    unique_value=${unique_value%%_*}
    printf '%s\n' "$unique_value"
}

hidraw_current_build() {
    version_file=$(hidraw_root_path /etc.defaults/VERSION)
    awk -F '"' '/^buildnumber=/{print $2; exit}' "$version_file" 2>/dev/null || true
}

hidraw_current_kernel() {
    uname -r
}

hidraw_stock_vermagic() {
    stock_module=$(hidraw_root_path /lib/modules/hid.ko)
    stock_vermagic=$(modinfo -F vermagic "$stock_module" 2>/dev/null || true)
    if [ -z "$stock_vermagic" ] && command -v strings >/dev/null 2>&1; then
        stock_vermagic=$(strings "$stock_module" 2>/dev/null \
            | sed -n 's/^vermagic=//p' | sed -n '1p')
    fi
    printf '%s\n' "$stock_vermagic" | sed 's/[[:space:]]*$//'
}

hidraw_check_compatibility() {
    current_platform=$(hidraw_current_platform)
    current_build=$(hidraw_current_build)
    current_kernel=$(hidraw_current_kernel)
    current_vermagic=$(hidraw_stock_vermagic)
    compatible=1

    if [ "$current_platform" != "$EXPECTED_PLATFORM" ]; then
        printf 'Unsupported platform: %s (expected %s).\n' \
            "${current_platform:-unknown}" "$EXPECTED_PLATFORM" >&2
        compatible=0
    fi

    case " $EXPECTED_DSM_BUILDS " in
        *" $current_build "*) ;;
        *)
            printf 'Unsupported DSM build: %s (expected one of %s).\n' \
                "${current_build:-unknown}" "$EXPECTED_DSM_BUILDS" >&2
            compatible=0
            ;;
    esac

    if [ "$current_kernel" != "$EXPECTED_KERNEL" ]; then
        printf 'Unsupported kernel: %s (expected %s).\n' \
            "${current_kernel:-unknown}" "$EXPECTED_KERNEL" >&2
        compatible=0
    fi

    if [ "$current_vermagic" != "$EXPECTED_VERMAGIC" ]; then
        printf 'Stock HID vermagic mismatch: %s (expected %s).\n' \
            "${current_vermagic:-unknown}" "$EXPECTED_VERMAGIC" >&2
        compatible=0
    fi

    [ "$compatible" -eq 1 ]
}