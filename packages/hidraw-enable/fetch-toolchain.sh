#!/usr/bin/env bash
set -euo pipefail

CACHE_DIR="${CACHE_DIR:?Set CACHE_DIR}"
TOOLCHAIN_URL="${TOOLCHAIN_URL:?Set TOOLCHAIN_URL}"
KERNEL_URL="${KERNEL_URL:?Set KERNEL_URL}"

mkdir -p "$CACHE_DIR"

archive_name() {
    local url="$1"
    url="${url%%\#*}"
    url="${url%%\?*}"
    printf '%s\n' "${url##*/}"
}

download() {
    local url="$1"
    local name="$2"
    local output="$CACHE_DIR/$name"

    if [ -s "$output" ]; then
        printf 'Already present: %s\n' "$output"
        return
    fi

    printf 'Downloading %s\n  -> %s\n' "$url" "$output"
    curl -fL --retry 3 --retry-delay 2 --connect-timeout 30 \
        -o "$output.part" "$url"

    if head -c 512 "$output.part" | grep -Eqi '<!doctype[[:space:]]+html|<html'; then
        printf 'ERROR: %s is an HTML response, not an archive.\nURL: %s\n' \
            "$output.part" "$url" >&2
        rm -f "$output.part"
        exit 1
    fi

    mv "$output.part" "$output"
}

KERNEL_NAME="$(archive_name "$KERNEL_URL")"
TOOLCHAIN_NAME="$(archive_name "$TOOLCHAIN_URL")"

if [ -z "$KERNEL_NAME" ] || [ -z "$TOOLCHAIN_NAME" ]; then
    echo 'ERROR: archive URLs must end in a filename.' >&2
    exit 1
fi

download "$KERNEL_URL" "$KERNEL_NAME"
download "$TOOLCHAIN_URL" "$TOOLCHAIN_NAME"

printf '\nDownloaded build inputs:\n'
ls -lh "$CACHE_DIR/$KERNEL_NAME" "$CACHE_DIR/$TOOLCHAIN_NAME"
printf '\nSHA-256 checksums:\n'
sha256sum "$CACHE_DIR/$KERNEL_NAME" "$CACHE_DIR/$TOOLCHAIN_NAME"