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
# Even tiny script-only/empty HTTP-200 HTML has no semantic evidence and
# must preserve the source's previous verified semantic hash/LKG.
check(150, "text/html", "", False, "EMPTY_SEMANTIC_HTML")
check(2_000, "application/xhtml+xml", "", False, "EMPTY_SEMANTIC_HTML")
check(6_000, "text/html", "", False, "EMPTY_SEMANTIC_HTML")
# HTTP 200 may serve a tiny challenge/error HTML body; never hash it as healthy.
check(240, "text/html", "Just a moment... Enable JavaScript and cookies to continue", False, "HTML_CHALLENGE_OR_ERROR_SHELL")
check(1_050, "application/xhtml+xml", "Access denied. Cloudflare Ray ID: abc", False, "HTML_CHALLENGE_OR_ERROR_SHELL")
check(500, "text/html", "Service unavailable", False, "HTML_CHALLENGE_OR_ERROR_SHELL")
# Several small HTTP-200 JS/Cloudflare gates previously passed as healthy
# because the body was shorter than the generic 4096-byte low-info cutoff.
for shell in (
    "Please enable JavaScript and cookies to continue",
    "Enable JavaScript and cookies to continue",
    "Checking if the site connection is secure",
    "Attention required! | Cloudflare",
):
    check(180, "text/html; charset=UTF-8", shell, False, "HTML_CHALLENGE_OR_ERROR_SHELL")
check(250, "text/html", "Actual official decision content with dates and identity", True, None)
# A substantive official article mentioning a challenge phrase must not be blocked.
check(8_000, "text/html", "Access denied: security for EU funding. " * 50, True, None)
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
    challenge_html = b"<html><head><title>Just a moment...</title></head><body>Please enable JavaScript and cookies to continue</body></html>"
    challenge = probe(_Response(challenge_html, length=str(len(challenge_html))))
    assert challenge["ok"] is True
    assert challenge["content_quality_ok"] is False
    assert challenge["quality_issue"] == "HTML_CHALLENGE_OR_ERROR_SHELL"

    empty_semantic_html = b"<html><head><script>window.location='/challenge'</script></head><body><!-- empty --></body></html>"
    empty_document = probe(_Response(empty_semantic_html, length=str(len(empty_semantic_html))))
    assert empty_document["ok"] is True and empty_document["semantic_chars"] == 0
    assert empty_document["content_quality_ok"] is False
    assert empty_document["quality_issue"] == "EMPTY_SEMANTIC_HTML"


    # The legacy digest includes <title> and visually hidden text. Nonempty
    # semantic text is not proof that the page contains rendered source facts.
    metadata_shells = (
        b"<html><head><title>Official grants 2026</title></head>"
        b"<body><script>window.location='/verify'</script></body></html>",
        b"<html><head><title>Official grants 2026</title></head>"
        b"<body><div hidden>2026 grants</div></body></html>",
        b"<html><body><section style='display:none'>2026 grants</section></body></html>",
        b"<html><body><template>Fake notice 2026</template></body></html>",
        b"<html><body><div class='visually-hidden'>2026 grants</div></body></html>",
        b"<html><body><section aria-hidden='true'>2026 grants</section></body></html>",
    )
    for raw in metadata_shells:
        assert module.visible_html_characters(raw) == 0
        shell = probe(_Response(raw, length=str(len(raw))))
        assert shell["ok"] is True
        assert shell["content_quality_ok"] is False
        assert shell["quality_issue"] == "EMPTY_VISIBLE_HTML"

    # A large title or hidden payload plus one rendered token is still a
    # metadata shell, not a substantively observed official programme page.
    # The legacy semantic digest can exceed 256 characters in these cases.
    near_empty_visible = (
        b"<html><head><title>" + b"Programme details " * 30
        + b"</title></head><body><main><p>OK</p></main></body></html>",
        b"<html><body><section hidden>" + b"Official funds " * 40
        + b"</section><main><span>X</span></main></body></html>",
    )
    for raw in near_empty_visible:
        assert 0 < module.visible_html_characters(raw) < module.MIN_VISIBLE_HTML_CHARS
        assert len(module.semantic_bytes(raw, "text/html")) >= module.MIN_SEMANTIC_CHARS
        tiny = probe(_Response(raw, length=str(len(raw))))
        assert tiny["ok"] is True
        assert tiny["content_quality_ok"] is False
        assert tiny["quality_issue"] == "INSUFFICIENT_VISIBLE_HTML"

    # Preserve short legitimate HTML, including article text below 4 KiB.
    visible_short = (
        b"<html><head><title>Official grants 2026</title></head>"
        b"<body><main><p>Official grant instructions.</p></main></body></html>"
    )
    assert module.visible_html_characters(visible_short) > 0
    real_short = probe(_Response(visible_short, length=str(len(visible_short))))
    assert real_short["content_quality_ok"] is True
    assert real_short["quality_issue"] is None

    javascript_shell = b"<html><body>Please enable JavaScript and cookies to continue</body></html>"
    js_gate = probe(_Response(javascript_shell, length=str(len(javascript_shell))))
    assert js_gate["ok"] is True and js_gate["content_quality_ok"] is False
    assert js_gate["quality_issue"] == "HTML_CHALLENGE_OR_ERROR_SHELL"

    xhtml = probe(_Response(good, content_type="APPLICATION/XHTML+XML; charset=UTF-8"))
    assert xhtml["ok"] is True and xhtml["content_quality_ok"] is True
    pdf_data = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    pdf = probe(_Response(pdf_data, content_type="application/pdf",
                          length=str(len(pdf_data))))
    assert pdf["ok"] is True and pdf["bytes"] == len(pdf_data)
    # %PDF- alone is insufficient: partial PDF bodies with an apparently
    # correct HTTP status, Content-Type and Content-Length cannot refresh LKG.
    for incomplete_pdf in (
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n",
        b"%PDF-1.7\n%%EOF\n" + b"x" * 9_000,
    ):
        try:
            probe(_Response(incomplete_pdf, content_type="application/pdf",
                            length=str(len(incomplete_pdf))))
        except ValueError as exc:
            assert "missing EOF trailer" in str(exc), exc
        else:
            raise AssertionError("incomplete PDF acquired as healthy official evidence")
    pdf_with_whitespace = pdf_data + b"\n  "
    assert probe(_Response(pdf_with_whitespace, content_type="application/pdf"))["content_quality_ok"] is True

    # A transport may return HTTP 200 with an empty body or a misleading
    # application/pdf header over HTML anti-bot content. Neither is evidence
    # of a successful official source observation, even without length drift.
    for mime in ("text/html", "application/xhtml+xml", "application/pdf"):
        for declared_length in (None, "0"):
            try:
                probe(_Response(b"", content_type=mime, length=declared_length))
            except ValueError as exc:
                assert "empty official source response" in str(exc), (mime, exc)
            else:
                raise AssertionError(f"empty HTTP-200 body admitted: {mime}")
    for bogus_pdf in (
        b"<html><title>Just a moment</title><body>Checking browser</body></html>",
        b"<!doctype html><html><body>Service unavailable</body></html>",
        b"%PDF",
        b"random bytes",
    ):
        try:
            probe(_Response(bogus_pdf, content_type="application/pdf",
                            length=str(len(bogus_pdf))))
        except ValueError as exc:
            assert "PDF signature" in str(exc), exc
        else:
            raise AssertionError(f"spoofed or malformed PDF admitted: {bogus_pdf[:30]!r}")

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


