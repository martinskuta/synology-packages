"""Loading and validating package metadata and target configuration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


PACKAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SOURCE_BUILD_RE = re.compile(r"^(?P<version>\d+(?:\.\d+)*)-(?P<build>\d+)$")
OS_VERSION_RE = re.compile(r"^(?P<version>\d+(?:\.\d+)*)-(?P<build>\d+)$")
INFO_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
TARGET_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class ConfigError(ValueError):
    """Raised when package metadata is missing or inconsistent."""


def parse_os_version(value: str) -> tuple[tuple[int, ...], int]:
    match = OS_VERSION_RE.fullmatch(value)
    if not match:
        raise ConfigError(f"invalid DSM version {value!r}; expected '<version>-<build>'")
    return tuple(int(part) for part in match.group("version").split(".")), int(match.group("build"))


def _require_text(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label}: {key} must be a non-empty string")
    if any(character in value for character in "\r\n\0"):
        raise ConfigError(f"{label}: {key} cannot contain line breaks or NUL bytes")
    return value.strip()


def _validate_target(target: Any, label: str) -> dict[str, Any]:
    if not isinstance(target, dict):
        raise ConfigError(f"{label}: each target must be a mapping")

    normalized = dict(target)
    for key in ("platform", "arch", "source_build", "kernel_release", "vermagic"):
        normalized[key] = _require_text(target, key, label)
    for key in ("platform", "arch"):
        if not TARGET_COMPONENT_RE.fullmatch(normalized[key]):
            raise ConfigError(f"{label}: {key} contains unsupported characters")

    source_match = SOURCE_BUILD_RE.fullmatch(normalized["source_build"])
    if not source_match:
        raise ConfigError(f"{label}: source_build must have the form '<version>-<build>'")

    builds = target.get("dsm_builds")
    if not isinstance(builds, list) or not builds:
        raise ConfigError(f"{label}: dsm_builds must be a non-empty list")
    normalized_builds = []
    for build in builds:
        if isinstance(build, bool) or not (isinstance(build, int) or str(build).isdigit()):
            raise ConfigError(f"{label}: DSM builds must be positive integers")
        build_number = int(build)
        if build_number <= 0:
            raise ConfigError(f"{label}: DSM builds must be positive integers")
        normalized_builds.append(build_number)
    if len(set(normalized_builds)) != len(normalized_builds):
        raise ConfigError(f"{label}: dsm_builds contains duplicates")
    normalized["dsm_builds"] = sorted(normalized_builds)
    if min(normalized_builds) < int(source_match.group("build")):
        raise ConfigError(f"{label}: dsm_builds cannot precede source_build")

    for key in ("toolchain_url", "kernel_url"):
        if key in target and (not isinstance(target[key], str) or not target[key].strip()):
            raise ConfigError(f"{label}: {key} must be a non-empty string when provided")
        if key in target:
            normalized[key] = target[key].strip()
            parsed_url = urlparse(normalized[key])
            if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
                raise ConfigError(f"{label}: {key} must be an absolute HTTP(S) URL")

    return normalized


def load_package(path: str | Path) -> dict[str, Any]:
    """Load one package.yml file and return normalized metadata."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigError(f"cannot read {config_path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"invalid YAML in {config_path}: {error}") from error

    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path}: package.yml must contain a mapping")

    package = dict(raw)
    package_name = _require_text(package, "package", str(config_path))
    if not PACKAGE_NAME_RE.fullmatch(package_name):
        raise ConfigError(f"{config_path}: invalid package identifier {package_name!r}")
    package["package"] = package_name

    for key in ("displayname", "description", "maintainer"):
        package[key] = _require_text(package, key, str(config_path))

    revision = package.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ConfigError(f"{config_path}: revision must be a positive integer")

    support_url = package.get("support_url")
    if support_url is not None and (not isinstance(support_url, str) or not support_url.strip()):
        raise ConfigError(f"{config_path}: support_url must be a non-empty string when provided")
    package["support_url"] = (support_url or "https://github.com/").strip()
    if any(character in package["support_url"] for character in "\r\n\0"):
        raise ConfigError(f"{config_path}: support_url cannot contain line breaks or NUL bytes")
    support_parsed = urlparse(package["support_url"])
    if support_parsed.scheme not in ("http", "https") or not support_parsed.netloc:
        raise ConfigError(f"{config_path}: support_url must be an absolute HTTP(S) URL")

    os_min_ver = package.get("os_min_ver")
    if os_min_ver is not None:
        if not isinstance(os_min_ver, str):
            raise ConfigError(f"{config_path}: os_min_ver must be a DSM version string")
        parse_os_version(os_min_ver)
    package["os_min_ver"] = os_min_ver

    targets = package.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ConfigError(f"{config_path}: targets must be a non-empty list")

    normalized_targets = []
    seen = set()
    for index, target in enumerate(targets):
        label = f"{config_path}: targets[{index}]"
        normalized_target = _validate_target(target, label)
        key = (
            normalized_target["platform"],
            normalized_target["arch"],
            normalized_target["source_build"],
        )
        if key in seen:
            raise ConfigError(f"{label}: duplicate target {key!r}")
        seen.add(key)
        if os_min_ver:
            floor = parse_os_version(os_min_ver)
            target_min = (tuple(int(part) for part in SOURCE_BUILD_RE.fullmatch(
                normalized_target["source_build"]
            ).group("version").split(".")), min(normalized_target["dsm_builds"]))
            if target_min < floor:
                raise ConfigError(
                    f"{label}: earliest supported build is below package os_min_ver {os_min_ver}"
                )
        normalized_targets.append(normalized_target)

    package["targets"] = normalized_targets
    package["_path"] = config_path.resolve()
    return package


def target_os_versions(package: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    """Return the DSM version bounds represented by a target's allowed build list."""

    source_match = SOURCE_BUILD_RE.fullmatch(target["source_build"])
    if not source_match:
        raise ConfigError(f"invalid source_build {target['source_build']!r}")
    version = source_match.group("version")
    return (
        f"{version}-{min(target['dsm_builds'])}",
        f"{version}-{max(target['dsm_builds'])}",
    )


def target_metadata(package: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    os_min_ver, os_max_ver = target_os_versions(package, target)
    return {
        "package": package["package"],
        "version": f"{target['source_build']}-{package['revision']}",
        "tag": release_tag(package, target),
        "asset_name": asset_name(package, target),
        "os_min_ver": os_min_ver,
        "os_max_ver": os_max_ver,
    }


def release_tag(package: dict[str, Any], target: dict[str, Any]) -> str:
    return f"{package['package']}/v{target['source_build']}-{package['revision']}"


def asset_name(package: dict[str, Any], target: dict[str, Any]) -> str:
    version = f"{target['source_build']}-{package['revision']}"
    return f"{package['package']}_{target['platform']}_{version}.spk"


def info_quote(value: Any) -> str:
    """Quote a value for the key=value format consumed by DSM package metadata."""

    text = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{text}"'


def validate_info_key(key: str) -> bool:
    return bool(INFO_KEY_RE.fullmatch(key))