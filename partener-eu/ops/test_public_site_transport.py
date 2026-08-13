#!/usr/bin/env python3
"""Regression tests for the public deployment transport closure gate."""
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


if __name__ == "__main__":
    unittest.main()
