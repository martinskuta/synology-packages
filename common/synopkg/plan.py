"""Validate package configs and prepare the GitHub Actions build matrix."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .archive import ArchiveResolutionError, resolve_urls
from .config import ConfigError, load_package, target_metadata


def github_tag_exists(repository: str, tag: str, token: str | None = None) -> bool:
    url = f"https://api.github.com/repos/{repository}/releases/tags/{quote(tag, safe='')}"
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status == 200
    except HTTPError as error:
        if error.code == 404:
            return False
        raise RuntimeError(f"GitHub API returned HTTP {error.code} while checking {tag}") from error
    except OSError as error:
        raise RuntimeError(f"could not check GitHub release tag {tag}: {error}") from error


def build_plan(
    packages_dir: str | Path,
    repository: str | None = None,
    token: str | None = None,
    resolver=resolve_urls,
    tag_exists=github_tag_exists,
) -> list[dict]:
    package_root = Path(packages_dir)
    if not package_root.is_dir():
        raise ConfigError(f"packages directory does not exist: {package_root}")

    plan = []
    checked_tags: dict[str, bool] = {}
    for package_dir in sorted(path for path in package_root.iterdir() if path.is_dir()):
        config_path = package_dir / "package.yml"
        if not config_path.is_file():
            continue
        package = load_package(config_path)
        for target in package["targets"]:
            metadata = target_metadata(package, target)
            if repository:
                tag = metadata["tag"]
                if tag not in checked_tags:
                    checked_tags[tag] = tag_exists(repository, tag, token)
                if checked_tags[tag]:
                    continue

            try:
                resolved = resolver(target)
            except ArchiveResolutionError as error:
                raise ArchiveResolutionError(
                    f"{package['package']} {target['platform']}/{target['arch']} "
                    f"{target['source_build']}: {error}"
                ) from error

            plan.append(
                {
                    "package": package["package"],
                    "package_dir": package_dir.name,
                    "version": metadata["version"],
                    "tag": metadata["tag"],
                    "asset_name": metadata["asset_name"],
                    "platform": target["platform"],
                    "arch": target["arch"],
                    "source_build": target["source_build"],
                    "dsm_builds": target["dsm_builds"],
                    "kernel_release": target["kernel_release"],
                    "vermagic": target["vermagic"],
                    "os_min_ver": metadata["os_min_ver"],
                    "os_max_ver": metadata["os_max_ver"],
                    "toolchain_url": resolved["toolchain_url"],
                    "kernel_url": resolved["kernel_url"],
                }
            )
    return plan


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages-dir", type=Path, default=root / "packages")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        matrix = build_plan(args.packages_dir, args.repository, args.token)
    except (ArchiveResolutionError, ConfigError, RuntimeError) as error:
        print(f"plan error: {error}", file=sys.stderr)
        return 1

    output = json.dumps({"include": matrix}, separators=(",", ":"))
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())