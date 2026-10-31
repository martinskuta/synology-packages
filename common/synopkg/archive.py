"""Resolve Synology toolchain and GPL source archive URLs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from .config import ConfigError, load_package


ARCHIVE_BASE = "https://archive.synology.com/download/ToolChain"
TOOLCHAIN_LISTING = ARCHIVE_BASE + "/toolchain/{source_build}"
GPL_LISTING = ARCHIVE_BASE + "/Synology%20NAS%20GPL%20Source/{source_build}"
TOOLCHAIN_ROOT_LISTING = ARCHIVE_BASE + "/toolchain"
GPL_ROOT_LISTING = ARCHIVE_BASE + "/Synology%20NAS%20GPL%20Source"
SOURCE_BUILD_PATTERN = re.compile(r"^(?P<version>\d+(?:\.\d+)*)-(?P<build>\d+)$")


class ArchiveResolutionError(RuntimeError):
    """Raised when archive listings contain no unambiguous matching files."""


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None
            self._text = []


def listing_links(html: str, listing_url: str) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    parser.feed(html)
    links = []
    for href, label in parser.links:
        absolute = urljoin(listing_url, href)
        path = urlparse(absolute).path
        filename = unquote(path.rstrip("/").rsplit("/", 1)[-1])
        if filename and filename not in ("..", "."):
            links.append((absolute, label or filename))
    return links


def fetch_listing(url: str) -> str:
    request = Request(url, headers={"User-Agent": "synology-package-source-builder/1.0"})
    try:
        with urlopen(request, timeout=45) as response:
            return response.read().decode("utf-8", errors="replace")
    except (OSError, URLError) as error:
        raise ArchiveResolutionError(f"cannot read Synology archive listing {url}: {error}") from error


def _matching_toolchain(links: list[tuple[str, str]], platform: str, arch: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(platform)}-gcc[^/]*_{re.escape(arch)}-GPL\.txz$",
        re.IGNORECASE,
    )
    matches = [url for url, _ in links if pattern.fullmatch(unquote(urlparse(url).path.rsplit("/", 1)[-1]))]
    if len(matches) != 1:
        raise ArchiveResolutionError(
            f"expected exactly one {platform} toolchain for {arch}, found {len(matches)}"
        )
    return matches[0]


def _matching_kernel(
    links: list[tuple[str, str]], kernel_release: str, source_build: str, platform: str
) -> str:
    candidates = []
    for url, _ in links:
        path_parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        filename = path_parts[-1] if path_parts else ""
        if platform in path_parts[:-1] and re.fullmatch(r"linux-[A-Za-z0-9._+-]+\.txz", filename):
            candidates.append((url, filename))
    if not candidates:
        raise ArchiveResolutionError(
            f"no linux-*.txz GPL source found for {platform} at {source_build}"
        )

    kernel_version = kernel_release.rstrip("+")
    exact = [url for url, name in candidates if name == f"linux-{kernel_version}.txz"]
    if len(exact) == 1:
        return exact[0]

    major_minor = ".".join(kernel_version.split(".")[:2])
    family = [url for url, name in candidates if name == f"linux-{major_minor}.x.txz"]
    if len(family) == 1:
        return family[0]
    if len(candidates) == 1:
        return candidates[0][0]
    raise ArchiveResolutionError(
        f"ambiguous linux-*.txz GPL sources for {platform} at {source_build}; "
        f"kernel_release={kernel_release!r}"
    )


def resolve_urls(target: dict, fetcher=fetch_listing) -> dict[str, str]:
    """Resolve toolchain and kernel URLs, honoring per-target overrides."""

    result = {}
    if target.get("toolchain_url"):
        result["toolchain_url"] = target["toolchain_url"]
    else:
        listing_url = TOOLCHAIN_LISTING.format(source_build=target["source_build"])
        result["toolchain_url"] = _matching_toolchain(
            listing_links(fetcher(listing_url), listing_url), target["platform"], target["arch"]
        )

    if target.get("kernel_url"):
        result["kernel_url"] = target["kernel_url"]
    else:
        listing_url = GPL_LISTING.format(source_build=target["source_build"])
        result["kernel_url"] = _matching_kernel(
            listing_links(fetcher(listing_url), listing_url),
            target["kernel_release"],
            target["source_build"],
            target["platform"],
        )
    return result


def _source_build_key(source_build: str) -> tuple:
    match = SOURCE_BUILD_PATTERN.fullmatch(source_build)
    if not match:
        raise ArchiveResolutionError(f"invalid Synology source build {source_build!r}")
    version = tuple(int(part) for part in match.group("version").split("."))
    return version, int(match.group("build"))


def _source_builds(html: str, listing_url: str) -> set[str]:
    builds = set()
    for url, _ in listing_links(html, listing_url):
        name = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
        if SOURCE_BUILD_PATTERN.fullmatch(name):
            builds.add(name)
    return builds


def _kernel_release_from_toolchain(url: str, platform: str, arch: str) -> str:
    path_parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
    if len(path_parts) < 2:
        raise ArchiveResolutionError(f"could not identify toolchain folder in {url}")
    folder_name = path_parts[-2]
    match = re.search(r"Linux(?:\s+Linux)?\s+(\d+(?:\.\d+)+)", folder_name, re.IGNORECASE)
    if not match:
        raise ArchiveResolutionError(
            f"could not infer kernel release from toolchain folder {folder_name!r} "
            f"for {platform}/{arch}"
        )
    return f"{match.group(1)}+"


def discover_new_targets(package: dict, fetcher=fetch_listing) -> list[dict]:
    """Find newer source builds that provide both a matching toolchain and GPL kernel."""

    toolchain_roots = _source_builds(fetcher(TOOLCHAIN_ROOT_LISTING), TOOLCHAIN_ROOT_LISTING)
    gpl_roots = _source_builds(fetcher(GPL_ROOT_LISTING), GPL_ROOT_LISTING)
    common_builds = sorted(toolchain_roots & gpl_roots, key=_source_build_key)
    new_targets = []
    target_groups: dict[tuple[str, str], list[dict]] = {}
    for target in package["targets"]:
        key = (target["platform"], target["arch"])
        target_groups.setdefault(key, []).append(target)

    for (platform, arch), configured in sorted(target_groups.items()):
        highest = max(_source_build_key(target["source_build"]) for target in configured)
        for source_build in common_builds:
            if _source_build_key(source_build) <= highest:
                continue

            toolchain_listing = TOOLCHAIN_LISTING.format(source_build=source_build)
            toolchain_links = listing_links(fetcher(toolchain_listing), toolchain_listing)
            try:
                toolchain_url = _matching_toolchain(toolchain_links, platform, arch)
            except ArchiveResolutionError as error:
                if "found 0" in str(error):
                    continue
                raise

            kernel_release = _kernel_release_from_toolchain(toolchain_url, platform, arch)
            gpl_listing = GPL_LISTING.format(source_build=source_build)
            gpl_links = listing_links(fetcher(gpl_listing), gpl_listing)
            try:
                _matching_kernel(gpl_links, kernel_release, source_build, platform)
            except ArchiveResolutionError as error:
                if str(error).startswith("no linux-*.txz GPL source"):
                    continue
                raise

            build_number = int(SOURCE_BUILD_PATTERN.fullmatch(source_build).group("build"))
            new_targets.append(
                {
                    "platform": platform,
                    "arch": arch,
                    "source_build": source_build,
                    "kernel_release": kernel_release,
                    "vermagic": f"{kernel_release} SMP mod_unload",
                    "dsm_builds": [build_number],
                }
            )
    return new_targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover_parser = subparsers.add_parser("discover", help="print newer package targets as JSON lines")
    discover_parser.add_argument("--package-yml", required=True)
    args = parser.parse_args(argv)

    try:
        package = load_package(args.package_yml)
        for target in discover_new_targets(package):
            print(json.dumps(target, separators=(",", ":")))
    except (ArchiveResolutionError, ConfigError, OSError) as error:
        print(f"archive discovery error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())