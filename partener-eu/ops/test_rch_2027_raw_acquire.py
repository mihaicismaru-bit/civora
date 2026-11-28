#!/usr/bin/env python3
"""Hermetic RCH 2027 official HTML acquisition/immutable handoff regression."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from copy import deepcopy
from pathlib import Path

MODULE = Path(__file__).parents[1] / "ingest" / "rch_2027_raw_acquire.py"
spec = importlib.util.spec_from_file_location("rch_acquisition", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

RAW = b"<!DOCTYPE html><html><head><title>RCH 2027</title></head><body>The European Partnership launches its first Joint Transnational Call (JTC): Foundations for climate-resilient cultural heritage. RCH - Resilient Cultural Heritage. Primul apel de proiecte din cadrul parteneriatului RCH a fost publicat.</body></html>"
STAMP = "2026-11-08T07:28:14Z"
RUN_ID = "test-rch-2027-001"


def must_reject(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (ValueError, FileNotFoundError, TypeError):
        return
    raise AssertionError(f"expected fail-closed rejection: {fn.__name__}")


def test_url_and_response_policy():
    for sid, info in mod.SOURCE_SPECS.items():
        mod.validate_url(sid, info["url"])
        base = info["url"]
        for changed in (
            base.replace("https://", "http://", 1),
            base.replace("https://", "https://other.example@", 1),
            base + "?status=open",
            base + "#preannounce",
            base.replace("https://", "https://", 1).replace("/", ":8443/", 1)
            if False else "https://evil.example" + info["path"],
            base.rsplit("/", 1)[0] + "/pre-announcement-jtc1-rch/",
        ):
            must_reject(mod.validate_url, sid, changed)
        mod.validate_response(sid, status=200, mime="text/html",
                              encoding="identity", declared_length=str(len(RAW)), raw=RAW)
        mod.validate_response(sid, status=200, mime="application/xhtml+xml",
                              encoding="", declared_length=None, raw=RAW)
        for content_type in ("application/json; note=text/html", "text/plain; filename=call.html",
                             "text/html-fake", "application/pdf", "application/octet-stream"):
            must_reject(mod.validate_response, sid, status=200, mime=content_type,
                        encoding="identity", declared_length=None, raw=RAW)

        # A valid HTTP 200 envelope containing only invisible/mismatched call
        # identity is not an official call-detail observation.
        wrong = b"<!doctype html><html><body>Unrelated maintenance page</body></html>"
        must_reject(mod.validate_response, sid, status=200, mime="text/html",
                    encoding="identity", declared_length=None, raw=wrong)
        hidden = (b"<!doctype html><html><body>Unrelated maintenance page"
                  + b"<script>" + RAW + b"</script>"
                  + b"<template>" + RAW + b"</template>"
                  + b"<div hidden>" + RAW + b"</div>"
                  + b"<div aria-hidden='true'>" + RAW + b"</div>"
                  + b"<div style='display:none'>" + RAW + b"</div>"
                  + b"</body></html>")
        must_reject(mod.validate_response, sid, status=200, mime="text/html",
                    encoding="identity", declared_length=None, raw=hidden)
        # A forged call identity inside CSS-invisible descendants must not
        # turn an unrelated HTTP 200 HTML page into an official receipt.
        # Tabs/newlines evade a space-only CSS normalization.
        for css in ("display:\tnone", "visibility:\nhidden",
                    "visibility:collapse", "content-visibility:hidden",
                    "opacity:0", "opacity:0!important"):
            page = (b"<!doctype html><html><body>Unrelated maintenance page"
                    + b"<div style='" + css.encode("ascii") + b"'>" + RAW
                    + b"</div></body></html>")
            must_reject(mod.validate_response, sid, status=200, mime="text/html",
                        encoding="identity", declared_length=None, raw=page)
        # HTML controls may be hidden without inline display:none. The old
        # extractor accepted identity anchors inside native inactive elements.
        for before, after in (
            (b"<div inert>", b"</div>"),
            (b"<dialog>", b"</dialog>"),
            (b"<details>", b"</details>"),
            (b"<div popover='manual'>", b"</div>"),
            (b"<select><option>", b"</option></select>"),
            (b"<textarea>", b"</textarea>"),
            (b"<iframe>", b"</iframe>"),
            (b"<datalist>", b"</datalist>"),
            (b"<canvas>", b"</canvas>"),
            (b"<div style='opacity:0.00'>", b"</div>"),
            (b"<div aria-hidden='true' aria-hidden='false'>", b"</div>"),
            (b"<div style='display:none' style='display:block'>", b"</div>"),
            (b"<details open open>", b"</details>"),
        ):
            page = b"<!doctype html><html><body>Unrelated maintenance page" + before + RAW + after + b"</body></html>"
            must_reject(mod.validate_response, sid, status=200, mime="text/html",
                        encoding="identity", declared_length=None, raw=page)
        # Genuine visible copy still proves the identity, including an open
        # native details element; this guard must not suppress real evidence.
        visible = b"<!doctype html><html><body><details open>" + RAW + b"</details></body></html>"
        mod.validate_response(sid, status=200, mime="text/html",
                              encoding="identity", declared_length=None, raw=visible)
        must_reject(mod.validate_response, sid, status=403, mime="text/html",
                    encoding="identity", declared_length=None, raw=RAW)
        must_reject(mod.validate_response, sid, status=200, mime="text/html",
                    encoding="gzip", declared_length=None, raw=RAW)
        must_reject(mod.validate_response, sid, status=200, mime="text/html",
                    encoding="identity", declared_length=str(len(RAW) + 1), raw=RAW)
        must_reject(mod.validate_response, sid, status=200, mime="text/html",
                    encoding="identity", declared_length="nonsense", raw=RAW)
        must_reject(mod.validate_response, sid, status=200, mime="text/html",
                    encoding="identity", declared_length=None, raw=b'{"html": "ransom"}')


def test_capture_replay_and_fail_closed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "evidence"
        actual_fetch = mod.fetch_raw
        calls = []
        try:
            def fake_fetch(sid):
                calls.append(sid)
                return RAW, mod.SOURCE_SPECS[sid]["url"], "text/html"
            mod.fetch_raw = fake_fetch
            receipt = mod.capture(root, RUN_ID)
            assert receipt["status"] == "RAW_REPLAY_VERIFIED_NOT_PUBLISHED"
            assert receipt["publish_authorized"] is False
            assert calls == sorted(mod.SOURCE_SPECS)
        finally:
            mod.fetch_raw = actual_fetch

        manifest_path = root / "handoff" / "rch_2027_sources.json"
        original = manifest_path.read_bytes()
        handoff = json.loads(original)
        assert handoff["run_id"] == RUN_ID
        assert handoff["handoff_sha256"] == mod.sha256(mod.canonical_json({
            key: value for key, value in handoff.items() if key != "handoff_sha256"
        }))
        assert all(r["raw_sha256"] == mod.sha256(RAW) for r in handoff["receipts"])
        assert all(r["parser_version"] == mod.PARSER_VERSION for r in handoff["receipts"])
        assert all(r["observation_state"].endswith("UNRECONCILED") for r in handoff["receipts"])
        assert all(r["open_call_authorized"] is False for r in handoff["receipts"])

        # Byte-exact replay rejects raw mutation, even with valid HTML structure.
        raw_file = root / handoff["receipts"][0]["raw_path"]
        raw_file.write_bytes(RAW + b"<p>tampered deadline</p>")
        must_reject(mod.validate_handoff, root)
        raw_file.write_bytes(RAW)

        # Manifest edit without the recomputed handoff hash fails.
        bad = deepcopy(handoff)
        bad["publish_authorized"] = True
        manifest_path.write_text(json.dumps(bad), encoding="utf-8")
        must_reject(mod.validate_handoff, root)

        # Attacker recomputing a handoff hash still cannot waive any safety flag.
        bad["handoff_sha256"] = mod.sha256(mod.canonical_json({
            key: value for key, value in bad.items() if key != "handoff_sha256"
        }))
        manifest_path.write_text(json.dumps(bad), encoding="utf-8")
        must_reject(mod.validate_handoff, root)

        for tamper in (
            {"source_id": "SRC-EU-FAKE"},
            {"requested_url": "https://evil.example/call/"},
            {"final_url": "https://evil.example/call/"},
            {"raw_path": "../other.txt"},
            {"observation_state": "OPEN_CALL"},
            {"authority_class": "T1_CALL_AUTHORITY"},
            {"deadline_authorized": True},
            {"parser_version": "RCH_2027_RAW_ACQUISITION_V0"},
            {"fetched_at_utc": "last week"},
            {"run_id": "another-run"},
        ):
            bad = deepcopy(handoff)
            bad["receipts"][0].update(tamper)
            bad["handoff_sha256"] = mod.sha256(mod.canonical_json({
                key: value for key, value in bad.items() if key != "handoff_sha256"
            }))
            manifest_path.write_text(json.dumps(bad), encoding="utf-8")
            must_reject(mod.validate_handoff, root)

        # Rehashing an extended manifest must never smuggle in extra
        # distribution/publication flags beyond the registered evidence schema.
        for scope in ("handoff", "receipt"):
            bad = deepcopy(handoff)
            target = bad if scope == "handoff" else bad["receipts"][0]
            target["distribution_authorized"] = True
            bad["handoff_sha256"] = mod.sha256(mod.canonical_json({
                k: v for k, v in bad.items() if k != "handoff_sha256"
            }))
            manifest_path.write_text(json.dumps(bad), encoding="utf-8")
            must_reject(mod.validate_handoff, root)
        # Duplicate keys are ambiguous between parsers even when the last
        # occurrence is innocuous; reject at the JSON decode boundary.
        manifest_path.write_text(
            original.decode("utf-8").replace(
                '"run_id": "', '"run_id": "forged", "run_id": "', 1
            ), encoding="utf-8"
        )
        must_reject(mod.read_evidence_json, manifest_path)
        manifest_path.write_text(original.decode("utf-8").replace(
            '"schema_version": "1.0"', '"schema_version": NaN'
        ), encoding="utf-8")
        must_reject(mod.read_evidence_json, manifest_path)

        manifest_path.write_bytes(original)
        assert mod.validate_handoff(root)["status"] == "RAW_REPLAY_VERIFIED_NOT_PUBLISHED"
        mod.write_immutable(manifest_path, original)
        must_reject(mod.write_immutable, manifest_path, b"overwritten")
        must_reject(mod.capture, root, "../unsafe-run")




PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\nstartxref\n9\n%%EOF\n"


def test_document_originals_and_annex_locator():
    for sid in mod.DOCUMENT_SPECS:
        url = mod.document_url(sid)
        mod.validate_document_url(sid, url)
        for altered in (
            url.replace("https://", "http://", 1),
            url.replace("www.heritageresearch-hub.eu", "evil.example"),
            url + "?preview=true",
            url + "#annex",
            url.replace(".pdf", "-draft.pdf"),
        ):
            must_reject(mod.validate_document_url, sid, altered)
        mod.validate_document_response(status=200, mime="application/pdf",
                                       encoding="identity", declared_length=str(len(PDF)), raw=PDF)
        for kwargs in (
            {"status": 403, "mime": "application/pdf", "encoding": "identity", "declared_length": None, "raw": PDF},
            {"status": 200, "mime": "text/html; filename=.pdf", "encoding": "identity", "declared_length": None, "raw": PDF},
            {"status": 200, "mime": "application/pdf-fake", "encoding": "identity", "declared_length": None, "raw": PDF},
            {"status": 200, "mime": "application/pdf", "encoding": "gzip", "declared_length": None, "raw": PDF},
            {"status": 200, "mime": "application/pdf", "encoding": "identity", "declared_length": str(len(PDF)+1), "raw": PDF},
            {"status": 200, "mime": "application/pdf", "encoding": "identity", "declared_length": None, "raw": b"<html>bad</html>"},
            {"status": 200, "mime": "application/pdf", "encoding": "identity", "declared_length": None, "raw": PDF[:-6]},
        ):
            must_reject(mod.validate_document_response, **kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        actual_fetch = mod.fetch_document_raw
        calls = []
        try:
            def fake_fetch(sid):
                calls.append(sid)
                return PDF, mod.document_url(sid), "application/pdf"
            mod.fetch_document_raw = fake_fetch
            outcome = mod.capture_documents(root, RUN_ID)
            assert outcome["status"] == "PDF_RAW_REPLAY_VERIFIED_NOT_PUBLISHED"
            assert outcome["publish_authorized"] is False
            assert calls == sorted(mod.DOCUMENT_SPECS)
        finally:
            mod.fetch_document_raw = actual_fetch
        manifest_file = root / "handoff" / "rch_2027_documents.json"
        original = manifest_file.read_bytes()
        manifest = json.loads(original)
        assert manifest["national_annex_locator"] == {
            "source_id": "SRC-EU-RCH-2027-CALL-TEXT",
            "section": "Annex I / Romania",
            "page_index_start": 127,
            "page_index_end": 129,
            "location_is_publication_authority": False,
        }
        assert all(not r["publish_authorized"] and not r["open_call_authorized"]
                   and not r["eligibility_authorized"] for r in manifest["receipts"])
        raw_file = root / manifest["receipts"][0]["raw_path"]
        raw_file.write_bytes(PDF + b"evil")
        must_reject(mod.validate_document_handoff, root)
        raw_file.write_bytes(PDF)
        for change in (
            ("publish_authorized", True),
            ("open_call_authorized", True),
            ("eligibility_authorized", True),
            ("raw_sha256", "0" * 64),
            ("raw_path", "../other.pdf"),
            ("source_id", "SRC-EU-FAKE"),
            ("final_url", "https://other.example/call.pdf"),
            ("authority_class", "T1_CALL_AUTHORITY"),
            ("observation_state", "OPEN_CALL"),
        ):
            bad = deepcopy(manifest)
            bad["receipts"][0][change[0]] = change[1]
            bad["handoff_sha256"] = mod.sha256(mod.canonical_json({
                k: v for k, v in bad.items() if k != "handoff_sha256"
            }))
            manifest_file.write_text(json.dumps(bad), encoding="utf-8")
            must_reject(mod.validate_document_handoff, root)
        bad = deepcopy(manifest)
        bad["national_annex_locator"]["page_index_start"] = 1
        bad["handoff_sha256"] = mod.sha256(mod.canonical_json({
            k: v for k, v in bad.items() if k != "handoff_sha256"
        }))
        manifest_file.write_text(json.dumps(bad), encoding="utf-8")
        must_reject(mod.validate_document_handoff, root)
        for scope in ("handoff", "receipt"):
            bad = deepcopy(manifest)
            target = bad if scope == "handoff" else bad["receipts"][0]
            target["distribution_authorized"] = True
            bad["handoff_sha256"] = mod.sha256(mod.canonical_json({
                k: v for k, v in bad.items() if k != "handoff_sha256"
            }))
            manifest_file.write_text(json.dumps(bad), encoding="utf-8")
            must_reject(mod.validate_document_handoff, root)
        manifest_file.write_text(original.decode("utf-8").replace(
            '"run_id": "', '"run_id": "forged", "run_id": "', 1
        ), encoding="utf-8")
        must_reject(mod.read_evidence_json, manifest_file)

        manifest_file.write_bytes(original)
        assert mod.validate_document_handoff(root)["publish_authorized"] is False
        mod.write_immutable(manifest_file, original)
        must_reject(mod.write_immutable, manifest_file, b"overwritten")

if __name__ == "__main__":
    test_url_and_response_policy()
    test_capture_replay_and_fail_closed()
    test_document_originals_and_annex_locator()
    print("PASS RCH 2027 paired HTML + three official PDFs, Annex I locator, immutable SHA handoff, nonpublishing adversarial replay")
