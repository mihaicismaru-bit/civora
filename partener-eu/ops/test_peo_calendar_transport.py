#!/usr/bin/env python3
"""Regression guard for bounded, fail-closed PEO calendar transport."""
from __future__ import annotations

import importlib.util
import io
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "peo_calendar_ingest.py"
spec = importlib.util.spec_from_file_location("peo_calendar_ingest", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def xlsx_like_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/padding.bin", b"X" * 2048)
    return buf.getvalue()


VALID = xlsx_like_bytes()
assert module._is_xlsx_payload(VALID)
assert not module._is_xlsx_payload(b"<html>challenge</html>" * 100)


class Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class Response:
    def __init__(self, body, status=200, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
        self.body = body
        self.status = status
        self.headers = Headers({"Content-Type": content_type})

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# Wrong HTTP-200 body (for example a WAF/challenge page) is retryable.
calls = []
responses = [
    Response(b"<html>waf challenge</html>" * 100, content_type="text/html"),
    Response(VALID),
]


def invalid_then_valid(req, timeout=25):
    calls.append((req, timeout))
    return responses.pop(0)


with patch.object(module.urllib.request, "urlopen", side_effect=invalid_then_valid):
    blob, code, ctype = module.fetch("https://example.invalid/calendar.xlsx", attempts=2, sleep_fn=lambda _: None)
assert blob == VALID and code == 200
assert "spreadsheetml.sheet" in ctype
assert len(calls) == 2

# Transient HTTP 503 retries; a permanent 404 fails immediately.
http_calls = []


def transient_then_valid(req, timeout=25):
    http_calls.append(1)
    if len(http_calls) == 1:
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
    return Response(VALID)


with patch.object(module.urllib.request, "urlopen", side_effect=transient_then_valid):
    blob, _, _ = module.fetch("https://example.invalid/calendar.xlsx", attempts=3, sleep_fn=lambda _: None)
assert blob == VALID
assert len(http_calls) == 2

not_found_calls = []


def not_found(req, timeout=25):
    not_found_calls.append(1)
    raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)


try:
    with patch.object(module.urllib.request, "urlopen", side_effect=not_found):
        module.fetch("https://example.invalid/calendar.xlsx", attempts=4, sleep_fn=lambda _: None)
except urllib.error.HTTPError as exc:
    assert exc.code == 404
else:
    raise AssertionError("404 did not fail fast")
assert len(not_found_calls) == 1

# Repeated HTML/challenge bodies exhaust bounded attempts and never reach openpyxl.
invalid_calls = []


def always_invalid(req, timeout=25):
    invalid_calls.append(1)
    return Response(b"<html>still not a workbook</html>" * 100, content_type="text/html")


try:
    with patch.object(module.urllib.request, "urlopen", side_effect=always_invalid):
        module.fetch("https://example.invalid/calendar.xlsx", attempts=3, sleep_fn=lambda _: None)
except RuntimeError as exc:
    assert "invalid XLSX payload" in str(exc)
else:
    raise AssertionError("invalid payload did not fail closed")
assert len(invalid_calls) == 3

print("PASS PEO calendar transport hardening regression")
