# Synology HIDRAW kernel module builder

Builds a hidraw-enabled `hid.ko` for a Synology DS225+ running DSM 7.4.1-90080
(`geminilakenk`, x86_64, kernel 5.10.55+).

The resulting module is named `hid-hidraw.ko` locally. When deployed, it replaces
`/lib/modules/hid.ko`; hidraw support is compiled into the HID core rather than
being a separate `hidraw.ko`.

## Requirements

- Windows with Docker Desktop
- Synology NAS with SSH access
- The NAS platform name and DSM build number
- Synology GPL kernel source and matching toolchain

## Target identification

On the NAS, run:

```sh
cat /proc/sys/kernel/syno_hw_version
uname -a
cat /etc.defaults/VERSION
grep '^unique=' /etc.defaults/synoinfo.conf
```

For this project:

| Item | Value |
|---|---|
| Model | DS225+ |
| Platform | `geminilakenk` |
| Architecture | `x86_64` |
| DSM build | `7.4-90080` |
| Original kernel | `5.10.55+` |
| Required vermagic | `5.10.55+ SMP mod_unload` |

## Repeat after a DSM update

1. Identify the new DSM build number.
2. Download the new matching GPL source and toolchain.
3. Rebuild `hid.ko` with `CONFIG_HIDRAW=y`.
4. Compare the new module’s `vermagic` with the NAS’s original `hid.ko`.
5. Test-load the rebuilt module without replacing the original.
6. Only after a successful test, optionally install it persistently.

Never reuse a module built for a previous DSM build or kernel version.

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Ubuntu 22.04 build environment |
| `fetch-synology-build.sh` | Downloads kernel source and toolchain |
| `build-hidraw.sh` | Extracts, configures, builds, and exports modules |
| `downloads/` | Synology source and toolchain archives |
| `output/` | Built `.ko` files |
| `original-modules/` | Backup of DSM’s original signed modules |

## Build outputs

| File | Purpose |
|---|---|
| `output/hid-hidraw.ko` | Rebuilt `hid.ko` with hidraw support |
| `output/hid-generic.ko` | Rebuilt generic HID driver |
| `output/usbhid.ko` | Rebuilt USB HID transport driver |

Normally, deploy only `hid-hidraw.ko` as `/lib/modules/hid.ko`. Rebuild and retain
the other two modules for comparison or recovery, but do not replace them unless
testing proves it necessary.

## Safety

- Always back up `/lib/modules/hid.ko` before replacing it.
- Test-load from a temporary path first.
- Do not use `insmod --force` or disable module-signature enforcement.
- The original DSM modules are signed by Synology. The rebuilt module is unsigned;
  it loaded because `CONFIG_MODULE_SIG_FORCE` was not enabled. A future DSM update
  could change that behavior.
- After any DSM update, repeat the entire flow.