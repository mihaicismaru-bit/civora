#!/usr/bin/env python3
"""Regression tests for the public deployment transport and vNext content gate."""
from __future__ import annotations

import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("check_public_site.py")
SPEC = importlib.util.spec_from_file_location("check_public_site", MODULE_PATH)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def endpoint(
    endpoint_id: str,
    requested_scheme: str,
    final_scheme: str,
    redirects: list[tuple[str, str]] | None = None,
    content_verified: bool = True,
) -> dict[str, object]:
    return {
        "id": endpoint_id,
        "url": f"{requested_scheme}://example.test/",
        "requested_url": f"{requested_scheme}://example.test/?probe=1",
        "final_url": f"{final_scheme}://example.test/",
        "final_scheme": final_scheme,
        "content_verified": content_verified,
        "error": None,
        "redirect_chain": [
            {
                "http_status": 301,
                "from_url": f"{source}://example.test/",
                "to_url": f"{target}://example.test/",
            }
            for source, target in (redirects or [])
        ],
    }


class TransportGateTests(unittest.TestCase):
    def test_pass_requires_complete_secure_transport(self) -> None:
        endpoints = {
            "custom_https": endpoint("custom_https", "https", "https"),
            "custom_http": endpoint("custom_http", "http", "https", [("http", "https")]),
            "pages_origin": endpoint("pages_origin", "https", "https", [("https", "https")]),
        }
        result = CHECK.assess_transport(endpoints)
        self.assertTrue(result["custom_https_verified"])
        self.assertTrue(result["http_redirects_to_https"])
        self.assertTrue(result["pages_https_preserved"])
        self.assertTrue(result["secure_transport_verified"])

    def test_current_http_exposure_and_pages_downgrade_fail_gate(self) -> None:
        endpoints = {
            "custom_https": endpoint("custom_https", "https", "https"),
            "custom_http": endpoint("custom_http", "http", "http"),
            "pages_origin": endpoint("pages_origin", "https", "http", [("https", "http")]),
        }
        result = CHECK.assess_transport(endpoints)
        self.assertTrue(result["custom_https_verified"])
        self.assertFalse(result["http_redirects_to_https"])
        self.assertFalse(result["pages_https_preserved"])
        self.assertFalse(result["secure_transport_verified"])
        self.assertTrue(CHECK.has_https_downgrade(endpoints["pages_origin"]))

    def test_missing_content_cannot_satisfy_transport_gate(self) -> None:
        endpoints = {
            "custom_https": endpoint("custom_https", "https", "https", content_verified=False),
            "custom_http": endpoint("custom_http", "http", "https", [("http", "https")], content_verified=False),
            "pages_origin": endpoint("pages_origin", "https", "https", content_verified=False),
        }
        self.assertFalse(CHECK.assess_transport(endpoints)["secure_transport_verified"])

    def test_public_probe_is_bound_to_funding_concierge_vnext(self) -> None:
        markers = CHECK.REQUIRED_MARKERS
        self.assertEqual(markers["hero"], "Ce vrei să finanțezi?")
        self.assertIn("ce știm sigur", markers["product_definition"])
        self.assertEqual(markers["heavy_loader_ref"], 'src="public-heavy-loader-v1.js')
        self.assertEqual(markers["home_data_ref"], 'src="home-public-data.js')
        self.assertEqual(markers["concierge_ui_ref"], 'src="home-concierge-vnext.js')
        self.assertEqual(markers["concierge_css_ref"], 'href="home-concierge-vnext.css')
        self.assertNotIn("decision_data_ref", markers)
        self.assertNotIn("decision_ui_ref", markers)
        self.assertNotIn("novice_ui_ref", markers)
        self.assertNotIn("goto_ui_ref", markers)
        self.assertEqual(CHECK.UA, "PARTENER.EU-CIVORA-P10-Deployment-Probe/1.9")

    def test_optimized_boot_rejects_eager_heavy_refs(self) -> None:
        optimized = '''<script src="data.js"></script><script src="app.js"></script><script defer src="public-heavy-loader-v1.js"></script><script defer src="home-public-data.js"></script><script defer src="home-concierge-vnext.js"></script>'''
        self.assertEqual(CHECK.eager_heavy_refs(optimized), [])
        stale = optimized + '<script defer src="decision-products.js"></script>'
        self.assertIn('src="decision-products.js', CHECK.eager_heavy_refs(stale))

    def test_vnext_asset_extractors_resolve_versioned_refs(self) -> None:
        html = '''<link rel="stylesheet" href="home-concierge-vnext.css?v=1"><script defer src="public-heavy-loader-v1.js?v=1"></script><script defer src="home-public-data.js?v=1"></script><script defer src="home-concierge-vnext.js?v=1"></script>'''
        self.assertEqual(
            CHECK.extract_asset(html, "public-heavy-loader-v1.js", "https://partener.eu/"),
            "https://partener.eu/public-heavy-loader-v1.js?v=1",
        )
        self.assertEqual(
            CHECK.extract_asset(html, "home-public-data.js", "https://partener.eu/"),
            "https://partener.eu/home-public-data.js?v=1",
        )
        self.assertEqual(
            CHECK.extract_asset(html, "home-concierge-vnext.js", "https://partener.eu/"),
            "https://partener.eu/home-concierge-vnext.js?v=1",
        )
        self.assertEqual(
            CHECK.extract_stylesheet(html, "home-concierge-vnext.css", "https://partener.eu/"),
            "https://partener.eu/home-concierge-vnext.css?v=1",
        )


if __name__ == "__main__":
    unittest.main()
