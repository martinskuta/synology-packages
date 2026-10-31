#!/usr/bin/env bash
set -euo pipefail

WORK="${WORK:-/work}"
BUILD_ROOT="/build"
KERNEL_DIR="$BUILD_ROOT/linux-5.10.x"
OUTPUT="$WORK/output"

PLATFORM="${PLATFORM:?Set PLATFORM, for example geminilakenk}"
ARCH="${ARCH:?Set ARCH to x86_64 or i686}"
CROSS_COMPILE="${ARCH}-pc-linux-gnu-"
KERNEL_VERSION="${KERNEL_VERSION:-5.10.x}"
LOCALVERSION="${LOCALVERSION:-+}"

KERNEL_ARCHIVE="$WORK/downloads/linux-${KERNEL_VERSION}.txz"
TOOLCHAIN_ARCHIVE="$WORK/downloads/${PLATFORM}-gcc1220_glibc236_${ARCH}-GPL.txz"

for file in "$KERNEL_ARCHIVE" "$TOOLCHAIN_ARCHIVE"; do
    [ -s "$file" ] || {
        echo "ERROR: missing archive: $file" >&2
        exit 1
    }
done

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT" "$OUTPUT"

echo "=== Extracting toolchain ==="
tar -xJf "$TOOLCHAIN_ARCHIVE" -C "$BUILD_ROOT"

TOOLCHAIN_BIN="$(find "$BUILD_ROOT" -type f -name "${CROSS_COMPILE}gcc" -exec dirname {} \; | head -n1)"

if [ -z "$TOOLCHAIN_BIN" ]; then
    echo "ERROR: could not locate ${CROSS_COMPILE}gcc" >&2
    exit 1
fi

export PATH="$TOOLCHAIN_BIN:$PATH"
export ARCH
export CROSS_COMPILE

echo "=== Extracting kernel source ==="
tar -xJf "$KERNEL_ARCHIVE" -C "$BUILD_ROOT"
cd "$KERNEL_DIR"

echo "=== Build environment ==="
echo "Kernel source: $KERNEL_DIR"
echo "Toolchain bin: $TOOLCHAIN_BIN"
echo "Compiler:      $(command -v "${CROSS_COMPILE}gcc")"
"${CROSS_COMPILE}gcc" --version | head -n1

echo
echo "=== Configure $PLATFORM kernel ==="
cp "synology/synoconfigs/$PLATFORM" .config

# Preserve DSM's loadable-module layout.
./scripts/config --set-val HID m
./scripts/config --set-val HID_GENERIC m
./scripts/config --set-val USB_HID m

# Enable hidraw support; hidraw is compiled into hid.ko.
./scripts/config --enable HIDRAW

# Preserve DSM's USB HIDDEV setting.
./scripts/config --enable USB_HIDDEV

# Match DSM's trailing plus in the module vermagic.
./scripts/config --set-str LOCALVERSION "$LOCALVERSION"
./scripts/config --disable LOCALVERSION_AUTO

make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" olddefconfig

echo
echo "=== Effective configuration ==="
grep -E '^CONFIG_(HID|HIDRAW|HID_GENERIC|USB_HID|USB_HIDDEV|LOCALVERSION|LOCALVERSION_AUTO|MODULE_SIG|MODULE_SIG_FORCE|MODVERSIONS)=' .config || true

if ! grep -q '^CONFIG_HID=m$' .config; then
    echo "ERROR: CONFIG_HID is not m; refusing to build." >&2
    exit 1
fi

if ! grep -q '^CONFIG_HIDRAW=y$' .config; then
    echo "ERROR: CONFIG_HIDRAW is not enabled; refusing to build." >&2
    exit 1
fi

echo
echo "=== Prepare kernel build tree ==="
make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" -j"$(nproc)" prepare
make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" -j"$(nproc)" modules_prepare

echo
echo "=== Build HID modules ==="
make ARCH="$ARCH" CROSS_COMPILE="$CROSS_COMPILE" -j"$(nproc)" M=drivers/hid modules

echo
echo "=== Built modules ==="
find drivers/hid -type f -name '*.ko' -print

echo
echo "=== Copy results to output folder ==="
cp -v drivers/hid/hid.ko "$OUTPUT/hid-hidraw.ko"
cp -v drivers/hid/hid-generic.ko "$OUTPUT/hid-generic.ko"
cp -v drivers/hid/usbhid/usbhid.ko "$OUTPUT/usbhid.ko"

echo
echo "=== New module metadata ==="
for module in \
    "$OUTPUT/hid-hidraw.ko" \
    "$OUTPUT/hid-generic.ko" \
    "$OUTPUT/usbhid.ko"; do
    echo "--- $(basename "$module")"
    strings "$module" | grep -E '^(vermagic|srcversion|depends|intree|name|license|version)=' || true
    echo
done

echo "=== HIDRAW symbols in rebuilt HID core ==="
nm "$OUTPUT/hid-hidraw.ko" | grep -i hidraw | head -n 20 || true

echo
echo "Build complete."