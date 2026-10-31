# Synology Package Center source

This repository builds and publishes Synology SPK packages from per-package configuration. Add this source in Package Center to install and update **HIDRAW Support**:

`https://martinskuta.github.io/synology-packages/`

The package index is also available at `https://martinskuta.github.io/synology-packages/index.json`. Static Pages cannot filter query parameters; each entry includes `arch`, `dsm_builds`, `os_min_ver`, and `os_max_ver` for a future Cloudflare Worker. Until that Worker is added, Package Center may display an incompatible build, but the installer rejects it before installation.

## Current package and support

The first package, `hidraw-enable` (HIDRAW Support), rebuilds DSM's HID core with `CONFIG_HIDRAW=y`. The initial target is:

| Property | Value |
| --- | --- |
| NAS model used for the initial target | DS225+ |
| Platform | `geminilakenk` |
| Toolchain architecture | `x86_64` |
| Synology source build | `7.4-90080` |
| Allowed DSM build | `90080` |
| Kernel release | `5.10.55+` |
| Required vermagic | `5.10.55+ SMP mod_unload` |

The package runs with `run-as: package`; it does not install a root lifecycle script or modify `/lib/modules`. A one-time root Task Scheduler boot task loads the package-owned `hid.ko` at boot.

## One-time DSM setup

1. In the repository's **Settings → Pages**, set the build and deployment source to **GitHub Actions**.
2. In **Settings → Actions → General**, allow GitHub Actions to create and approve pull requests. This is required for the weekly source-build discovery workflow.
3. In DSM Package Center settings, set the trust level to **Any publisher**. Only add publishers and packages you trust.
4. Add `https://martinskuta.github.io/synology-packages/` as a Package Source. If DSM does not accept the root URL, try `https://martinskuta.github.io/synology-packages/index.json`.
5. Install **HIDRAW Support**. Read the install-wizard page and create the boot task below.

### Create the root boot task

In DSM **Control Panel → Task Scheduler**, create a **Triggered Task → Boot-up** task and set **User** to `root`. Use this command as the task's user-defined script:

```sh
[ -x /var/packages/hidraw-enable/target/bin/apply ] && /var/packages/hidraw-enable/target/bin/apply start
```

The existence check makes the task a no-op after the package is removed. The package's `apply` script rechecks the NAS platform, DSM build, running kernel, and stock module vermagic before it changes the loaded HID stack.

## Compatibility, rollback, and safety

- Installation is refused unless the configured platform, DSM build, `uname -r`, and stock `hid.ko` vermagic match exactly.
- At boot, a mismatch leaves stock modules alone and is recorded in `/var/packages/hidraw-enable/var/apply.log`.
- The rebuilt `hid.ko` is loaded from the package directory. DSM's `/lib/modules` files are never replaced or edited.
- The apply script tries DSM's `usbhid` and `hid_generic` modules first and uses the bundled fallbacks if needed. If loading fails, it tries to restore the stock stack and logs the outcome.
- For an immediate rollback, run `/var/packages/hidraw-enable/target/bin/apply restore` as root. A reboot without a successful boot-task swap also starts with DSM's stock modules.
- Package Center reports the package as running only when the apply state is active, the `hid` module is loaded, and `/sys/class/hidraw` exists.
- Uninstall hooks do not attempt a privileged unload. Reboot after uninstall to restore stock modules; the defensive boot-task command will then do nothing.
- Do not use force-loading or bypass module-signature checks. If a future DSM enables `MODULE_SIG_FORCE`, loading can fail and the package logs/rolls back rather than bypassing the restriction.
- Unloading HID drivers briefly disconnects attached USB HID devices during boot. Use this only on the exact supported target until additional targets have been built and tested.

## CI, builds, and releases

The `build.yml` workflow validates package configuration, runs Python tests and ShellCheck, discovers Synology download URLs, builds the payload in the package's Ubuntu 22.04 Docker image, and packs the SPK. Successful builds on `master` publish immutable GitHub Releases containing the SPK, SHA-256 checksum, and `.meta.json`; release notes include the Synology GPL source and toolchain URLs, their SHA-256 checksums, and the repository commit. GitHub Pages is regenerated from release metadata.

- Pull requests build and validate but do not publish.
- A manual **Run workflow** on `master` with `publish: false` builds and uploads artifacts only. Download the artifact and use DSM's **Manual Install** to test the `.spk`.
- Manual publishing and Pages deployment are only enabled from `master`.
- The weekly `discover.yml` workflow checks for newer Synology source builds and opens one PR per new target. Review the generated kernel release/vermagic and wait for the PR build to validate them before merging.
- Releases are immutable. Bump a package's `revision` when changing package scripts or build behavior so the next version has a new tag.

