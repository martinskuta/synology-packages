#!/bin/sh
set -eu

SPK_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

FAKE_ROOT="$TMP_DIR/root"
FAKE_BIN="$TMP_DIR/bin"
PKG_TEMP="$TMP_DIR/package"
INSTALLED_PACKAGE="$TMP_DIR/installed"
mkdir -p "$FAKE_ROOT/etc.defaults" "$FAKE_ROOT/lib/modules" \
    "$FAKE_BIN" "$PKG_TEMP" "$INSTALLED_PACKAGE/bin" \
    "$INSTALLED_PACKAGE/scripts" "$INSTALLED_PACKAGE/modules/fallback" \
    "$INSTALLED_PACKAGE/var"

cat > "$FAKE_ROOT/etc.defaults/synoinfo.conf" <<'EOF'
unique="synology_geminilakenk"
EOF
cat > "$FAKE_ROOT/etc.defaults/VERSION" <<'EOF'
buildnumber="90080"
EOF
# DSM extracts package.tgz (which contains target.env) to SYNOPKG_PKGINST_TEMP_DIR.
cat > "$PKG_TEMP/target.env" <<'EOF'
EXPECTED_PLATFORM=geminilakenk
EXPECTED_DSM_BUILDS=90080 90081
EXPECTED_KERNEL=5.10.55+
EXPECTED_VERMAGIC=5.10.55+ SMP mod_unload
EOF
touch "$FAKE_ROOT/lib/modules/hid.ko"

cat > "$FAKE_BIN/uname" <<'EOF'
#!/bin/sh
if [ "${1:-}" = -r ]; then
    printf '%s\n' "${TEST_KERNEL:-5.10.55+}"
else
    exec /usr/bin/uname "$@"
fi
EOF
cat > "$FAKE_BIN/modinfo" <<'EOF'
#!/bin/sh
if [ "${1:-}" = -F ] && [ "${2:-}" = vermagic ]; then
    printf '%s\n' "${TEST_VERMAGIC:-5.10.55+ SMP mod_unload }"
    exit 0
fi
exit 1
EOF
chmod +x "$FAKE_BIN/uname" "$FAKE_BIN/modinfo"
cp "$SPK_DIR/payload/bin/apply" "$INSTALLED_PACKAGE/bin/apply"
cp "$SPK_DIR/scripts/common.sh" "$INSTALLED_PACKAGE/scripts/common.sh"
cp "$PKG_TEMP/target.env" "$INSTALLED_PACKAGE/scripts/target.env"
touch "$INSTALLED_PACKAGE/modules/hid.ko"
cat > "$FAKE_BIN/rmmod" <<EOF
#!/bin/sh
touch "$TMP_DIR/rmmod-called"
exit 0
EOF
chmod +x "$FAKE_BIN/rmmod"

run_preinst() {
    PATH="$FAKE_BIN:$PATH" \
        HIDRAW_ROOT="$FAKE_ROOT" \
        SYNOPKG_PKGINST_TEMP_DIR="$PKG_TEMP" \
        SYNOPKG_TEMP_LOGFILE="$TMP_DIR/dsm-message.log" \
        sh "$SPK_DIR/scripts/preinst"
}

run_preinst >/dev/null
echo 'PASS: compatible target is accepted.'

# Packed SPK layout: target.env sits next to the scripts, no DSM temp dir.
SPK_LAYOUT="$TMP_DIR/spk-layout"
mkdir -p "$SPK_LAYOUT/scripts"
cp "$SPK_DIR/scripts/preinst" "$SPK_DIR/scripts/common.sh" "$SPK_LAYOUT/scripts/"
cp "$PKG_TEMP/target.env" "$SPK_LAYOUT/scripts/target.env"
PATH="$FAKE_BIN:$PATH" HIDRAW_ROOT="$FAKE_ROOT" \
    sh "$SPK_LAYOUT/scripts/preinst" >/dev/null
echo 'PASS: preinst reads target.env from the packed scripts directory.'