# End-to-end LKG regression: an unseen HTML document is an observation failure,
# not a new semantic change or an invitation to update material call facts.
with tempfile.TemporaryDirectory() as td:
    temp_root = Path(td)
    registry_file = temp_root / "registry.json"
    state_file = temp_root / "health.json"
    tasks = temp_root / "tasks"
    fake_source = {
        "id": "SRC-TEST-METADATA-ONLY", "tier": "T1",
        "class": "OFFICIAL", "url": registered,
        "source_families": ["ROMANIA", "OFFICIAL"],
        "material_fact_use": True,
    }
    registry_file.write_text(json.dumps({"sources": [fake_source]}), encoding="utf-8")
    state_file.write_text(json.dumps({"sources": [{
        "id": fake_source["id"], "semantic_sha256": "a" * 64,
        "semantic_chars": 500, "bytes": 8_000, "consecutive_failures": 0,
    }]}), encoding="utf-8")
    originals = (module.REGISTRY, module.STATE, module.TASK_DIR,
                 module.REVIEWED_BASELINES, module.fetch_source)
    try:
        module.REGISTRY, module.STATE = registry_file, state_file
        module.TASK_DIR = tasks
        module.REVIEWED_BASELINES = temp_root / "reviewed-baselines.json"
        module.fetch_source = lambda _src: {
            "ok": True, "http_status": 200, "final_url": registered,
            "content_type": "text/html", "bytes": 140,
            "semantic_bytes": 55, "semantic_chars": 55,
            "raw_sha256": "b" * 64, "semantic_sha256": "b" * 64,
            "content_quality_ok": False, "quality_issue": "EMPTY_VISIBLE_HTML",
            "selected_url": registered,
        }
        module.main()
        row = json.loads(state_file.read_text(encoding="utf-8"))["sources"][0]
        assert row["health"] == "DEGRADED"
        assert row["semantic_sha256"] == "a" * 64
        assert row["observed_semantic_sha256"] == "b" * 64
        assert row["last_known_semantic_sha256"] == "a" * 64
        assert row["semantic_hash_changed"] is False
        assert row["resolution_task_required"] is False
        assert row["publish_material_fact_update"] is False
        assert not tasks.exists(), "unverified HTML wrote a resolution task"
    finally:
        (module.REGISTRY, module.STATE, module.TASK_DIR,
         module.REVIEWED_BASELINES, module.fetch_source) = originals

print("PASS source registry low-information, partial-body and exact-endpoint-lock regression")
