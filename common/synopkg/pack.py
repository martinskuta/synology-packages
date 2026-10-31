"""Create a Synology SPK and its release metadata from a package payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import quote

from .config import ConfigError, asset_name, info_quote, load_package, target_metadata, validate_info_key


INFO_RESERVED_KEYS = {
    "package",
    "version",
    "arch",
    "os_min_ver",
    "os_max_ver",
    "displayname",
    "description",
    "maintainer",
    "support_url",
    "thirdparty",
    "startable",
}


def _target_for(package: dict, platform: str, arch: str, source_build: str) -> dict:
    matches = [
        target
        for target in package["targets"]
        if target["platform"] == platform
        and target["arch"] == arch
        and target["source_build"] == source_build
    ]
    if len(matches) != 1:
        raise ConfigError(
            f"expected one configured target for {platform}/{arch}/{source_build}, found {len(matches)}"
        )
    return matches[0]


def _target_env(target: dict) -> str:
    return "\n".join(
        (
            f"EXPECTED_PLATFORM={target['platform']}",
            f"EXPECTED_DSM_BUILDS={' '.join(str(value) for value in target['dsm_builds'])}",
            f"EXPECTED_KERNEL={target['kernel_release']}",
            f"EXPECTED_VERMAGIC={target['vermagic']}",
            "",
        )
    )


def _escape_info(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _read_info_env(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    extras = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        if not separator or not validate_info_key(key):
            raise ValueError(f"invalid INFO environment entry at {path}:{line_number}")
        if key not in INFO_RESERVED_KEYS:
            extras[key] = value
    return extras


def _render_info(package: dict, target: dict, info_template: Path, info_env: Path | None) -> str:
    metadata = target_metadata(package, target)
    values = {
        "PACKAGE": package["package"],
        "VERSION": metadata["version"],
        "PLATFORM": target["platform"],
        "OS_MIN_VER": metadata["os_min_ver"],
        "OS_MAX_VER": metadata["os_max_ver"],
        "DISPLAYNAME": package["displayname"],
        "DESCRIPTION": package["description"],
        "MAINTAINER": package["maintainer"],
        "SUPPORT_URL": package["support_url"],
    }
    rendered = info_template.read_text(encoding="utf-8")
    for key, value in values.items():
        rendered = rendered.replace(f"@{key}@", _escape_info(value))
    if re.search(r"@[A-Z_]+@", rendered):
        raise ValueError(f"unresolved placeholder in INFO template: {info_template}")

    rendered = rendered.rstrip("\r\n") + "\n"
    for key, value in _read_info_env(info_env).items():
        rendered += f"{key}={info_quote(value)}\n"
    return rendered


def _tar_filter(info: tarfile.TarInfo, executable_prefixes: tuple[str, ...]) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    if info.isdir():
        info.mode = 0o755
    elif info.name.removeprefix("./").endswith("target.env"):
        info.mode = 0o644
    elif info.name.removeprefix("./").startswith(executable_prefixes):
        info.mode = 0o755
    else:
        info.mode = 0o644
    return info


def _add_tree(archive: tarfile.TarFile, root: Path, arcname: str, executable_prefixes: tuple[str, ...]) -> None:
    if not root.exists():
        return
    if root.is_symlink():
        raise ValueError(f"symlinks are not permitted in SPK inputs: {root}")
    archive.add(root, arcname=arcname, recursive=False, filter=lambda info: _tar_filter(info, executable_prefixes))
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlinks are not permitted in SPK inputs: {path}")
        archive.add(
            path,
            arcname=(Path(arcname) / path.relative_to(root)).as_posix(),
            recursive=False,
            filter=lambda info: _tar_filter(info, executable_prefixes),
        )


def _digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def pack_package(
    package_dir: str | Path,
    payload_dir: str | Path,
    output_dir: str | Path,
    platform: str,
    arch: str,
    source_build: str,
    info_env: str | Path | None = None,
    gpl_json: str | Path | None = None,
    repository: str = "martinskuta/synology-packages",
) -> dict:
    package_root = Path(package_dir)
    spk_source = package_root / "spk"
    payload_source = Path(payload_dir)
    output_root = Path(output_dir)
    if not payload_source.is_dir():
        raise ValueError(f"missing payload directory: {payload_source}")
    if not any(payload_source.iterdir()):
        raise ValueError(f"payload directory is empty: {payload_source}")

    package = load_package(package_root / "package.yml")
    target = _target_for(package, platform, arch, source_build)
    metadata = target_metadata(package, target)
    spk_name = asset_name(package, target)
    output_root.mkdir(parents=True, exist_ok=True)
    spk_path = output_root / spk_name
    checksum_path = output_root / f"{spk_name[:-4]}.sha256"
    metadata_path = output_root / f"{spk_name[:-4]}.meta.json"

    with tempfile.TemporaryDirectory(prefix="synopkg-pack-") as temporary:
        stage = Path(temporary)
        package_root_stage = stage / "payload"
        shutil.copytree(payload_source, package_root_stage)
        static_payload = spk_source / "payload"
        if static_payload.is_dir():
            # Files shipped with the package definition (e.g. bin/apply) are
            # merged on top of the build output.
            shutil.copytree(static_payload, package_root_stage, dirs_exist_ok=True)
        target_env = _target_env(target)
        (package_root_stage / "target.env").write_text(target_env, encoding="utf-8")

        package_tgz = stage / "package.tgz"
        with tarfile.open(package_tgz, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
            _add_tree(archive, package_root_stage, ".", ("bin/",))

        spk_root = stage / "spk"
        spk_root.mkdir()
        (spk_root / "INFO").write_text(
            _render_info(
                package,
                target,
                spk_source / "INFO.in",
                Path(info_env) if info_env else None,
            ),
            encoding="utf-8",
        )
        shutil.copy2(package_tgz, spk_root / "package.tgz")
        shutil.copytree(spk_source / "scripts", spk_root / "scripts")
        (spk_root / "scripts" / "target.env").write_text(target_env, encoding="utf-8")
        shutil.copytree(spk_source / "conf", spk_root / "conf")
        shutil.copytree(spk_source / "WIZARD_UIFILES", spk_root / "WIZARD_UIFILES")
        for filename in (
            "LICENSE",
            "CHANGELOG",
            "PACKAGE_ICON.PNG",
            "PACKAGE_ICON_256.PNG",
        ):
            source = spk_source / filename
            if not source.is_file():
                raise ValueError(f"missing SPK component: {source}")
            shutil.copy2(source, spk_root / filename)

        with tarfile.open(spk_path, "w", format=tarfile.USTAR_FORMAT) as archive:
            component_order = (
                "INFO",
                "package.tgz",
                "scripts",
                "conf",
                "WIZARD_UIFILES",
                "LICENSE",
                "CHANGELOG",
                "PACKAGE_ICON.PNG",
                "PACKAGE_ICON_256.PNG",
            )
            for component in component_order:
                path = spk_root / component
                if not path.exists():
                    raise ValueError(f"missing SPK component: {path}")
                _add_tree(archive, path, path.name, ("scripts/",))

    sha256 = _digest(spk_path, "sha256")
    md5 = _digest(spk_path, "md5")
    checksum_path.write_text(f"{sha256}  {spk_name}\n", encoding="utf-8")
    tag_path = metadata["tag"]
    release_url = (
        f"https://github.com/{repository}/releases/download/{tag_path}/{quote(spk_name)}"
    )
    info_fields = {
        "package": package["package"],
        "version": metadata["version"],
        "arch": target["platform"],
        "os_min_ver": metadata["os_min_ver"],
        "os_max_ver": metadata["os_max_ver"],
        "displayname": package["displayname"],
        "description": package["description"],
        "maintainer": package["maintainer"],
        "support_url": package["support_url"],
        "thirdparty": "yes",
        "startable": "yes",
        **_read_info_env(Path(info_env) if info_env else None),
    }
    meta = {
        **info_fields,
        "dname": package["displayname"],
        "desc": package["description"],
        "link": release_url,
        "tag": tag_path,
        "asset_name": spk_name,
        "platform": target["platform"],
        "target_arch": target["arch"],
        "source_build": target["source_build"],
        "dsm_builds": target["dsm_builds"],
        "sha256": sha256,
        "md5": md5,
        "size": spk_path.stat().st_size,
    }
    metadata_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if gpl_json:
        source = Path(gpl_json)
        if source.is_file():
            shutil.copy2(source, output_root / "gpl.json")
    return {"spk": spk_path, "sha256": checksum_path, "meta": metadata_path, "metadata": meta}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--payload-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--source-build", required=True)
    parser.add_argument("--info-env", type=Path)
    parser.add_argument("--gpl-json", type=Path)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "martinskuta/synology-packages"))
    args = parser.parse_args(argv)

    try:
        result = pack_package(
            args.package_dir,
            args.payload_dir,
            args.output_dir,
            args.platform,
            args.arch,
            args.source_build,
            args.info_env,
            args.gpl_json,
            args.repository,
        )
    except (ConfigError, OSError, ValueError, tarfile.TarError) as error:
        print(f"pack error: {error}", file=sys.stderr)
        return 1

    print(json.dumps({key: str(value) for key, value in result.items() if key != "metadata"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())