# Without a usable modinfo, the vermagic is read from the module itself.
NO_MODINFO_BIN="$TMP_DIR/no-modinfo-bin"
mkdir -p "$NO_MODINFO_BIN"
cp "$FAKE_BIN/uname" "$NO_MODINFO_BIN/uname"
printf '#!/bin/sh\nexit 1\n' > "$NO_MODINFO_BIN/modinfo"
chmod +x "$NO_MODINFO_BIN/modinfo"
printf 'ELF\000license=GPL\000vermagic=5.10.55+ SMP mod_unload \000name=hid\000' \
    > "$FAKE_ROOT/lib/modules/hid.ko"
PATH="$NO_MODINFO_BIN:$PATH" HIDRAW_ROOT="$FAKE_ROOT" \
    SYNOPKG_PKGINST_TEMP_DIR="$PKG_TEMP" \
    sh "$SPK_DIR/scripts/preinst" >/dev/null
echo 'PASS: stock vermagic is read without modinfo.'

cat > "$FAKE_ROOT/etc.defaults/synoinfo.conf" <<'EOF'
unique="synology_otherplatform"
EOF
if run_preinst >/dev/null 2>&1; then
    echo 'FAIL: wrong platform was accepted.' >&2
    exit 1
fi
if ! grep -q 'Unsupported platform: otherplatform' "$TMP_DIR/dsm-message.log"; then
    echo 'FAIL: the rejection reason was not written for Package Center.' >&2
    exit 1
fi
echo 'PASS: wrong platform is rejected with a Package Center message.'

if PATH="$FAKE_BIN:$PATH" HIDRAW_ROOT="$FAKE_ROOT" \
    sh "$INSTALLED_PACKAGE/bin/apply" start >/dev/null 2>&1; then
    echo 'FAIL: apply accepted a wrong platform.' >&2
    exit 1
fi
if [ -e "$TMP_DIR/rmmod-called" ]; then
    echo 'FAIL: apply unloaded modules after a compatibility mismatch.' >&2
    exit 1
fi
if [ "$(cat "$INSTALLED_PACKAGE/var/state")" != mismatch ]; then
    echo 'FAIL: apply did not record the compatibility mismatch.' >&2
    exit 1
fi
echo 'PASS: apply skips module changes on a compatibility mismatch.'

cat > "$FAKE_ROOT/etc.defaults/synoinfo.conf" <<'EOF'
unique="synology_geminilakenk"
EOF
cat > "$FAKE_ROOT/etc.defaults/VERSION" <<'EOF'
buildnumber="90082"
EOF
if run_preinst >/dev/null 2>&1; then
    echo 'FAIL: wrong DSM build was accepted.' >&2
    exit 1
fi
echo 'PASS: wrong DSM build is rejected.'

cat > "$FAKE_ROOT/etc.defaults/VERSION" <<'EOF'
buildnumber="90080"
EOF
if TEST_KERNEL='5.10.56+' run_preinst >/dev/null 2>&1; then
    echo 'FAIL: wrong kernel was accepted.' >&2
    exit 1
fi
echo 'PASS: wrong running kernel is rejected.'

if TEST_VERMAGIC='5.10.56+ SMP mod_unload' run_preinst >/dev/null 2>&1; then
    echo 'FAIL: wrong stock vermagic was accepted.' >&2
    exit 1
fi
echo 'PASS: wrong stock vermagic is rejected.'

mkdir -p "$FAKE_ROOT/sys/module/hid" "$FAKE_ROOT/sys/class/hidraw"
printf 'active\n' > "$INSTALLED_PACKAGE/var/state"
if ! PATH="$FAKE_BIN:$PATH" HIDRAW_ROOT="$FAKE_ROOT" \
    sh "$INSTALLED_PACKAGE/bin/apply" status >/dev/null; then
    echo 'FAIL: active module and hidraw class were not reported as running.' >&2
    exit 1
fi
rmdir "$FAKE_ROOT/sys/class/hidraw"
if PATH="$FAKE_BIN:$PATH" HIDRAW_ROOT="$FAKE_ROOT" \
    sh "$INSTALLED_PACKAGE/bin/apply" status >/dev/null 2>&1; then
    echo 'FAIL: missing hidraw class was reported as running.' >&2
    exit 1
fi
echo 'PASS: status requires both the loaded HID module and hidraw class.'