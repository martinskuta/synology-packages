import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

from common.synopkg.publish import publish_releases


class _Response:
    def __init__(self, payload=None):
        self.payload = json.dumps(payload or {}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class ReleasePublishingTests(unittest.TestCase):
    def create_artifacts(self, directory):
        package_dir = Path(directory) / "hidraw-enable-geminilakenk-7.4-90080-x86_64"
        package_dir.mkdir()
        asset_name = "hidraw-enable_geminilakenk_7.4-90080-1.spk"
        asset = package_dir / asset_name
        asset.write_bytes(b"package archive")
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        (package_dir / "hidraw-enable_geminilakenk_7.4-90080-1.sha256").write_text(
            f"{digest}  {asset_name}\n", encoding="utf-8"
        )
        metadata = {
            "asset_name": asset_name,
            "dname": "HIDRAW Support",
            "package": "hidraw-enable",
            "platform": "geminilakenk",
            "target_arch": "x86_64",
            "source_build": "7.4-90080",
            "tag": "hidraw-enable/v7.4-90080-1",
            "version": "7.4-90080-1",
            "sha256": digest,
            "size": asset.stat().st_size,
        }
        (package_dir / "hidraw-enable_geminilakenk_7.4-90080-1.meta.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        (package_dir / "gpl.json").write_text(
            json.dumps(
                {
                    "kernel_url": "https://example.test/linux.txz",
                    "kernel_sha256": "kernelsha256",
                    "toolchain_url": "https://example.test/toolchain.txz",
                    "toolchain_sha256": "toolchainsha256",
                    "repo_commit": "abc123",
                }
            ),
            encoding="utf-8",
        )
        return package_dir

    def test_creates_draft_uploads_assets_with_gpl_notes_then_publishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets_dir = Path(temporary)
            package_dir = self.create_artifacts(assets_dir)
            release_url = "https://uploads.github.test/assets{?name,label}"
            calls = []
            responses = [
                HTTPError("https://api.github.test/release", 404, "not found", {}, io.BytesIO(b"{}")),
                _Response(
                    {
                        "id": 42,
                        "draft": True,
                        "upload_url": release_url,
                        "html_url": "https://github.com/martinskuta/synology-packages/releases/tag/hidraw-enable/v7.4-90080-1",
                        "assets": [],
                    }
                ),
                _Response(),
                _Response(),
                _Response(),
                _Response({"id": 42, "draft": False}),
            ]

            def opener(request, timeout):
                calls.append(request)
                response = responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return response

            published = publish_releases(
                assets_dir,
                "martinskuta/synology-packages",
                "token",
                "abc123",
                opener=opener,
            )

            self.assertEqual(["hidraw-enable/v7.4-90080-1"], published)
            self.assertEqual(6, len(calls))
            create_payload = json.loads(calls[1].data)
            self.assertTrue(create_payload["draft"])
            self.assertIn("https://example.test/linux.txz", create_payload["body"])
            self.assertIn("`kernelsha256`", create_payload["body"])
            self.assertIn("https://example.test/toolchain.txz", create_payload["body"])
            self.assertIn("`toolchainsha256`", create_payload["body"])
            self.assertIn("abc123", create_payload["body"])
            uploaded = {
                parse_qs(urlparse(call.full_url).query)["name"][0]
                for call in calls[2:5]
                if isinstance(call, Request)
            }
            self.assertEqual(
                {
                    "hidraw-enable_geminilakenk_7.4-90080-1.spk",
                    "hidraw-enable_geminilakenk_7.4-90080-1.sha256",
                    "hidraw-enable_geminilakenk_7.4-90080-1.meta.json",
                },
                uploaded,
            )
            self.assertFalse(responses)

    def test_existing_published_release_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.create_artifacts(temporary)
            calls = []

            def opener(request, timeout):
                calls.append(request)
                return _Response({"draft": False, "html_url": "https://github.test/release"})

            self.assertEqual(
                [],
                publish_releases(
                    temporary,
                    "martinskuta/synology-packages",
                    "token",
                    "abc123",
                    opener=opener,
                ),
            )
            self.assertEqual(1, len(calls))


if __name__ == "__main__":
    unittest.main()