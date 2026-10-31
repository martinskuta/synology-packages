"""Build a DSM package source index from GitHub Releases."""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import zlib
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class IndexError(RuntimeError):
    """Raised when release metadata or package icons cannot be indexed."""


VERSION_RE = re.compile(r"^(?P<source>\d+(?:\.\d+)*)-(?P<build>\d+)-(?P<revision>\d+)$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _request(url: str, token: str, opener=None):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        return (opener or urlopen)(request, timeout=60)
    except (HTTPError, OSError) as error:
        raise IndexError(f"GitHub request failed for {url}: {error}") from error


def _next_page(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for link in link_header.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="next"', link)
        if match:
            return match.group(1)
    return None


def _read_json_response(response, url: str):
    try:
        return json.loads(response.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IndexError(f"invalid JSON response from {url}: {error}") from error


def fetch_release_metadata(repository: str, token: str, opener=None) -> list[dict]:
    """Fetch all release pages and parse each published .meta.json asset."""

    url = f"https://api.github.com/repos/{repository}/releases?per_page=100&page=1"
    metadata_items = []
    page_number = 1
    while url:
        with _request(url, token, opener) as response:
            releases = _read_json_response(response, url)
            next_url = _next_page(response.headers.get("Link"))
        if not isinstance(releases, list):
            raise IndexError(f"GitHub releases response was not a list: {url}")

        for release in releases:
            for asset in release.get("assets", []):
                if not asset.get("name", "").endswith(".meta.json"):
                    continue
                download_url = asset.get("browser_download_url")
                if not download_url:
                    raise IndexError(f"release metadata asset has no download URL: {asset.get('name')}")
                with _request(download_url, token, opener) as response:
                    metadata = _read_json_response(response, download_url)
                if not isinstance(metadata, dict):
                    raise IndexError(f"release metadata asset is not a JSON object: {download_url}")
                metadata_items.append(metadata)

        if next_url:
            url = next_url
        elif len(releases) == 100:
            page_number += 1
            url = f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page_number}"
        else:
            url = ""
    return metadata_items


def version_key(version: str) -> tuple:
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise IndexError(f"invalid package version {version!r}")
    source_parts = tuple(int(part) for part in match.group("source").split("."))
    return source_parts, int(match.group("build")), int(match.group("revision"))


def _arch_list(meta: dict) -> list[str]:
    value = meta.get("arch")
    if isinstance(value, str):
        result = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        result = value
    else:
        raise IndexError(f"release metadata has invalid DSM arch: {value!r}")
    if not result:
        raise IndexError("release metadata arch list cannot be empty")
    return sorted(set(result))


def latest_metadata(metadata_items: list[dict]) -> list[dict]:
    latest: dict[tuple, tuple[tuple, dict]] = {}
    for meta in metadata_items:
        required = ("package", "version", "platform", "dsm_builds", "link", "md5", "size")
        if any(key not in meta for key in required):
            raise IndexError(f"release metadata is missing a required field: {meta!r}")
        if not isinstance(meta["dsm_builds"], list) or not meta["dsm_builds"]:
            raise IndexError(f"release metadata has invalid dsm_builds: {meta['dsm_builds']!r}")
        builds = tuple(sorted(int(build) for build in meta["dsm_builds"]))
        identity = (meta["package"], meta["platform"], builds)
        key = version_key(meta["version"])
        previous = latest.get(identity)
        if previous is None or key > previous[0]:
            latest[identity] = (key, meta)

    return [entry[1] for entry in latest.values()]


def build_index(metadata_items: list[dict], base_url: str) -> dict:
    packages = []
    for meta in latest_metadata(metadata_items):
        package = {
            "package": meta["package"],
            "version": meta["version"],
            "dname": meta.get("dname", meta.get("displayname", meta["package"])),
            "desc": meta.get("desc", meta.get("description", "")),
            "link": meta["link"],
            "md5": meta["md5"],
            "size": int(meta["size"]),
            "thumbnail": [
                f"{base_url.rstrip('/')}/{meta['package']}_72.png",
                f"{base_url.rstrip('/')}/{meta['package']}_120.png",
            ],
            "maintainer": meta.get("maintainer", ""),
            "qinst": True,
            "qupgrade": True,
            "qstart": True,
            "beta": False,
            "arch": _arch_list(meta),
            "dsm_builds": sorted(int(build) for build in meta["dsm_builds"]),
            "os_min_ver": meta.get("os_min_ver", ""),
            "os_max_ver": meta.get("os_max_ver", ""),
        }
        packages.append(package)

    packages.sort(key=lambda item: (item["package"], item["arch"], item["dsm_builds"]))
    return {"packages": packages}


def _paeth(left: int, above: int, upper_left: int) -> int:
    prediction = left + above - upper_left
    left_distance = abs(prediction - left)
    above_distance = abs(prediction - above)
    corner_distance = abs(prediction - upper_left)
    if left_distance <= above_distance and left_distance <= corner_distance:
        return left
    if above_distance <= corner_distance:
        return above
    return upper_left


def _read_png(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise IndexError(f"package icon is not a PNG: {path}")
    offset = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = None
    compressed = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">2I5B", chunk
            )
            if compression != 0 or filter_method != 0:
                raise IndexError(f"unsupported PNG encoding in {path}")
        elif kind == b"IDAT":
            compressed.extend(chunk)
        elif kind == b"IEND":
            break

    if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
        raise IndexError(f"{path} must be a non-interlaced 8-bit RGB/RGBA PNG")
    bytes_per_pixel = 4 if color_type == 6 else 3
    row_size = width * bytes_per_pixel
    raw = zlib.decompress(compressed)
    expected_size = height * (row_size + 1)
    if len(raw) != expected_size:
        raise IndexError(f"PNG pixel data has an unexpected size: {path}")

    pixels = bytearray()
    previous = bytearray(row_size)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        filtered = raw[cursor : cursor + row_size]
        cursor += row_size
        row = bytearray(row_size)
        for index, value in enumerate(filtered):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                predictor = _paeth(left, above, upper_left)
            else:
                raise IndexError(f"unsupported PNG row filter {filter_type} in {path}")
            row[index] = (value + predictor) & 0xFF
        if color_type == 6:
            pixels.extend(row)
        else:
            for index in range(0, len(row), 3):
                pixels.extend((row[index], row[index + 1], row[index + 2], 255))
        previous = row
    return width, height, bytes(pixels)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    raw = bytearray()
    row_size = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * row_size : (y + 1) * row_size])
    content = PNG_SIGNATURE
    content += _png_chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0))
    content += _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
    content += _png_chunk(b"IEND", b"")
    path.write_bytes(content)


