import shutil
import tempfile
import unittest
from pathlib import Path

from common.synopkg.config import load_package
from common.synopkg.discover import (
    DiscoveryError,
    discovery_branch,
    discover_packages,
    package_config_with_target,
)


FIXTURES = Path(__file__).parent / "fixtures"

NEW_TARGET = {
    "platform": "geminilakenk",
    "arch": "x86_64",
    "source_build": "7.4-95000",
    "kernel_release": "5.10.70+",
    "vermagic": "5.10.70+ SMP mod_unload",
    "dsm_builds": [95000],
}


class DiscoveryTests(unittest.TestCase):
    def test_config_update_adds_target_and_duplicate_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "package.yml"
            shutil.copy2(FIXTURES / "package.yml", config_path)

            updated = package_config_with_target(config_path, NEW_TARGET)

            self.assertIsNotNone(updated)
            config_path.write_text(updated, encoding="utf-8")
            package = load_package(config_path)
            self.assertEqual("7.4-95000", package["targets"][-1]["source_build"])
            self.assertEqual([95000], package["targets"][-1]["dsm_builds"])
            self.assertIsNone(package_config_with_target(config_path, NEW_TARGET))

    def test_invalid_discovery_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "package.yml"
            shutil.copy2(FIXTURES / "package.yml", config_path)
            invalid = dict(NEW_TARGET, dsm_builds=[])
            with self.assertRaises(DiscoveryError):
                package_config_with_target(config_path, invalid)

    def test_dry_run_emits_branch_proposal_without_editing_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary)
            package_dir = repository_root / "packages" / "hidraw-enable"
            package_dir.mkdir(parents=True)
            config_path = package_dir / "package.yml"
            shutil.copy2(FIXTURES / "package.yml", config_path)
            original = config_path.read_bytes()
            (package_dir / "discover.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            result = discover_packages(
                repository_root / "packages",
                repository_root,
                "martinskuta/synology-packages",
                dry_run=True,
                hook_runner=lambda package_dir, root: [NEW_TARGET],
            )

            self.assertEqual(1, len(result))
            self.assertEqual(
                "discover/hidraw-enable-geminilakenk-x86_64-7.4-95000", result[0]["branch"]
            )
            self.assertEqual(original, config_path.read_bytes())
            self.assertEqual(
                "discover/hidraw-enable-geminilakenk-x86_64-7.4-95000",
                discovery_branch("hidraw-enable", NEW_TARGET),
            )


if __name__ == "__main__":
    unittest.main()