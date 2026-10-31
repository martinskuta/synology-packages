import shutil
import tempfile
import unittest
from pathlib import Path

from common.synopkg.config import ConfigError, asset_name, load_package, release_tag, target_metadata


FIXTURES = Path(__file__).parent / "fixtures"


class PackageConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temporary.name) / "package.yml"
        shutil.copy2(FIXTURES / "package.yml", self.config_path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_loads_metadata_and_derives_names_and_os_bounds(self):
        package = load_package(self.config_path)
        target = package["targets"][0]

        self.assertEqual("7.4.90080-1", target_metadata(package, target)["version"])
        self.assertEqual("hidraw-enable/v7.4.90080-1", release_tag(package, target))
        self.assertEqual(
            "hidraw-enable_geminilakenk_7.4.90080-1.spk", asset_name(package, target)
        )
        self.assertEqual("7.4-90080", target_metadata(package, target)["os_min_ver"])
        self.assertEqual("7.4-90081", target_metadata(package, target)["os_max_ver"])

    def test_rejects_missing_and_invalid_fields(self):
        original = self.config_path.read_text(encoding="utf-8")
        cases = (
            (original.replace("revision: 1", "revision: 0"), "revision"),
            (original.replace("dsm_builds: [90080, 90081]", "dsm_builds: []"), "dsm_builds"),
            (original.replace('source_build: "7.4-90080"', 'source_build: "invalid"'), "source_build"),
            (original.replace("dsm_builds: [90080, 90081]", "dsm_builds: [89999]"), "precede"),
        )
        for content, expected in cases:
            with self.subTest(expected=expected):
                self.config_path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ConfigError, expected):
                    load_package(self.config_path)


if __name__ == "__main__":
    unittest.main()