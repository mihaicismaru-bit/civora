#!/usr/bin/env python3
"""Hermetic RCH public EPSS source-link and immutable gateway replay gate."""
import importlib.util
import json
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))
import rch_2027_raw_acquire as raw
import rch_2027_paired_handoff as pair
import rch_2027_epss_gateway as gate

RUN = "rch-epss-fixture"
SOURCE = (b"<!DOCTYPE html><html><body>First Joint Transnational Call: "
          b"Foundations for climate-resilient cultural heritage. "
          b"Primul apel de proiecte Resilient Cultural Heritage."
          b'<a href="https://epss.proposals.ee/rch/">Submission platform</a>'
          b"</body></html>")
PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\nstartxref\n9\n%%EOF\n"
GATEWAY = (b"<!doctype html><html><body>RCH Partnership Calls for Proposals "
           b"Resilient Cultural Heritage RCH Call 1 "
           b"Foundations for climate-resilient cultural heritage Sign in</body></html>")


def reject(fn, *args):
    try:
        fn(*args)
    except (ValueError, FileNotFoundError, TypeError):
        return
    raise AssertionError(f"fail-closed rejection missing: {fn.__name__}")


def test_transport_and_link():
    assert gate.official_submission_link(SOURCE) == gate.GATEWAY_URL
    gate.validate_gateway_response(status=200, mime="text/html",
                                  encoding="identity", declared_length=None, body=GATEWAY)
    for altered in ("http://epss.proposals.ee/rch/", "https://evil.example/rch/",
                    gate.GATEWAY_URL + "?open=true", gate.GATEWAY_URL + "#call2",
                    "https://epss.proposals.ee/other/"):
        reject(gate.validate_gateway_url, altered)
    for html in (
        SOURCE.replace(b"Submission platform", b"Read more"),
        SOURCE.replace(b"https://epss.proposals.ee/rch/", b"https://evil.example/rch/"),
        SOURCE.replace(b'<a href=', b'<a hidden href='),
        SOURCE.replace(b'<a href=', b'<script><a href='),
        SOURCE.replace(b"</body>", b'<a href="https://epss.proposals.ee/rch/">Submission platform</a></body>'),
    ):
        reject(gate.official_submission_link, html)
    for html in (
        b'<!doctype html><html><body>Sign in</body></html>',
        b'<!doctype html><html><script>RCH Call 1 Resilient Cultural Heritage Sign in</script></html>',
    ):
        reject(gate.validate_gateway_response, status=200, mime="text/html",
               encoding="identity", declared_length=None, body=html)


def test_bound_capture_replay():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        old_html, old_pdf, old_gateway = raw.fetch_raw, raw.fetch_document_raw, gate.fetch_gateway
        try:
            raw.fetch_raw = lambda sid: (SOURCE, raw.SOURCE_SPECS[sid]["url"], "text/html")
            raw.fetch_document_raw = lambda sid: (PDF, raw.document_url(sid), "application/pdf")
            gate.fetch_gateway = lambda url: (GATEWAY, url, "text/html")
            raw.capture(root, RUN)
            raw.capture_documents(root, RUN)
            assert pair.seal(root)["status"] == "RAW_ORIGINALS_PAIRED_NOT_PUBLISHED"
            assert gate.capture(root, RUN)["status"] == "EPSS_PUBLIC_LOGIN_RAW_REPLAY_VERIFIED_NOT_PUBLISHED"
        finally:
            raw.fetch_raw, raw.fetch_document_raw, gate.fetch_gateway = old_html, old_pdf, old_gateway
        assert gate.replay(root)["open_call_authorized"] is False
        filename = root / gate.MANIFEST_PATH
        original = filename.read_bytes()
        receipt = json.loads(original)
        assert receipt["paired_handoff_sha256"] == raw.read_evidence_json(
            root / "handoff/rch_2027_paired_handoff.json")["handoff_sha256"]
        assert all(receipt[key] is False for key in gate.FALSE_FLAGS)
        bad = deepcopy(receipt)
        bad["distribution_authorized"] = True
        bad["handoff_sha256"] = raw.sha256(raw.canonical_json(
            {k: v for k, v in bad.items() if k != "handoff_sha256"}))
        filename.write_text(json.dumps(bad))
        reject(gate.replay, root)
        bad = deepcopy(receipt)
        bad["new_authorization"] = True
        bad["handoff_sha256"] = raw.sha256(raw.canonical_json(
            {k: v for k, v in bad.items() if k != "handoff_sha256"}))
        filename.write_text(json.dumps(bad))
        reject(gate.replay, root)
        for field, value in (("paired_handoff_sha256", "f" * 64),
                             ("source_html_raw_sha256", "f" * 64),
                             ("run_id", "other-run"),
                             ("observation_state", "OPEN_CALL"),
                             ("fetched_at_utc", "2099-01-01T00:00:00Z")):
            bad = deepcopy(receipt)
            bad[field] = value
            bad["handoff_sha256"] = raw.sha256(raw.canonical_json(
                {k: v for k, v in bad.items() if k != "handoff_sha256"}))
            filename.write_text(json.dumps(bad))
            reject(gate.replay, root)
        filename.write_bytes(original)
        original_raw = (root / gate.RAW_PATH).read_bytes()
        (root / gate.RAW_PATH).write_bytes(original_raw + b" tamper")
        reject(gate.replay, root)
        (root / gate.RAW_PATH).write_bytes(original_raw)
        assert gate.replay(root)["publish_authorized"] is False
        reject(gate.capture, root, "wrong-run")


if __name__ == "__main__":
    test_transport_and_link()
    test_bound_capture_replay()
    print("PASS RCH official Call 1 -> EPSS public login linked raw SHA; fail-closed replay/no OPEN")
