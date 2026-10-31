#!/usr/bin/env bash
set -euo pipefail

BUILD_ROOT="/build"
PLATFORM="${TARGET_PLATFORM:?Set TARGET_PLATFORM}"
ARCH="${TARGET_ARCH:?Set TARGET_ARCH}"
KERNEL_RELEASE="${KERNEL_RELEASE:?Set KERNEL_RELEASE}"
VERMAGIC="${VERMAGIC:?Set VERMAGIC}"
CACHE_DIR="${CACHE_DIR:?Set CACHE_DIR}"
OUT_DIR="${OUT_DIR:?Set OUT_DIR}"
KERNEL_URL="${KERNEL_URL:?Set KERNEL_URL}"
TOOLCHAIN_URL="${TOOLCHAIN_URL:?Set TOOLCHAIN_URL}"

archive_name() {
    local url="$1"
    url="${url%%\#*}"
    url="${url%%\?*}"
    printf '%s\n' "${url##*/}"
}

KERNEL_ARCHIVE="$CACHE_DIR/$(archive_name "$KERNEL_URL")"
TOOLCHAIN_ARCHIVE="$CACHE_DIR/$(archive_name "$TOOLCHAIN_URL")"

for archive in "$KERNEL_ARCHIVE" "$TOOLCHAIN_ARCHIVE"; do
    [ -s "$archive" ] || {
        printf 'ERROR: missing archive: %s\n' "$archive" >&2
        exit 1
    }
done

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT/kernel" "$BUILD_ROOT/toolchain" \
    "$OUT_DIR/payload/modules/fallback"

echo '=== Extracting toolchain ==='
tar -xJf "$TOOLCHAIN_ARCHIVE" -C "$BUILD_ROOT/toolchain"

CROSS_COMPILE="${ARCH}-pc-linux-gnu-"
COMPILER="$(find "$BUILD_ROOT/toolchain" -type f -name "${CROSS_COMPILE}gcc" -print -quit)"
if [ -z "$COMPILER" ]; then
    printf 'ERROR: could not locate %s gcc in the toolchain archive.\n' "$CROSS_COMPILE" >&2
    exit 1
fi
TOOLCHAIN_BIN="$(dirname "$COMPILER")"
export PATH="$TOOLCHAIN_BIN:$PATH"
export ARCH CROSS_COMPILE

echo '=== Extracting kernel source ==='
tar -xJf "$KERNEL_ARCHIVE" -C "$BUILD_ROOT/kernel"

CONFIG_PATH="$(find "$BUILD_ROOT/kernel" -type f \
    -path "*/synology/synoconfigs/$PLATFORM" -print -quit)"
if [ -z "$CONFIG_PATH" ]; then
    printf 'ERROR: no synology/synoconfigs/%s config found in kernel archive.\n' "$PLATFORM" >&2
    exit 1
fi
KERNEL_DIR="$(dirname "$(dirname "$(dirname "$CONFIG_PATH")")")"
cd "$KERNEL_DIR"

echo '=== Build environment ==='
printf 'Kernel source: %s\nToolchain bin: %s\nCompiler:      %s\n' \
    "$KERNEL_DIR" "$TOOLCHAIN_BIN" "$(command -v "${CROSS_COMPILE}gcc")"
"${CROSS_COMPILE}gcc" --version | head -n1

echo "=== Configure $PLATFORM kernel ==="
cp "synology/synoconfigs/$PLATFORM" .config

./scripts/config --set-val HID m
./scripts/config --set-val HID_GENERIC m
./scripts/config --set-val USB_HID m
./scripts/config --enable HIDRAW
./scripts/config --enable USB_HIDDEV
./scripts/config --set-str LOCALVERSION '+'
./scripts/config --disable LOCALVERSION_AUTO

make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" olddefconfig

grep -E '^CONFIG_(HID|HIDRAW|HID_GENERIC|USB_HID|MODVERSIONS)=' .config || true

