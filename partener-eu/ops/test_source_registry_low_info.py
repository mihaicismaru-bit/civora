#!/usr/bin/env python3
"""Regression guard for low-information HTML in the verified source registry."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "source_registry_probe.py"
spec = importlib.util.spec_from_file_location("source_registry_probe", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def check(raw_size: int, content_type: str, semantic_text: str, expected_ok: bool, expected_issue):
    ok, issue, chars = module.classify_content_quality(raw_size, content_type, semantic_text.encode("utf-8"))
    assert ok is expected_ok, (raw_size, content_type, chars, ok, expected_ok)
    assert issue == expected_issue, (issue, expected_issue)


check(12_000, "text/html", "x" * 101, False, "LOW_INFORMATION_HTML_SHELL")
check(120_000, "text/html; charset=UTF-8", "conținut oficial " * 700, True, None)
check(2_000, "text/html", "pagină scurtă legitimă", True, None)
check(12_000, "application/pdf", "x" * 50, True, None)

old = {
    "semantic_sha256": "shell-hash",
    "semantic_bytes": 101,
    "bytes": 12_000,
}
original_task_dir = module.TASK_DIR
try:
    import tempfile
    import json
    with tempfile.TemporaryDirectory() as td:
        module.TASK_DIR = Path(td)
        (module.TASK_DIR / "SRC-TEST.json").write_text(json.dumps({
            "current_semantic_sha256": "shell-hash",
            "previous_semantic_sha256": "good-hash",
        }), encoding="utf-8")
        assert module.task_baseline_hash("SRC-TEST", old) == "good-hash"
finally:
    module.TASK_DIR = original_task_dir

# Official source health may not hash a successful-looking truncated HTTP body.
# Exercise the real fetch_once transport with synthetic in-memory responses.
class _Response:
    status = 200

    def __init__(self, payload: bytes, *, length: str | None = None, encoding: str | None = None):
        self.payload = payload
        self.headers = {"content-type": "text/html; charset=utf-8"}
        if length is not None:
            self.headers["content-length"] = length
        if encoding is not None:
            self.headers["content-encoding"] = encoding

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]

    def geturl(self):
        return "https://official.example.invalid/evidence"


original_urlopen = module.urllib.request.urlopen
try:
    good = b"<html><body>" + b"Official programme evidence " * 400 + b"</body></html>"
    def probe(response):
        module.urllib.request.urlopen = lambda *_a, **_kw: response
        return module.fetch_once("https://official.example.invalid/evidence")

    healthy = probe(_Response(good, length=str(len(good)), encoding="identity"))
    assert healthy["ok"] is True
    assert healthy["bytes"] == len(good)
    assert healthy["content_quality_ok"] is True

    incomplete_cases = (
        ("oversized", _Response(b"x" * (module.MAX_SOURCE_BYTES + 10)), "oversized"),
        ("short", _Response(good, length=str(len(good) + 1)), "Content-Length"),
        ("long", _Response(good, length=str(len(good) - 1)), "Content-Length"),
        ("bad length", _Response(good, length="invalid"), "Content-Length"),
        ("gzip", _Response(good, encoding="gzip"), "Content-Encoding"),
    )
    for label, response, expected in incomplete_cases:
        try:
            probe(response)
        except ValueError as exc:
            assert expected in str(exc), (label, exc)
        else:
            raise AssertionError(f"incomplete/unverifiable source marked healthy: {label}")
finally:
    module.urllib.request.urlopen = original_urlopen

print("PASS source registry low-information regression")
