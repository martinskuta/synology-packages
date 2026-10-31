import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from common.synopkg.plan import build_plan, github_tag_exists


FIXTURES = Path(__file__).parent / "fixtures"


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.packages_dir = Path(self.temporary.name) / "packages"
        self.package_dir = self.packages_dir / "hidraw-enable"
        self.package_dir.mkdir(parents=True)
        shutil.copy2(FIXTURES / "package.yml", self.package_dir / "package.yml")

    def tearDown(self):
        self.temporary.cleanup()

    def test_build_plan_emits_resolved_target(self):
        matrix = build_plan(
            self.packages_dir,
            resolver=lambda target: {
                "toolchain_url": "https://example.test/toolchain.txz",
                "kernel_url": "https://example.test/kernel.txz",
            },
        )

        self.assertEqual(1, len(matrix))
        self.assertEqual("hidraw-enable", matrix[0]["package"])
        self.assertEqual("7.4.90080-1", matrix[0]["version"])
        self.assertEqual("7.4-90080", matrix[0]["os_min_ver"])
        self.assertEqual("https://example.test/kernel.txz", matrix[0]["kernel_url"])

    def test_existing_release_tag_is_skipped(self):
        matrix = build_plan(
            self.packages_dir,
            repository="martinskuta/synology-packages",
            tag_exists=lambda repository, tag, token: tag == "hidraw-enable/v7.4.90080-1",
            resolver=lambda _: self.fail("existing release should not resolve build inputs"),
        )
        self.assertEqual([], matrix)

    def test_github_release_lookup_uses_encoded_tag_and_bearer_token(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        with patch("common.synopkg.plan.urlopen", return_value=Response()) as open_url:
            self.assertTrue(
                github_tag_exists("martinskuta/synology-packages", "hidraw-enable/v1", "token")
            )
        request = open_url.call_args.args[0]
        self.assertIn("hidraw-enable%2Fv1", request.full_url)
        self.assertEqual("Bearer token", request.get_header("Authorization"))

    def test_missing_github_release_tag_returns_false(self):
        error = HTTPError("https://api.github.test/release", 404, "not found", {}, None)
        with patch("common.synopkg.plan.urlopen", side_effect=error):
            self.assertFalse(
                github_tag_exists("martinskuta/synology-packages", "hidraw-enable/v1")
            )


if __name__ == "__main__":
    unittest.main()