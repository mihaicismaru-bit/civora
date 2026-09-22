#!/usr/bin/env python3
"""Regression guard for official source transport aliases and verified TLS fallback."""
from __future__ import annotations

import importlib.util
import ssl
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "source_registry_probe.py"
spec = importlib.util.spec_from_file_location("source_registry_probe", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

PRIMARY = "https://new.example.invalid/current"
ALIAS = "https://legacy.example.invalid/current"
ALIAS_2 = "https://www.legacy.example.invalid/current"
SOURCE = {
    "id": "SRC-TEST",
    "url": PRIMARY,
    "canonical_aliases": [PRIMARY, ALIAS, ALIAS, ALIAS_2],
}

assert module.source_urls(SOURCE) == [PRIMARY, ALIAS, ALIAS_2]


def healthy(url: str):
    return {
        "ok": True,
        "http_status": 200,
        "final_url": url,
        "content_type": "text/html",
        "bytes": 50_000,
        "raw_sha256": "raw",
        "semantic_sha256": "semantic",
        "semantic_bytes": 2_000,
        "semantic_chars": 2_000,
        "content_quality_ok": True,
        "quality_issue": None,
        "attempts": 1,
    }


# The secondary transport is allowed only for an explicit certificate-verification
# failure and must keep TLS verification on. Ordinary network errors must not be
# hidden by switching clients.
original_fetch_once = module.fetch_once
original_verified_curl = module.fetch_with_verified_curl
original_sleep = module.time.sleep
try:
    curl_calls = []

    def tls_chain_failure(url: str):
        raise ssl.SSLCertVerificationError(
            1,
            "certificate verify failed: unable to get local issuer certificate",
        )

    def verified_curl_success(url: str):
        curl_calls.append(url)
        out = healthy(url)
        out["transport"] = "system-curl-verified"
        return out

    module.fetch_once = tls_chain_failure
    module.fetch_with_verified_curl = verified_curl_success
    module.time.sleep = lambda _seconds: None
    out = module.fetch(PRIMARY, attempts=1)
    assert curl_calls == [PRIMARY]
    assert out["verified_tls_fallback"] is True
    assert out["transport"] == "system-curl-verified"
    assert "certificate verify failed" in out["primary_transport_error"].lower()

    curl_calls = []

    def ordinary_network_failure(url: str):
        raise OSError("temporary DNS failure")

    module.fetch_once = ordinary_network_failure
    try:
        module.fetch(PRIMARY, attempts=1)
        raise AssertionError("ordinary network errors must not switch to TLS fallback")
    except OSError as exc:
        assert "DNS" in str(exc)
    assert curl_calls == []

    module.fetch_once = tls_chain_failure

    def verified_curl_failure(url: str):
        raise RuntimeError("verified curl certificate validation failed")

    module.fetch_with_verified_curl = verified_curl_failure
    try:
        module.fetch(PRIMARY, attempts=1)
        raise AssertionError("both verified transports failing must stay fail-closed")
    except RuntimeError as exc:
        message = str(exc).lower()
        assert "primary verified tls transport failed" in message
        assert "secure curl fallback also failed" in message
finally:
    module.fetch_once = original_fetch_once
    module.fetch_with_verified_curl = original_verified_curl
    module.time.sleep = original_sleep


original_fetch = module.fetch
try:
    calls = []

    def primary_ok(url: str):
        calls.append(url)
        return healthy(url)

    module.fetch = primary_ok
    out = module.fetch_source(SOURCE)
    assert calls == [PRIMARY]
    assert out["selected_url"] == PRIMARY
    assert out["used_canonical_alias"] is False

    calls = []

    def alias_after_primary_failure(url: str):
        calls.append(url)
        if url == PRIMARY:
            raise OSError("primary TLS unavailable")
        return healthy(url)

    module.fetch = alias_after_primary_failure
    out = module.fetch_source(SOURCE)
    assert calls == [PRIMARY, ALIAS]
    assert out["selected_url"] == ALIAS
    assert out["used_canonical_alias"] is True
    assert out["fallback_failures"][0]["url"] == PRIMARY

    calls = []

    def alias_after_low_information(url: str):
        calls.append(url)
        if url == PRIMARY:
            low = healthy(url)
            low.update({
                "bytes": 12_000,
                "semantic_sha256": "shell",
                "semantic_bytes": 100,
                "semantic_chars": 100,
                "content_quality_ok": False,
                "quality_issue": "LOW_INFORMATION_HTML_SHELL",
            })
            return low
        return healthy(url)

    module.fetch = alias_after_low_information
    out = module.fetch_source(SOURCE)
    assert calls == [PRIMARY, ALIAS]
    assert out["selected_url"] == ALIAS
    assert out["content_quality_ok"] is True

    calls = []

    def all_low_or_failed(url: str):
        calls.append(url)
        if url == PRIMARY:
            low = healthy(url)
            low.update({
                "bytes": 12_000,
                "semantic_sha256": "shell",
                "semantic_bytes": 100,
                "semantic_chars": 100,
                "content_quality_ok": False,
                "quality_issue": "LOW_INFORMATION_HTML_SHELL",
            })
            return low
        raise OSError("alias unavailable")

    module.fetch = all_low_or_failed
    out = module.fetch_source(SOURCE)
    assert calls == [PRIMARY, ALIAS, ALIAS_2]
    assert out["selected_url"] == PRIMARY
    assert out["content_quality_ok"] is False
    assert out["quality_issue"] == "LOW_INFORMATION_HTML_SHELL"

    calls = []

    def all_failed(url: str):
        calls.append(url)
        raise OSError("offline")

    module.fetch = all_failed
    try:
        module.fetch_source(SOURCE)
        raise AssertionError("all-failed source should fail closed")
    except RuntimeError as exc:
        message = str(exc)
        assert PRIMARY in message
        assert ALIAS in message
        assert ALIAS_2 in message
finally:
    module.fetch = original_fetch

print("PASS source registry official alias + verified TLS fallback regression")