if ! grep -q '^CONFIG_HID=m$' .config; then
    echo 'ERROR: CONFIG_HID is not m; refusing to build.' >&2
    exit 1
fi
if ! grep -q '^CONFIG_HIDRAW=y$' .config; then
    echo 'ERROR: CONFIG_HIDRAW is not enabled; refusing to build.' >&2
    exit 1
fi
if grep -q '^CONFIG_MODVERSIONS=y$' .config && [ ! -s Module.symvers ]; then
    echo 'ERROR: CONFIG_MODVERSIONS=y but Module.symvers is missing; refusing to build an unverifiable module.' >&2
    exit 1
fi

BUILT_KERNEL_RELEASE="$(make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" -s kernelrelease)"
if [ "$BUILT_KERNEL_RELEASE" != "$KERNEL_RELEASE" ]; then
    printf 'ERROR: kernel release mismatch: built %s, expected %s.\n' \
        "$BUILT_KERNEL_RELEASE" "$KERNEL_RELEASE" >&2
    exit 1
fi

echo '=== Prepare kernel build tree ==='
make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" -j"$(nproc)" prepare
make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" -j"$(nproc)" modules_prepare

echo '=== Build HID modules ==='
make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" -j"$(nproc)" M=drivers/hid modules

HID_MODULE="$KERNEL_DIR/drivers/hid/hid.ko"
GENERIC_MODULE="$KERNEL_DIR/drivers/hid/hid-generic.ko"
USBHID_MODULE="$KERNEL_DIR/drivers/hid/usbhid/usbhid.ko"
for module in "$HID_MODULE" "$GENERIC_MODULE" "$USBHID_MODULE"; do
    [ -s "$module" ] || {
        printf 'ERROR: expected module was not built: %s\n' "$module" >&2
        exit 1
    }
done

ACTUAL_VERMAGIC="$(modinfo -F vermagic "$HID_MODULE" | sed 's/[[:space:]]*$//')"
if [ "$ACTUAL_VERMAGIC" != "$VERMAGIC" ]; then
    printf 'ERROR: hid.ko vermagic mismatch: built "%s", expected "%s".\n' \
        "$ACTUAL_VERMAGIC" "$VERMAGIC" >&2
    exit 1
fi
if ! nm "$HID_MODULE" | grep -qi hidraw; then
    echo 'ERROR: rebuilt hid.ko has no HIDRAW symbols.' >&2
    exit 1
fi

cp "$HID_MODULE" "$OUT_DIR/payload/modules/hid.ko"
cp "$USBHID_MODULE" "$OUT_DIR/payload/modules/fallback/usbhid.ko"
cp "$GENERIC_MODULE" "$OUT_DIR/payload/modules/fallback/hid-generic.ko"

printf 'kernel_release=%s\nvermagic=%s\nsource_build=%s\n' \
    "$KERNEL_RELEASE" "$VERMAGIC" "${SOURCE_BUILD:-}" > "$OUT_DIR/info.env"

KERNEL_SHA256="$(sha256sum "$KERNEL_ARCHIVE" | awk '{print $1}')"
TOOLCHAIN_SHA256="$(sha256sum "$TOOLCHAIN_ARCHIVE" | awk '{print $1}')"
python3 - "$OUT_DIR/gpl.json" "$KERNEL_URL" "$KERNEL_SHA256" \
    "$TOOLCHAIN_URL" "$TOOLCHAIN_SHA256" "${REPO_COMMIT:-unknown}" <<'PY'
import json
import sys

path, kernel_url, kernel_sha256, toolchain_url, toolchain_sha256, commit = sys.argv[1:]
with open(path, "w", encoding="utf-8") as output:
    json.dump(
        {
            "kernel_url": kernel_url,
            "kernel_sha256": kernel_sha256,
            "toolchain_url": toolchain_url,
            "toolchain_sha256": toolchain_sha256,
            "repo_commit": commit,
        },
        output,
        indent=2,
    )
    output.write("\n")
PY

echo 'Build complete.'