#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="${PACKAGE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
TARGET_PLATFORM="${TARGET_PLATFORM:?Set TARGET_PLATFORM}"
TARGET_ARCH="${TARGET_ARCH:?Set TARGET_ARCH}"
SOURCE_BUILD="${SOURCE_BUILD:?Set SOURCE_BUILD}"
KERNEL_RELEASE="${KERNEL_RELEASE:?Set KERNEL_RELEASE}"
VERMAGIC="${VERMAGIC:?Set VERMAGIC}"
TOOLCHAIN_URL="${TOOLCHAIN_URL:?Set TOOLCHAIN_URL}"
KERNEL_URL="${KERNEL_URL:?Set KERNEL_URL}"
CACHE_DIR="${CACHE_DIR:?Set CACHE_DIR}"
OUT_DIR="${OUT_DIR:?Set OUT_DIR}"
IMAGE_TAG="${IMAGE_TAG:-synology-hidraw-builder:ubuntu22}"

PACKAGE_DIR="$(cd "$PACKAGE_DIR" && pwd)"
mkdir -p "$CACHE_DIR" "$OUT_DIR"
CACHE_DIR="$(cd "$CACHE_DIR" && pwd)"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

if [ "${SKIP_DOCKER_BUILD:-0}" != 1 ]; then
    docker build --file "$PACKAGE_DIR/Dockerfile" --tag "$IMAGE_TAG" "$PACKAGE_DIR"
fi

docker run --rm \
    --mount "type=bind,src=$PACKAGE_DIR,dst=/package,readonly" \
    --mount "type=bind,src=$CACHE_DIR,dst=/cache" \
    --mount "type=bind,src=$OUT_DIR,dst=/out" \
    --env "TARGET_PLATFORM=$TARGET_PLATFORM" \
    --env "TARGET_ARCH=$TARGET_ARCH" \
    --env "SOURCE_BUILD=$SOURCE_BUILD" \
    --env "KERNEL_RELEASE=$KERNEL_RELEASE" \
    --env "VERMAGIC=$VERMAGIC" \
    --env "TOOLCHAIN_URL=$TOOLCHAIN_URL" \
    --env "KERNEL_URL=$KERNEL_URL" \
    --env 'CACHE_DIR=/cache' \
    --env 'OUT_DIR=/out' \
    --env "REPO_COMMIT=${GITHUB_SHA:-unknown}" \
    "$IMAGE_TAG" \
    bash -c 'bash /package/fetch-toolchain.sh && bash /package/build-in-container.sh'