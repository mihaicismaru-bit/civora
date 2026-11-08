#!/usr/bin/env python3
"""Offline adversarial checks for RCH HTML/PDF same-run immutable pairing."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

MODULE = Path(__file__).parents[1] / "ingest" / "rch_2027_paired_handoff.py"
spec = importlib.util.spec_from_file_location("rch_pair", MODULE)
assert spec and spec.loader
pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)
raw = pair.raw

HTML = b"<!DOCTYPE html><html><head><title>RCH 2027</title></head><body>The European Partnership launches its first Joint Transnational Call (JTC): Foundations for climate-resilient cultural heritage. RCH - Resilient Cultural Heritage. Primul apel de proiecte din cadrul parteneriatului RCH a fost publicat.</body></html>"
PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\nstartxref\n9\n%%EOF\n"
RUN = "test-rch-pair-001"


def reject(fn, *args):
    try:
        fn(*args)
    except (ValueError, FileNotFoundError, TypeError):
        return
    raise AssertionError("fail-closed pairing accepted an invalid fixture")


def replace_manifest(path: Path, obj: dict) -> None:
    obj["handoff_sha256"] = raw.sha256(raw.canonical_json({
        k: v for k, v in obj.items() if k != "handoff_sha256"
    }))
    path.write_text(json.dumps(obj), encoding="utf-8")


def run_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_html, old_pdf = raw.fetch_raw, raw.fetch_document_raw
        try:
            raw.fetch_raw = lambda sid: (HTML, raw.SOURCE_SPECS[sid]["url"], "text/html")
            raw.fetch_document_raw = lambda sid: (PDF, raw.document_url(sid), "application/pdf")
            assert raw.capture(root, RUN)["publish_authorized"] is False
            assert raw.capture_documents(root, RUN)["publish_authorized"] is False
        finally:
            raw.fetch_raw, raw.fetch_document_raw = old_html, old_pdf

        result = pair.seal(root)
        assert result["status"] == "RAW_ORIGINALS_PAIRED_NOT_PUBLISHED"
        assert result["original_count"] == 5
        assert result["open_call_authorized"] is False
        assert result["publish_authorized"] is False
        assert result["semantic_reconciliation_required"] is True
        assert pair.replay(root) == result
        assert pair.seal(root) == result  # immutable, idempotent exact-byte replay

        sealed_path = root / "handoff" / pair.PAIR_NAME
        original_pair = sealed_path.read_bytes()
        forged = json.loads(original_pair)
        forged["publish_authorized"] = True
        replace_manifest(sealed_path, forged)
        reject(pair.replay, root)  # even with recomputed top-level hash
        sealed_path.write_bytes(original_pair)

        forged = json.loads(original_pair)
        forged["source_manifest_raw_sha256"] = "0" * 64
        replace_manifest(sealed_path, forged)
        reject(pair.replay, root)
        sealed_path.write_bytes(original_pair)

        html_original = root / "raw" / "SRC-EU-RCH-2027-CALL1.html"
        original_bytes = html_original.read_bytes()
        html_original.write_bytes(original_bytes + b"<p>fabricated call status OPEN</p>")
        reject(pair.replay, root)
        html_original.write_bytes(original_bytes)

        doc_path = root / "handoff" / "rch_2027_documents.json"
        original_doc = doc_path.read_bytes()
        forged = json.loads(original_doc)
        forged["run_id"] = "different-run"
        for row in forged["receipts"]:
            row["run_id"] = "different-run"
        replace_manifest(doc_path, forged)
        assert raw.validate_document_handoff(root)["publish_authorized"] is False
        reject(pair.replay, root)  # independent checks pass, pair identity fails
        doc_path.write_bytes(original_doc)

        forged = json.loads(original_doc)
        for row in forged["receipts"]:
            row["fetched_at_utc"] = "2026-11-09T20:00:00Z"
        replace_manifest(doc_path, forged)
        assert raw.validate_document_handoff(root)["publish_authorized"] is False
        reject(pair.replay, root)  # stale/mixed source snapshots fail pairing
        doc_path.write_bytes(original_doc)

        # Five internally consistent receipts must still fail if all claim a future capture.
        # The independent raw handoffs only check timestamp shape; the paired gate
        # is responsible for rejecting impossible observation chronology.
        html_path = root / "handoff" / "rch_2027_sources.json"
        original_html = html_path.read_bytes()
        future_html = json.loads(original_html)
        future_pdf = json.loads(original_doc)
        for manifest in (future_html, future_pdf):
            for row in manifest["receipts"]:
                row["fetched_at_utc"] = "2099-11-08T10:00:00Z"
        replace_manifest(html_path, future_html)
        replace_manifest(doc_path, future_pdf)
        assert raw.validate_handoff(root)["publish_authorized"] is False
        assert raw.validate_document_handoff(root)["publish_authorized"] is False
        # Test the chronology gate directly: replay would also reject merely
        # because the already-sealed manifest no longer matches these new bytes.
        reject(pair.expected_pair, root)
        reject(pair.replay, root)
        reject(pair.seal, root)
        html_path.write_bytes(original_html)
        doc_path.write_bytes(original_doc)

        assert pair.replay(root) == result
        reject(pair.seal, root / "missing")
        print("PASS RCH five original manifests paired, immutable SHA and run/future-time/freshness/authorization negative replay")


if __name__ == "__main__":
    run_test()