## Package configuration and updates

Each package owns `packages/<name>/package.yml`, its build hook, and its `spk/` contents. The `hidraw-enable` config separates the source used to build (`source_build`) from the NAS build numbers permitted to install it (`dsm_builds`). The version is `<source_build>-<revision>`, for example `7.4-90080-1`.

To allow another DSM update build that reuses the same source/toolchain, first verify its exact kernel release and stock vermagic, then add that build number to the matching `dsm_builds` list. This case is deliberately not auto-discovered. `os_min_ver` is the package's minimum DSM version; index `os_min_ver` and `os_max_ver` are derived from each target's DSM build list.

To add a new package, provide:

- `package.yml` with package metadata, a positive `revision`, and a non-empty `targets` list.
- `build.sh`, which receives `PACKAGE_DIR`, `TARGET_PLATFORM`, `TARGET_ARCH`, `SOURCE_BUILD`, `KERNEL_RELEASE`, `VERMAGIC`, `TOOLCHAIN_URL`, `KERNEL_URL`, `CACHE_DIR`, and `OUT_DIR`. It must create `$OUT_DIR/payload/`; it may also create `$OUT_DIR/info.env` and `$OUT_DIR/gpl.json`.
- `spk/` with `INFO.in`, package scripts, `conf/privilege`, wizard files, license, changelog, and 64/256-pixel package icons.
- Optional `discover.sh`, which receives `PACKAGE_DIR` and prints one JSON object per newly discovered target, with `platform`, `arch`, `source_build`, `kernel_release`, `vermagic`, and `dsm_builds`.

The shared Python tools and workflow call these fixed hooks, so package-specific build behavior stays inside its package folder. Package-side scripts must remain POSIX `sh`; DSM does not provide Python for them. If a change to shared tooling requires rebuilding an existing immutable package version, bump the affected package revision as well.

## Local module-only build (Windows / Docker Desktop)

CI is the supported SPK pipeline. For local debugging, the following PowerShell example downloads the configured inputs and builds only the module payload; it does not pack an SPK. The URLs below are the current `geminilakenk` / `7.4-90080` inputs.

```powershell
$repoRoot = (Get-Location).Path
$cacheDir = Join-Path $repoRoot '.cache\synology'
$outDir = Join-Path $repoRoot '.out\hidraw'
New-Item -ItemType Directory -Force $cacheDir, $outDir | Out-Null

docker build -t synology-hidraw-builder:ubuntu22 (Join-Path $repoRoot 'packages\hidraw-enable')

docker run --rm `
  --mount "type=bind,src=$(Join-Path $repoRoot 'packages\hidraw-enable'),dst=/package,readonly" `
  --mount "type=bind,src=$cacheDir,dst=/cache" `
  --mount "type=bind,src=$outDir,dst=/out" `
  -e TARGET_PLATFORM=geminilakenk `
  -e TARGET_ARCH=x86_64 `
  -e SOURCE_BUILD=7.4-90080 `
  -e KERNEL_RELEASE='5.10.55+' `
  -e VERMAGIC='5.10.55+ SMP mod_unload' `
  -e TOOLCHAIN_URL='https://global.synologydownload.com/download/ToolChain/toolchain/7.4-90080/Intel%20x86%20Linux%205.10.55%20%28geminilakenk%29/geminilakenk-gcc1220_glibc236_x86_64-GPL.txz' `
  -e KERNEL_URL='https://global.synologydownload.com/download/ToolChain/Synology%20NAS%20GPL%20Source/7.4-90080/geminilakenk/linux-5.10.x.txz' `
  -e CACHE_DIR=/cache `
  -e OUT_DIR=/out `
  synology-hidraw-builder:ubuntu22 `
  bash -c 'bash /package/fetch-toolchain.sh && bash /package/build-in-container.sh'
```

The output modules are under `.out/hidraw/payload/modules/`. Never load a module built for a different DSM build or kernel. Windows users who need a complete SPK should use the `publish: false` workflow artifact rather than trying to reproduce the packaging pipeline locally.

## Manual NAS test checklist

1. Add the package source and verify DSM can read the listing at `/` or `/index.json`.
2. Install the matching SPK, create the root boot task, and reboot.
3. Confirm Package Center reports **Running** and `/sys/class/hidraw` exists.
4. Run `apply restore` as root and verify DSM's stock HID stack is restored; reboot to apply the package module again.
5. Uninstall the package, reboot, and confirm the stock modules are active and the remaining boot task is a no-op.
6. Before publishing a new target, verify the NAS platform, DSM build, `uname -r`, stock vermagic, and rollback behavior on that exact device.