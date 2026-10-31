import unittest
from pathlib import Path

from common.synopkg.archive import (
    ArchiveResolutionError,
    GPL_LISTING,
    GPL_ROOT_LISTING,
    TOOLCHAIN_LISTING,
    TOOLCHAIN_ROOT_LISTING,
    discover_new_targets,
    listing_links,
    resolve_urls,
)
from common.synopkg.config import load_package


FIXTURES = Path(__file__).parent / "fixtures"


class ArchiveResolutionTests(unittest.TestCase):
    def setUp(self):
        self.toolchain_listing = TOOLCHAIN_LISTING.format(source_build="7.4-90080")
        self.kernel_listing = GPL_LISTING.format(source_build="7.4-90080")
        self.pages = {
            self.toolchain_listing: (FIXTURES / "toolchain.html").read_text(encoding="utf-8"),
            self.kernel_listing: (FIXTURES / "kernel.html").read_text(encoding="utf-8"),
        }

    def test_resolves_matching_toolchain_and_kernel_with_inconsistent_folder_names(self):
        result = resolve_urls(
            {
                "platform": "geminilakenk",
                "arch": "x86_64",
                "source_build": "7.4-90080",
                "kernel_release": "5.10.55+",
            },
            fetcher=self.pages.__getitem__,
        )

        self.assertTrue(result["toolchain_url"].endswith("geminilakenk-gcc1220_glibc236_x86_64-GPL.txz"))
        self.assertTrue(result["kernel_url"].endswith("/geminilakenk/linux-5.10.x.txz"))
        self.assertNotIn("epyc7002", result["toolchain_url"])

    def test_honors_url_overrides_without_fetching_listings(self):
        result = resolve_urls(
            {
                "platform": "geminilakenk",
                "arch": "x86_64",
                "source_build": "7.4-90080",
                "kernel_release": "5.10.55+",
                "toolchain_url": "https://example.test/toolchain.txz",
                "kernel_url": "https://example.test/kernel.txz",
            },
            fetcher=lambda _: self.fail("override should avoid archive requests"),
        )
        self.assertEqual(
            {
                "toolchain_url": "https://example.test/toolchain.txz",
                "kernel_url": "https://example.test/kernel.txz",
            },
            result,
        )

    def test_rejects_missing_matching_platform(self):
        with self.assertRaisesRegex(ArchiveResolutionError, "expected exactly one"):
            resolve_urls(
                {
                    "platform": "unknownplatform",
                    "arch": "x86_64",
                    "source_build": "7.4-90080",
                    "kernel_release": "5.10.55+",
                },
                fetcher=self.pages.__getitem__,
            )

    def test_listing_parser_resolves_relative_links(self):
        links = listing_links('<a href="file.txz">file.txz</a>', "https://example.test/base/")
        self.assertEqual("https://example.test/base/file.txz", links[0][0])

    def test_discovers_new_build_and_prefills_kernel_and_vermagic(self):
        package = load_package(FIXTURES / "package.yml")
        pages = {
            TOOLCHAIN_ROOT_LISTING: (FIXTURES / "toolchain-root.html").read_text(encoding="utf-8"),
            GPL_ROOT_LISTING: (FIXTURES / "gpl-root.html").read_text(encoding="utf-8"),
            TOOLCHAIN_LISTING.format(source_build="7.4-95000"): (
                FIXTURES / "toolchain-7.4-95000.html"
            ).read_text(encoding="utf-8"),
            GPL_LISTING.format(source_build="7.4-95000"): (
                FIXTURES / "kernel-7.4-95000.html"
            ).read_text(encoding="utf-8"),
        }

        targets = discover_new_targets(package, fetcher=pages.__getitem__)

        self.assertEqual(
            [
                {
                    "platform": "geminilakenk",
                    "arch": "x86_64",
                    "source_build": "7.4-95000",
                    "kernel_release": "5.10.70+",
                    "vermagic": "5.10.70+ SMP mod_unload",
                    "dsm_builds": [95000],
                }
            ],
            targets,
        )


if __name__ == "__main__":
    unittest.main()