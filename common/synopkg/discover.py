"""Open one pull request for each newer target emitted by a package hook."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from .config import ConfigError, load_package


class DiscoveryError(RuntimeError):
    """Raised when a package hook or pull request operation fails."""


def package_config_with_target(config_path: str | Path, target: dict) -> str | None:
    """Return validated YAML with target appended, or None if it is already configured."""

    path = Path(config_path)
    try:
        load_package(path)
        package_data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (ConfigError, OSError, yaml.YAMLError) as error:
        raise DiscoveryError(f"cannot read package config {path}: {error}") from error
    if not isinstance(package_data, dict) or not isinstance(package_data.get("targets"), list):
        raise DiscoveryError(f"invalid package config structure: {path}")

    duplicate = any(
        existing.get("platform") == target.get("platform")
        and existing.get("arch") == target.get("arch")
        and existing.get("source_build") == target.get("source_build")
        for existing in package_data["targets"]
    )
    if duplicate:
        return None

    package_data["targets"].append(dict(target))
    contents = yaml.safe_dump(package_data, sort_keys=False, allow_unicode=True, width=100)
    try:
        with tempfile.TemporaryDirectory(prefix="synopkg-config-check-") as temporary:
            temporary_path = Path(temporary) / "package.yml"
            temporary_path.write_text(contents, encoding="utf-8")
            load_package(temporary_path)
    except ConfigError as error:
        raise DiscoveryError(f"discovered target is invalid for {path}: {error}") from error
    return contents


def parse_hook_targets(output: str) -> list[dict]:
    targets = []
    required = {"platform", "arch", "source_build", "kernel_release", "vermagic", "dsm_builds"}
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            target = json.loads(line)
        except json.JSONDecodeError as error:
            raise DiscoveryError(f"discover hook line {line_number} is not valid JSON: {error}") from error
        if not isinstance(target, dict) or not required.issubset(target):
            raise DiscoveryError(f"discover hook line {line_number} is missing target fields")
        for key in required - {"dsm_builds"}:
            if not isinstance(target[key], str) or not target[key].strip():
                raise DiscoveryError(f"discover hook line {line_number} has invalid {key}")
        if not isinstance(target["dsm_builds"], list) or not target["dsm_builds"]:
            raise DiscoveryError(f"discover hook line {line_number} has invalid dsm_builds")
        targets.append(target)
    return targets


def run_discover_hook(package_dir: str | Path, repository_root: str | Path) -> list[dict]:
    package_path = Path(package_dir).resolve()
    hook = package_path / "discover.sh"
    if not hook.is_file():
        return []
    environment = os.environ.copy()
    environment["PACKAGE_DIR"] = str(package_path)
    root = str(Path(repository_root).resolve())
    environment["PYTHONPATH"] = root + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    result = subprocess.run(
        ["sh", str(hook)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise DiscoveryError(
            f"{package_path.name}/discover.sh failed ({result.returncode}): {result.stderr.strip()}"
        )
    return parse_hook_targets(result.stdout)


def _run(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if check and result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        raise DiscoveryError(f"command failed ({result.returncode}): {' '.join(command)}\n{details}")
    return result


def _branch_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-").lower()


def discovery_branch(package: str, target: dict) -> str:
    return "discover/" + _branch_slug(
        f"{package}-{target['platform']}-{target['arch']}-{target['source_build']}"
    )


def _branch_or_pr_exists(
    repository_root: Path, repository: str, branch: str, token: str | None
) -> bool:
    remote = _run(
        ["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
        repository_root,
        check=False,
    )
    if remote.returncode:
        raise DiscoveryError(f"could not check remote branch {branch}: {remote.stderr.strip()}")
    if remote.stdout.strip():
        return True

    local = _run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        repository_root,
        check=False,
    )
    if local.returncode == 0:
        return True

    environment = os.environ.copy()
    if token:
        environment["GH_TOKEN"] = token
    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repository,
            "--head",
            branch,
            "--state",
            "all",
            "--json",
            "number",
        ],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise DiscoveryError(f"could not check pull requests for {branch}: {result.stderr.strip()}")
    try:
        return bool(json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise DiscoveryError(f"gh returned invalid JSON while checking {branch}: {error}") from error


def _create_pull_request(
    repository_root: Path,
    repository: str,
    package_dir: Path,
    target: dict,
    branch: str,
    base_branch: str,
    token: str | None,
) -> str:
    if _branch_or_pr_exists(repository_root, repository, branch, token):
        return ""

    with tempfile.TemporaryDirectory(prefix="synopkg-discovery-") as temporary:
        worktree = Path(temporary) / "checkout"
        _run(
            ["git", "worktree", "add", "--quiet", "-b", branch, str(worktree), f"origin/{base_branch}"],
            repository_root,
        )
        try:
            config_path = worktree / "packages" / package_dir.name / "package.yml"
            contents = package_config_with_target(config_path, target)
            if contents is None:
                return ""
            config_path.write_text(contents, encoding="utf-8")
            _run(["git", "config", "user.name", "github-actions[bot]"], worktree)
            _run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], worktree)
            _run(["git", "add", "--", str(config_path.relative_to(worktree))], worktree)
            _run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"Add {target['source_build']} target for {package_dir.name}",
                ],
                worktree,
            )
            _run(["git", "push", "--set-upstream", "origin", branch], worktree)

            environment = os.environ.copy()
            if token:
                environment["GH_TOKEN"] = token
            title = f"Add {target['source_build']} target for {package_dir.name}"
            body = (
                f"Add the discovered Synology source build `{target['source_build']}` for "
                f"`{target['platform']}` / `{target['arch']}`.\n\n"
                f"The proposed kernel release is `{target['kernel_release']}` with vermagic "
                f"`{target['vermagic']}`; CI will verify it against the built module."
            )
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    repository,
                    "--base",
                    base_branch,
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body",
                    body,
                ],
                cwd=worktree,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise DiscoveryError(f"could not open PR for {branch}: {result.stderr.strip()}")
            return result.stdout.strip()
        finally:
            _run(["git", "worktree", "remove", "--force", str(worktree)], repository_root, check=False)
            _run(["git", "branch", "-D", branch], repository_root, check=False)


def discover_packages(
    packages_dir: str | Path,
    repository_root: str | Path,
    repository: str,
    base_branch: str = "master",
    token: str | None = None,
    dry_run: bool = False,
    hook_runner=run_discover_hook,
) -> list[dict]:
    packages_path = Path(packages_dir).resolve()
    root_path = Path(repository_root).resolve()
    results = []
    for package_dir in sorted(path for path in packages_path.iterdir() if path.is_dir()):
        config_path = package_dir / "package.yml"
        if not config_path.is_file() or not (package_dir / "discover.sh").is_file():
            continue
        package = load_package(config_path)
        if package["package"] != package_dir.name:
            raise DiscoveryError(
                f"package directory {package_dir.name!r} does not match package id {package['package']!r}"
            )
        configured = {
            (target["platform"], target["arch"], target["source_build"])
            for target in package["targets"]
        }
        for target in hook_runner(package_dir, root_path):
            identity = (target["platform"], target["arch"], target["source_build"])
            if identity in configured:
                continue
            configured.add(identity)
            branch = discovery_branch(package["package"], target)
            contents = package_config_with_target(config_path, target)
            if contents is None:
                continue
            if dry_run:
                results.append({"package": package["package"], "branch": branch, "target": target})
                print(json.dumps(results[-1], separators=(",", ":")))
                continue
            pull_request = _create_pull_request(
                root_path,
                repository,
                package_dir,
                target,
                branch,
                base_branch,
                token,
            )
            if pull_request:
                result = {"package": package["package"], "branch": branch, "pull_request": pull_request}
                results.append(result)
                print(json.dumps(result, separators=(",", ":")))
    return results


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages-dir", type=Path, default=root / "packages")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--base", default="master")
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.repository:
        parser.error("--repository or GITHUB_REPOSITORY is required")
    if not args.dry_run and not args.token:
        parser.error("--token, GH_TOKEN or GITHUB_TOKEN is required")

    try:
        discover_packages(
            args.packages_dir,
            root,
            args.repository,
            args.base,
            args.token,
            args.dry_run,
        )
    except (ConfigError, DiscoveryError, OSError) as error:
        print(f"discovery error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())