def _write_thumbnails(package_names: set[str], package_root: Path, site_dir: Path) -> None:
    for package_name in sorted(package_names):
        icon_path = package_root / package_name / "spk" / "PACKAGE_ICON_256.PNG"
        if not icon_path.is_file():
            raise IndexError(f"missing package icon for {package_name}: {icon_path}")
        width, height, pixels = _read_png(icon_path)
        for size in (72, 120):
            resized = bytearray(size * size * 4)
            for y in range(size):
                source_y = min(height - 1, y * height // size)
                for x in range(size):
                    source_x = min(width - 1, x * width // size)
                    source = (source_y * width + source_x) * 4
                    target = (y * size + x) * 4
                    resized[target : target + 4] = pixels[source : source + 4]
            _write_png(site_dir / f"{package_name}_{size}.png", size, size, bytes(resized))


def generate_site(
    metadata_items: list[dict],
    package_root: str | Path,
    output_dir: str | Path,
    base_url: str,
) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    index = build_index(metadata_items, base_url)
    _write_thumbnails(
        {package["package"] for package in index["packages"]},
        Path(package_root),
        output_path,
    )
    content = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    (output_path / "index.json").write_text(content, encoding="utf-8")
    (output_path / "index.html").write_text(content, encoding="utf-8")
    return index


def default_pages_url(repository: str) -> str:
    owner, repo_name = repository.split("/", 1)
    return f"https://{owner}.github.io/{repo_name}"


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "martinskuta/synology-packages"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--package-root", type=Path, default=root / "packages")
    parser.add_argument("--output-dir", type=Path, default=root / "site")
    parser.add_argument("--base-url")
    args = parser.parse_args(argv)
    if not args.token:
        parser.error("--token or GITHUB_TOKEN is required")

    try:
        metadata = fetch_release_metadata(args.repository, args.token)
        generate_site(
            metadata,
            args.package_root,
            args.output_dir,
            args.base_url or default_pages_url(args.repository),
        )
    except (IndexError, OSError, ValueError) as error:
        print(f"index error: {error}", file=sys.stderr)
        return 1
    print(f"Wrote package index to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())