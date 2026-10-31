"""Publish packaged SPKs as immutable GitHub Releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class PublishError(RuntimeError):
    """Raised when a release or asset cannot be published safely."""


def _request_json(
    repository: str,
    endpoint: str,
    token: str,
    method: str = "GET",
    payload: dict | None = None,
    allow_404: bool = False,
    opener=None,
):
    url = f"https://api.github.com/repos/{repository}{endpoint}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with (opener or urlopen)(request, timeout=60) as response:
            response_body = response.read()
            return json.loads(response_body) if response_body else {}
    except HTTPError as error:
        if allow_404 and error.code == 404:
            return None
        detail = error.read().decode("utf-8", errors="replace")
        raise PublishError(f"GitHub API {method} {endpoint} failed with HTTP {error.code}: {detail}") from error
    except OSError as error:
        raise PublishError(f"GitHub API {method} {endpoint} failed: {error}") from error


def _release_assets(assets_dir: Path) -> dict[str, list[dict]]:
    releases: dict[str, list[dict]] = defaultdict(list)
    metadata_files = sorted(assets_dir.rglob("*.meta.json"))
    if not metadata_files:
        raise PublishError(f"no .meta.json assets found under {assets_dir}")

    for metadata_path in metadata_files:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PublishError(f"invalid release metadata {metadata_path}: {error}") from error
        tag = metadata.get("tag")
        asset_name = metadata.get("asset_name")
        if not isinstance(tag, str) or not tag or not isinstance(asset_name, str) or not asset_name:
            raise PublishError(f"{metadata_path} is missing the release tag or SPK asset name")

        asset = metadata_path.parent / asset_name
        checksum = metadata_path.with_name(metadata_path.name[: -len(".meta.json")] + ".sha256")
        gpl_metadata = metadata_path.parent / "gpl.json"
        for required in (asset, checksum, gpl_metadata):
            if not required.is_file():
                raise PublishError(f"release input is missing: {required}")

        expected_sha256 = hashlib.sha256(asset.read_bytes()).hexdigest()
        if expected_sha256 != metadata.get("sha256"):
            raise PublishError(f"SHA-256 mismatch for {asset}")
        if asset.stat().st_size != metadata.get("size"):
            raise PublishError(f"size mismatch for {asset}")
        checksum_values = checksum.read_text(encoding="utf-8").split()
        if checksum_values != [expected_sha256, asset.name]:
            raise PublishError(f"checksum file does not match {asset}")

        try:
            gpl = json.loads(gpl_metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PublishError(f"invalid GPL build metadata {gpl_metadata}: {error}") from error
        for key in ("kernel_url", "kernel_sha256", "toolchain_url", "toolchain_sha256", "repo_commit"):
            if not isinstance(gpl.get(key), str) or not gpl[key]:
                raise PublishError(f"{gpl_metadata} is missing {key}")

        releases[tag].append(
            {
                "metadata": metadata,
                "metadata_path": metadata_path,
                "asset": asset,
                "checksum": checksum,
                "gpl": gpl,
            }
        )
    return releases


def _release_notes(repository: str, commit: str, items: list[dict]) -> str:
    lines = [
        "## Source and build information",
        "",
        f"Repository commit: [`{commit}`](https://github.com/{repository}/commit/{commit})",
        "",
        "The corresponding Synology GPL sources and toolchains are listed below.",
        "",
    ]
    seen = set()
    for item in sorted(items, key=lambda entry: entry["metadata"]["asset_name"]):
        metadata = item["metadata"]
        gpl = item["gpl"]
        identity = (
            metadata["platform"],
            metadata["target_arch"],
            metadata["source_build"],
        )
        if identity in seen:
            continue
        seen.add(identity)
        if gpl["repo_commit"] != commit:
            raise PublishError(
                f"build metadata commit {gpl['repo_commit']} does not match release commit {commit}"
            )
        lines.extend(
            [
                f"### {metadata['platform']} / {metadata['target_arch']} — {metadata['source_build']}",
                "",
                f"- Kernel source: [{gpl['kernel_url']}]({gpl['kernel_url']})",
                f"  - SHA-256: `{gpl['kernel_sha256']}`",
                f"- Toolchain: [{gpl['toolchain_url']}]({gpl['toolchain_url']})",
                f"  - SHA-256: `{gpl['toolchain_sha256']}`",
                f"- Package configuration: [`packages/{metadata['package']}/build.sh`](https://github.com/{repository}/blob/{commit}/packages/{metadata['package']}/build.sh)",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _upload_asset(upload_url: str, path: Path, token: str, opener=None) -> None:
    base_url = upload_url.split("{", 1)[0]
    separator = "&" if "?" in base_url else "?"
    url = f"{base_url}{separator}{urlencode({'name': path.name})}"
    request = Request(
        url,
        data=path.read_bytes(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with (opener or urlopen)(request, timeout=120) as response:
            response.read()
    except (HTTPError, OSError) as error:
        raise PublishError(f"uploading release asset {path.name} failed: {error}") from error


def publish_releases(
    assets_dir: str | Path,
    repository: str,
    token: str,
    commit: str,
    opener=None,
) -> list[str]:
    assets_root = Path(assets_dir)
    releases = _release_assets(assets_root)
    published = []

    for tag, items in sorted(releases.items()):
        notes = _release_notes(repository, commit, items)
        metadata = items[0]["metadata"]
        endpoint = f"/releases/tags/{quote(tag, safe='')}"
        release = _request_json(repository, endpoint, token, allow_404=True, opener=opener)
        if release and not release.get("draft", False):
            print(f"Release already published; leaving immutable tag unchanged: {tag}")
            continue
        if release is None:
            release = _request_json(
                repository,
                "/releases",
                token,
                method="POST",
                payload={
                    "tag_name": tag,
                    "target_commitish": commit,
                    "name": f"{metadata['dname']} {metadata['version']}",
                    "body": notes,
                    "draft": True,
                    "prerelease": False,
                },
                opener=opener,
            )
        else:
            release = _request_json(
                repository,
                f"/releases/{release['id']}",
                token,
                method="PATCH",
                payload={"body": notes},
                opener=opener,
            )

        upload_url = release.get("upload_url")
        if not upload_url:
            raise PublishError(f"GitHub release {tag} did not provide an upload URL")
        existing_assets = {asset["name"]: asset for asset in release.get("assets", [])}
        expected_files = []
        for item in sorted(items, key=lambda entry: entry["metadata"]["asset_name"]):
            expected_files.extend((item["asset"], item["checksum"], item["metadata_path"]))
        for path in expected_files:
            previous = existing_assets.get(path.name)
            if previous:
                if previous.get("size") != path.stat().st_size:
                    raise PublishError(f"draft release already has a different asset named {path.name}")
                continue
            _upload_asset(upload_url, path, token, opener)

        _request_json(
            repository,
            f"/releases/{release['id']}",
            token,
            method="PATCH",
            payload={"body": notes, "draft": False},
            opener=opener,
        )
        release_url = release.get("html_url", f"https://github.com/{repository}/releases/tag/{quote(tag, safe='')}")
        print(f"Published {tag}: {release_url}")
        published.append(tag)
    return published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA"))
    args = parser.parse_args(argv)

    if not args.repository or not args.token or not args.commit:
        parser.error("--repository, --token and --commit (or their GitHub environment variables) are required")
    try:
        publish_releases(args.assets_dir, args.repository, args.token, args.commit)
    except (OSError, PublishError) as error:
        print(f"publish error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())