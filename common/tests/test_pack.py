import hashlib
import json
import tempfile
import tarfile
import unittest
from pathlib import Path

from common.synopkg.pack import pack_package


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "packages" / "hidraw-enable"


class PackagePackingTests(unittest.TestCase):
    def test_creates_spk_checksums_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload"
            # The build output only contains modules; bin/apply must come from spk/payload.
            (payload / "modules/fallback").mkdir(parents=True)
            (payload / "modules/hid.ko").write_bytes(b"rebuilt hid module")
            (payload / "modules/fallback/usbhid.ko").write_bytes(b"fallback usbhid")
            (payload / "modules/fallback/hid-generic.ko").write_bytes(b"fallback hid generic")
            info_env = root / "info.env"
            info_env.write_text("kernel_release=5.10.55+\n", encoding="utf-8")
            gpl_json = root / "gpl.json"
            gpl_json.write_text('{"repo_commit":"abc123"}\n', encoding="utf-8")

            result = pack_package(
                PACKAGE_DIR,
                payload,
                root / "out",
                "geminilakenk",
                "x86_64",
                "7.4-90080",
                info_env,
                gpl_json,
            )

            self.assertTrue(result["spk"].is_file())
            self.assertEqual(
                "hidraw-enable_geminilakenk_7.4.90080-1.spk", result["spk"].name
            )
            self.assertTrue(result["sha256"].is_file())
            self.assertTrue(result["meta"].is_file())
            with tarfile.open(result["spk"], "r:") as spk:
                names = set(spk.getnames())
                ordered_names = spk.getnames()
                self.assertEqual("INFO", ordered_names[0])
                self.assertEqual("package.tgz", ordered_names[1])
                self.assertTrue(
                    {
                        "INFO",
                        "package.tgz",
                        "scripts/preinst",
                        "scripts/target.env",
                        "conf/privilege",
                        "WIZARD_UIFILES/install_uifile",
                        "PACKAGE_ICON.PNG",
                        "PACKAGE_ICON_256.PNG",
                    }.issubset(names)
                )
                self.assertNotIn("./INFO", names)
                self.assertTrue(spk.getmember("scripts/preinst").mode & 0o111)
                info = spk.extractfile("INFO").read().decode("utf-8")
                self.assertIn('version="7.4.90080-1"', info)
                self.assertIn('arch="geminilakenk"', info)
                self.assertIn('os_min_ver="7.4-90080"', info)
                self.assertIn('os_max_ver="7.4-90080"', info)
                self.assertIn('kernel_release="5.10.55+"', info)
                package_tgz = root / "unpacked-package.tgz"
                package_tgz.write_bytes(spk.extractfile("package.tgz").read())

            with tarfile.open(package_tgz, "r:gz") as payload_tar:
                payload_names = set(payload_tar.getnames())
                self.assertTrue(any(name.endswith("modules/hid.ko") for name in payload_names))
                self.assertTrue(any(name.endswith("target.env") for name in payload_names))
                apply_member = next(
                    member for member in payload_tar.getmembers() if member.name.endswith("bin/apply")
                )
                self.assertTrue(apply_member.mode & 0o111)
                self.assertEqual(
                    (PACKAGE_DIR / "spk/payload/bin/apply").read_bytes(),
                    payload_tar.extractfile(apply_member).read(),
                )

            metadata = json.loads(result["meta"].read_text(encoding="utf-8"))
            self.assertEqual("hidraw-enable", metadata["package"])
            self.assertEqual("geminilakenk", metadata["arch"])
            self.assertEqual("yes", metadata["thirdparty"])
            self.assertEqual(90080, metadata["dsm_builds"][0])
            self.assertEqual(hashlib.sha256(result["spk"].read_bytes()).hexdigest(), metadata["sha256"])
            self.assertEqual(hashlib.md5(result["spk"].read_bytes()).hexdigest(), metadata["md5"])
            self.assertEqual(result["spk"].stat().st_size, metadata["size"])
            self.assertEqual("abc123", json.loads((root / "out/gpl.json").read_text())["repo_commit"])


if __name__ == "__main__":
    unittest.main()