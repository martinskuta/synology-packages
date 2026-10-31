#!/usr/bin/env bash
set -euo pipefail

WORK="${WORK:-/work}"
DOWNLOADS="$WORK/downloads"
mkdir -p "$DOWNLOADS"
cd "$DOWNLOADS"

DSM_BUILD="${DSM_BUILD:?Set DSM_BUILD, for example 7.4-90080}"
PLATFORM="${PLATFORM:?Set PLATFORM, for example geminilakenk}"
ARCH="${ARCH:?Set ARCH to i686 or x86_64}"
KERNEL_VERSION="${KERNEL_VERSION:-5.10.x}"

case "$ARCH" in
    i686|x86_64) ;;
    *)
        echo "ERROR: ARCH must be i686 or x86_64 (received: $ARCH)" >&2
        exit 1
        ;;
esac

CDN="https://global.synologydownload.com/download/ToolChain"

KERNEL_NAME="linux-${KERNEL_VERSION}.txz"
KERNEL_URL="$CDN/Synology%20NAS%20GPL%20Source/$DSM_BUILD/$PLATFORM/$KERNEL_NAME"

TOOLCHAIN_NAME="${PLATFORM}-gcc1220_glibc236_${ARCH}-GPL.txz"
TOOLCHAIN_URL="$CDN/toolchain/$DSM_BUILD/Intel%20x86%20Linux%205.10.55%20%28${PLATFORM}%29/$TOOLCHAIN_NAME"

download() {
    local url="$1"
    local output="$DOWNLOADS/$(basename "$url")"

    if [ -s "$output" ]; then
        echo "Already present: $output"
        return
    fi

    echo "Downloading:"
    echo "  $url"
    echo "  -> $output"

    curl -fL --retry 3 --retry-delay 2 --connect-timeout 30 \
         -o "$output.part" "$url"

    if head -c 200 "$output.part" | grep -qi '<!DOCTYPE html'; then
        echo "ERROR: $output.part is HTML, not an archive." >&2
        echo "URL: $url" >&2
        rm -f "$output.part"
        exit 1
    fi

    mv "$output.part" "$output"
    echo "Saved: $output"
    echo
}

echo "Target:"
echo "  DSM build: $DSM_BUILD"
echo "  Platform:  $PLATFORM"
echo "  Arch:      $ARCH"
echo

download "$KERNEL_URL"
download "$TOOLCHAIN_URL"

echo "Downloaded build inputs:"
ls -lh "$KERNEL_NAME" "$TOOLCHAIN_NAME"

echo
echo "SHA-256 checksums:"
sha256sum "$KERNEL_NAME" "$TOOLCHAIN_NAME"