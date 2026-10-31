#!/usr/bin/env bash
set -euo pipefail

WORK="${WORK:-/work}"
DOWNLOADS="$WORK/downloads"
SRC="$WORK/src"
TOOLCHAIN="$WORK/toolchain"
OUTPUT="$WORK/output"

PLATFORM="${PLATFORM:-geminilakenk}"
ARCH="${ARCH:-x86_64}"
KERNEL_LOCALVERSION="${KERNEL_LOCALVERSION:+}"

KERNEL_ARCHIVE="$DOWNLOADS/linux-5.10.x.txz"
TOOLCHAIN_ARCHIVE="$DOWNLOADS/${PLATFORM}-gcc1220_glibc236_${ARCH}-GPL.txz"

for file in "$KERNEL_ARCHIVE" "$TOOLCHAIN_ARCHIVE"; do
    [ -s "$file" ] || {
        echo "ERROR: missing archive: $file" >&2
        exit 1
    }
done

mkdir -p "$SRC" "$TOOLCHAIN" "$OUTPUT"

echo "=== Extracting toolchain ==="
tar -xJf "$TOOLCHAIN_ARCHIVE" -C "$TOOLCHAIN"

echo "=== Locating cross-compiler ==="
COMPILER="$(find "$TOOLCHAIN" -type f -name "${ARCH}-pc-linux-gnu-gcc" | head -n1)"

if [ -z "$COMPILER" ]; then
    echo "ERROR: could not find ${ARCH}-pc-linux-gnu-gcc" >&2
    find "$TOOLCHAIN" -type f -name '*gcc' | head -n 20 >&2
    exit 1
fi

TOOLCHAIN_BIN="$(dirname "$COMPILER")"
export PATH="$TOOLCHAIN_BIN:$PATH"
export CROSS_COMPILE="${ARCH}-pc-linux-gnu-"

echo "Compiler: $COMPILER"
"$COMPILER" --version | head -n1

echo
echo "=== Extracting kernel source ==="
tar -xJf "$KERNEL_ARCHIVE" -C "$SRC"

KERNEL_DIR="$(find "$SRC" -mindepth 1 -maxdepth 1 -type d | head -n1)"
cd "$KERNEL_DIR"

echo "Kernel source directory: $KERNEL_DIR"

echo
echo "=== Available Synology kernel configurations ==="
find . -maxdepth 3 -type f \( -iname '*geminilakenk*' -o -path '*/synoconfigs/*' \) | sort

echo
echo "=== Current HID-related configuration ==="
for config_file in \
    "synoconfigs/$PLATFORM" \
    "synoconfigs/$ARCH" \
    ".config"; do
    if [ -f "$config_file" ]; then
        echo "--- $config_file"
        grep -E '^CONFIG_(HID|HIDRAW|HID_GENERIC|USB_HID)[= ]' "$config_file" || true
    fi
done

echo
echo "=== HID source and Makefile references ==="
grep -RniE 'CONFIG_HIDRAW|hidraw' drivers/hid/Makefile drivers/hid/Kconfig 2>/dev/null || true