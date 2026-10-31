#!/bin/sh
set -eu

PACKAGE_DIR=${PACKAGE_DIR:?Set PACKAGE_DIR}
PACKAGE_DIR=$(CDPATH='' cd -- "$PACKAGE_DIR" && pwd)
REPOSITORY_ROOT=$(CDPATH='' cd -- "$PACKAGE_DIR/../.." && pwd)

PYTHONPATH="$REPOSITORY_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m common.synopkg.archive discover --package-yml "$PACKAGE_DIR/package.yml"