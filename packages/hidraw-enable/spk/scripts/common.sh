#!/bin/sh

HIDRAW_ROOT="${HIDRAW_ROOT:-}"

# Package scripts run as the unprivileged package user whose PATH may lack the
# sbin directories (modinfo, insmod, rmmod). Appending keeps test stubs first.
PATH="${PATH:-/usr/bin:/bin}:/sbin:/usr/sbin:/bin:/usr/bin"
export PATH

# Print a message for the user. DSM only shows script output in Package Center
# when it is written to SYNOPKG_TEMP_LOGFILE.
hidraw_report() {
    printf '%s\n' "$*" >&2
    if [ -n "${SYNOPKG_TEMP_LOGFILE:-}" ]; then
        printf '%s\n' "$*" >> "$SYNOPKG_TEMP_LOGFILE" 2>/dev/null || true
    fi
}

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
        hidraw_report "Missing package target metadata: $target_file"
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
        hidraw_report "Incomplete package target metadata: $target_file"
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

# Print the vermagic of a module file. Falls back to reading the NUL-separated
# .modinfo strings directly, because DSM may not provide modinfo or strings to
# the package user.
hidraw_module_vermagic() {
    module_file=$1
    module_vermagic=$(modinfo -F vermagic "$module_file" 2>/dev/null || true)
    if [ -z "$module_vermagic" ] && [ -r "$module_file" ]; then
        module_vermagic=$(tr '\000' '\n' < "$module_file" 2>/dev/null \
            | sed -n 's/^vermagic=//p' | sed -n '1p')
    fi
    printf '%s\n' "$module_vermagic" | sed 's/[[:space:]]*$//'
}

hidraw_stock_vermagic() {
    hidraw_module_vermagic "$(hidraw_root_path /lib/modules/hid.ko)"
}

hidraw_check_compatibility() {
    current_platform=$(hidraw_current_platform)
    current_build=$(hidraw_current_build)
    current_kernel=$(hidraw_current_kernel)
    current_vermagic=$(hidraw_stock_vermagic)
    compatible=1

    if [ "$current_platform" != "$EXPECTED_PLATFORM" ]; then
        hidraw_report "Unsupported platform: ${current_platform:-unknown} (expected $EXPECTED_PLATFORM)."
        compatible=0
    fi

    case " $EXPECTED_DSM_BUILDS " in
        *" $current_build "*) ;;
        *)
            hidraw_report "Unsupported DSM build: ${current_build:-unknown} (expected one of $EXPECTED_DSM_BUILDS)."
            compatible=0
            ;;
    esac

    if [ "$current_kernel" != "$EXPECTED_KERNEL" ]; then
        hidraw_report "Unsupported kernel: ${current_kernel:-unknown} (expected $EXPECTED_KERNEL)."
        compatible=0
    fi

    if [ "$current_vermagic" != "$EXPECTED_VERMAGIC" ]; then
        hidraw_report "Stock HID vermagic mismatch: ${current_vermagic:-unknown} (expected $EXPECTED_VERMAGIC)."
        compatible=0
    fi

    [ "$compatible" -eq 1 ]
}