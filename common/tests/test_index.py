import json
import tempfile
import unittest
from pathlib import Path

from common.synopkg.index import (
    fetch_release_metadata,
    generate_site,
    latest_metadata,
    version_key,
    _read_png,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages"


def metadata(version, dsm_builds=(90080,), platform="geminilakenk"):
    return {
        "package": "hidraw-enable",
        "version": version,
        "dname": "HIDRAW Support",
        "desc": "Loads HIDRAW support.",
        "link": f"https://github.test/{version}.spk",
        "md5": "0123456789abcdef0123456789abcdef",
        "size": 123,
        "maintainer": "martinskuta",
        "arch": platform,
        "platform": platform,
        "dsm_builds": list(dsm_builds),
        "os_min_ver": "7.4-90080",
        "os_max_ver": f"7.4-{max(dsm_builds)}",
    }


class _Response:
    def __init__(self, payload, headers=None):
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class PackageIndexTests(unittest.TestCase):
    def test_latest_revision_is_selected_per_package_platform_and_dsm_builds(self):
        revisions = [
            metadata("7.4.90080-1"),
            metadata("7.4.90080-2"),
            metadata("7.4.90080-3", dsm_builds=(90082,)),
            metadata("7.4.90080-1", platform="anotherplatform"),
        ]

        latest = latest_metadata(revisions)

        self.assertEqual(3, len(latest))
        self.assertIn("7.4.90080-2", [item["version"] for item in latest])
        self.assertEqual(((7, 4, 90080), 2), version_key("7.4.90080-2"))
        self.assertLess(version_key("7.4.90080-9"), version_key("7.5.95000-1"))

    def test_releases_with_versions_dsm_rejects_are_not_listed(self):
        latest = latest_metadata([metadata("7.4-90080-1"), metadata("7.4.90080-1")])

        self.assertEqual(["7.4.90080-1"], [item["version"] for item in latest])
        self.assertEqual([], latest_metadata([metadata("7.4-90080-1")]))

    def test_index_fields_and_site_outputs_are_dsm_and_worker_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "site"
            result = generate_site(
                [metadata("7.4.90080-1")],
                PACKAGE_ROOT,
                output_dir,
                "https://martinskuta.github.io/synology-packages",
            )

            package = result["packages"][0]
            self.assertEqual(["geminilakenk"], package["arch"])
            self.assertEqual([90080], package["dsm_builds"])
            self.assertTrue(package["qinst"])
            self.assertTrue(package["qupgrade"])
            self.assertTrue(package["qstart"])
            self.assertFalse(package["beta"])
            self.assertEqual(
                [
                    "https://martinskuta.github.io/synology-packages/hidraw-enable_72.png",
                    "https://martinskuta.github.io/synology-packages/hidraw-enable_120.png",
                ],
                package["thumbnail"],
            )
            self.assertEqual(
                (output_dir / "index.json").read_bytes(),
                (output_dir / "index.html").read_bytes(),
            )
            self.assertEqual(72, _read_png(output_dir / "hidraw-enable_72.png")[0])
            self.assertEqual(120, _read_png(output_dir / "hidraw-enable_120.png")[0])
            self.assertEqual("7.4.90080-1", json.loads((output_dir / "index.json").read_text())["packages"][0]["version"])

    def test_release_metadata_fetch_follows_github_pagination(self):
        first_page_url = "https://api.github.com/repos/owner/repo/releases?per_page=100&page=1"
        next_page_url = "https://api.github.com/repos/owner/repo/releases?per_page=100&page=2"
        first_asset_url = "https://github.test/first.meta.json"
        second_asset_url = "https://github.test/second.meta.json"
        responses = [
            _Response(
                [{"assets": [{"name": "first.meta.json", "browser_download_url": first_asset_url}]}],
                {"Link": f'<{next_page_url}>; rel="next"'},
            ),
            _Response(metadata("7.4-90080-1")),
            _Response(
                [{"assets": [{"name": "second.meta.json", "browser_download_url": second_asset_url}]}]
            ),
            _Response(metadata("7.4-90080-2")),
        ]
        requests = []

        def opener(request, timeout):
            requests.append(request.full_url)
            return responses.pop(0)

        fetched = fetch_release_metadata("owner/repo", "token", opener=opener)

        self.assertEqual(["7.4-90080-1", "7.4-90080-2"], [item["version"] for item in fetched])
        self.assertEqual(
            [first_page_url, first_asset_url, next_page_url, second_asset_url], requests
        )
        self.assertFalse(responses)


if __name__ == "__main__":
    unittest.main()