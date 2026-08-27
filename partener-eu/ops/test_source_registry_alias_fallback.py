#!/usr/bin/env python3
"""Regression guard for official source transport aliases."""
from __future__ import annotations

import importlib.util
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

print("PASS source registry official alias fallback regression")
