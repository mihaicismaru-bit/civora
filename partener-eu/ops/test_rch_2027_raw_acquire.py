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

RAW = b"<!DOCTYPE html><html><head><title>RCH 2027</title></head><body>Original official call information</body></html>"
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

        manifest_path.write_bytes(original)
        assert mod.validate_handoff(root)["status"] == "RAW_REPLAY_VERIFIED_NOT_PUBLISHED"
        mod.write_immutable(manifest_path, original)
        must_reject(mod.write_immutable, manifest_path, b"overwritten")
        must_reject(mod.capture, root, "../unsafe-run")


if __name__ == "__main__":
    test_url_and_response_policy()
    test_capture_replay_and_fail_closed()
    print("PASS RCH 2027 paired-source TLS policy, immutable SHA handoff, nonpublishing replay and adversarial mutations")
