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
# Only the actual media type may select HTML normalization or shell heuristics.
# Misleading parameter strings and suffixes must not select HTML processing.
check(12_000, "text/plain; filename=notice.html", "x" * 50, True, None)
check(12_000, "application/json; note=text/html", "x" * 50, True, None)
check(12_000, "text/html-fake", "x" * 50, True, None)
check(12_000, "application/xhtml+xml", "x" * 50, False, "LOW_INFORMATION_HTML_SHELL")
fixture_html = b"<html><script>hidden evidence</script><p>Visible official content</p></html>"
assert b"hidden evidence" not in module.semantic_bytes(fixture_html, "TEXT/HTML; charset=utf-8")
assert module.semantic_bytes(fixture_html, "text/plain; filename=notice.html") == fixture_html
assert module.semantic_bytes(fixture_html, "application/json; note=text/html") == fixture_html
assert module.official_media_type("text/html; filename=other.json") == "text/html"
assert module.is_html_content_type("application/xhtml+xml; charset=utf-8") is True
assert module.is_html_content_type("text/html-fake") is False

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

    def __init__(self, payload: bytes, *, length: str | None = None,
                 encoding: str | None = None, status: int = 200,
                 final_url: str = "https://official.example.invalid/evidence",
                 content_type: str = "text/html; charset=utf-8"):
        self.payload = payload
        self.read_count = 0
        self.status = status
        self.final_url = final_url
        self.headers = {"content-type": content_type}
        if length is not None:
            self.headers["content-length"] = length
        if encoding is not None:
            self.headers["content-encoding"] = encoding

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        self.read_count += 1
        return self.payload[:limit]

    def geturl(self):
        return self.final_url


original_build_opener = module.urllib.request.build_opener
try:
    good = b"<html><body>" + b"Official programme evidence " * 400 + b"</body></html>"

    class _StubOpener:
        def __init__(self, response):
            self.response = response

        def open(self, *_args, **_kwargs):
            return self.response

    def probe(response):
        module.urllib.request.build_opener = lambda *_handlers: _StubOpener(response)
        return module.fetch_once("https://official.example.invalid/evidence")

    healthy = probe(_Response(good, length=str(len(good)), encoding="identity"))
    assert healthy["ok"] is True
    assert healthy["bytes"] == len(good)
    assert healthy["content_quality_ok"] is True

    xhtml = probe(_Response(good, content_type="APPLICATION/XHTML+XML; charset=UTF-8"))
    assert xhtml["ok"] is True and xhtml["content_quality_ok"] is True
    pdf_data = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    pdf = probe(_Response(pdf_data, content_type="application/pdf",
                          length=str(len(pdf_data))))
    assert pdf["ok"] is True and pdf["bytes"] == len(pdf_data)

    # Fail before reading any bytes: a false Content-Type cannot become
    # semantic-hash PASS even if the payload looks like a genuine HTML page.
    for mime in ("text/plain; filename=notice.html", "application/json; note=text/html",
                 "text/html-fake", "application/xhtml+xml-fake",
                 "application/pdf-fake", "image/svg+xml", "application/json",
                 "", "application/octet-stream"):
        response = _Response(good, content_type=mime)
        try:
            probe(response)
        except ValueError as exc:
            assert "Content-Type" in str(exc), (mime, exc)
        else:
            raise AssertionError(f"unsupported MIME admitted as official health: {mime}")
        assert response.read_count == 0, (mime, response.read_count)

    incomplete_cases = (
        ("oversized", _Response(b"x" * (module.MAX_SOURCE_BYTES + 10)), "oversized"),
        ("short", _Response(good, length=str(len(good) + 1)), "Content-Length"),
        ("long", _Response(good, length=str(len(good) - 1)), "Content-Length"),
        ("bad length", _Response(good, length="invalid"), "Content-Length"),
        ("gzip", _Response(good, encoding="gzip"), "Content-Encoding"),
        ("partial 206", _Response(good, status=206), "HTTP status"),
        ("redirect 302", _Response(good, status=302), "HTTP status"),
        ("off-domain final", _Response(good, final_url="https://attacker.invalid/evidence"), "origin"),
        ("same-origin wrong endpoint", _Response(good, final_url="https://official.example.invalid/another-programme"), "endpoint"),
        ("same-origin query swap", _Response(good, final_url="https://official.example.invalid/evidence?state=OPEN"), "endpoint"),
        ("same-origin matrix parameter", _Response(good, final_url="https://official.example.invalid/evidence;session=123"), "untrusted"),
        ("fragment injected", _Response(good, final_url="https://official.example.invalid/evidence#OPEN"), "untrusted"),
        ("HTTP downgrade final", _Response(good, final_url="http://official.example.invalid/evidence"), "untrusted"),
        ("off-port final", _Response(good, final_url="https://official.example.invalid:8443/evidence"), "untrusted"),
    )
    for label, response, expected in incomplete_cases:
        try:
            probe(response)
        except ValueError as exc:
            assert expected in str(exc), (label, exc)
        else:
            raise AssertionError(f"incomplete/unverifiable source marked healthy: {label}")
finally:
    module.urllib.request.build_opener = original_build_opener

# A malicious intermediary must not even be contacted by the HTTP redirect
# handler: checking only the ultimate response URL misses off-authority hops.
import urllib.request

registered = "https://official.example.invalid/evidence"
handler = module._SourceOriginRedirect(registered)
request = urllib.request.Request(registered)
allowed = handler.redirect_request(
    request, None, 302, "Found", {}, "https://www.official.example.invalid/evidence"
)
assert allowed.full_url == "https://www.official.example.invalid/evidence"
slash_allowed = handler.redirect_request(
    request, None, 302, "Found", {}, "https://official.example.invalid/evidence/"
)
assert slash_allowed.full_url == "https://official.example.invalid/evidence/"

for url in (
    "https://attacker.invalid/evidence",
    "https://official.example.invalid.attacker.invalid/evidence",
    "https://official.example.invalid@attacker.invalid/evidence",
    "https://internal.example.invalid/evidence",
    "https://127.0.0.1/evidence",
    "http://official.example.invalid/evidence",
    "https://official.example.invalid:8443/evidence",
    "https://user:pass@official.example.invalid/evidence",
    "https://official.example.invalid/another-programme",
    "https://official.example.invalid/evidence?status=OPEN",
    "https://official.example.invalid/evidence;session=123",
    "https://official.example.invalid/evidence#OPEN",
):
    try:
        handler.redirect_request(request, None, 302, "Found", {}, url)
    except ValueError:
        pass
    else:
        raise AssertionError(f"off-authority redirect accepted before network: {url}")

# The initial registry identity is curated: HTTPS alone cannot prove a
# hostname is official. The transport guard enforces HTTPS/credential/port
# safety there; cross-host comparison is enforced at every redirect.
for url in (
    "http://official.example.invalid/evidence",
    "https://user@official.example.invalid/evidence",
    "https://official.example.invalid:9000/evidence",
    "https://official.example.invalid/evidence;session=123",
    "https://official.example.invalid/evidence#section",
):
    try:
        module._assert_source_origin(url, url)
    except ValueError:
        pass
    else:
        raise AssertionError(f"unsafe initial registry or alias URL: {url}")

print("PASS source registry low-information, partial-body and exact-endpoint-lock regression")
