#!/usr/bin/env python3
"""Hermetic DR-12 monthly-stage/provenance negative tests. No live network."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))
spec = importlib.util.spec_from_file_location("afir_dr12_quality_watch", INGEST / "afir_dr12_quality_watch.py")
assert spec and spec.loader
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

SENTENCE = (
    "Intervenția DR-12 pentru tinerii fermieri. "
    "Pragul de calitate lunar aferent depunerii cererilor de finanțare este "
    "de 80 de puncte (în intervalul 6 octombrie – 5 noiembrie 2026), "
    "ulterior pragul scade la 45 de puncte în cea de-a doua etapă lunară "
    "(6 noiembrie – 2 decembrie 2026) pentru ambele componente."
)


def raw(text: str = SENTENCE) -> bytes:
    return f"<html><article><p>{text}</p></article></html>".encode("utf-8")


def rejected(fn, marker: str | None = None) -> None:
    try:
        fn()
    except ValueError as exc:
        if marker:
            assert marker in str(exc), str(exc)
    else:
        raise AssertionError("bad DR-12 source/provenance admitted")


def test_official_transport_encoding_gate() -> None:
    """Hermetic AFIR fetch: an HTTP 200 compressed body is not raw HTML evidence."""
    from unittest.mock import patch

    class Response:
        def __init__(self, body: bytes, encoding: str | None, length: int | None = None):
            self.body = body
            self.read_count = 0
            self.status = 200
            self.headers = {"Content-Type": "text/html; charset=utf-8"}
            if encoding is not None:
                self.headers["Content-Encoding"] = encoding
            if length is not None:
                self.headers["Content-Length"] = str(length)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def geturl(self):
            return watch.NOTICE_URL

        def read(self, limit: int):
            self.read_count += 1
            return self.body[:limit]

    def fetch_response(response: Response) -> dict:
        class Opener:
            def open(self, request, timeout):
                assert request.full_url == watch.NOTICE_URL
                return response

        with patch.object(watch.transport.urllib.request, "build_opener",
                          return_value=Opener()):
            return watch.transport.fetch(watch.NOTICE_URL, sleep=lambda _: None)

    good = Response(raw(), None, len(raw()))
    accepted = fetch_response(good)
    assert accepted["ok"] is True and accepted["data"] == raw()
    assert good.read_count == 1

    for encoded in ("gzip", "br", "GZIP", "identity, gzip", ""):
        bad = Response(raw(), encoded)
        rejected_fetch = fetch_response(bad)
        # Empty Content-Encoding, like absence, means no encoding specified;
        # the remaining body/length/semantic gates still apply.
        if encoded == "":
            assert rejected_fetch["ok"] is True
            continue
        assert rejected_fetch["ok"] is False
        assert rejected_fetch["attemptCount"] == 1
        assert "unsupported encoded body" in rejected_fetch["error"]
        assert bad.read_count == 0  # reject before reading or hashing bytes

    truncated = Response(raw(), "identity", len(raw()) + 7)
    refused = fetch_response(truncated)
    assert refused["ok"] is False
    assert "declared Content-Length" in refused["error"]


def main() -> None:
    test_official_transport_encoding_gate()
    stages = watch.parse_notice(raw())
    assert len(stages) == 2
    assert [s["minimum_quality_points"] for s in stages] == [80, 45]
    assert stages[0]["through_date"] == "2026-11-05"
    assert stages[1]["from_date"] == "2026-11-06"
    assert all(s["components"] == ["ZOOTEHNIC", "VEGETAL"] for s in stages)

    # A 45-year-old farmer / 45% grant figure is NOT a quality threshold.
    for changed in (
        SENTENCE.replace("DR-12", "DR-14"),
        SENTENCE.replace("80 de puncte", "70 de puncte"),
        SENTENCE.replace("45 de puncte", "40 de puncte"),
        SENTENCE.replace("5 noiembrie 2026", "6 noiembrie 2026"),
        SENTENCE.replace("6 noiembrie – 2 decembrie", "7 noiembrie – 2 decembrie"),
        SENTENCE.replace("2 decembrie 2026", "3 decembrie 2026"),
        SENTENCE.replace("pentru ambele componente", "pentru componenta vegetală"),
        "DR-12 - 45 de ani; 80% ajutor; 6 noiembrie – 2 decembrie 2026.",
    ):
        rejected(lambda changed=changed: watch.parse_notice(raw(changed)), "missing")
    # A previously valid statement must not mask a second contradictory
    # or duplicate statement, including one with malformed numbers.
    for ambiguous in (
        SENTENCE + " " + SENTENCE,
        SENTENCE + " " + SENTENCE.replace("80 de puncte", "70 de puncte"),
        SENTENCE + " " + SENTENCE.replace("5 noiembrie 2026", "6 noiembrie 2026"),
        SENTENCE.replace("este de 80", "este " + "explicație " * 110 + "de 80"),
    ):
        rejected(lambda ambiguous=ambiguous: watch.parse_notice(raw(ambiguous)),
                 "duplicated or contradictory")
    assert watch.PARSER_VERSION.endswith("-v3")

    rejected(lambda: watch.parse_notice(b""))
    rejected(lambda: watch.parse_notice(b"a" * 12_000_001))

    fetched = {
        "ok": True,
        "url": watch.NOTICE_URL,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "data": raw(),
    }
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        receipt = base / "first"
        record = watch.capture(
            fetched, receipt, run_id="42199999999", run_attempt="1",
            fetched_at_utc="2026-11-05T21:30:00Z",
        )
        assert record == json.loads((receipt / "manifest.json").read_text(encoding="utf-8"))
        assert record["raw_sha256"] == hashlib.sha256(raw()).hexdigest()
        assert (receipt / record["raw_evidence_file"]).read_bytes() == raw()
        assert watch.replay_receipt(receipt) == record
        original_manifest = (receipt / "manifest.json").read_bytes()
        for key, bad in (
            ("raw_sha256", "0" * 64),
            ("run_id", ""),
            ("parser_version", "unknown"),
            ("programme", "DR-14"),
            ("requested_url", "https://example.com"),
            ("source_family", "UNVERIFIED"),
            ("observation_state", "OPEN_CALL"),
            ("open_call_authorized", True),
            ("publish_authorized", True),
            ("distribution_authorized", True),
            ("fetched_at_utc", "2026-11-05T21:30:00"),
        ):
            altered = copy.deepcopy(record)
            altered[key] = bad
            (receipt / "manifest.json").write_text(
                json.dumps(altered, ensure_ascii=False), encoding="utf-8"
            )
            rejected(lambda: watch.replay_receipt(receipt))
        altered = copy.deepcopy(record)
        altered["stages"][1]["minimum_quality_points"] = 20
        (receipt / "manifest.json").write_text(json.dumps(altered), encoding="utf-8")
        rejected(lambda: watch.replay_receipt(receipt), "stages")
        (receipt / "manifest.json").write_bytes(original_manifest)
        (receipt / "notice.raw.html").write_bytes(raw().replace(b"DR-12", b"DR-14"))
        rejected(lambda: watch.replay_receipt(receipt))
        (receipt / "notice.raw.html").write_bytes(raw())
        assert watch.replay_receipt(receipt) == record

        # The evidence receipt is an exact closed schema and closed file set.
        # Extra authorizing keys must not hide inside an otherwise correct
        # SHA-256 manifest, and arbitrary sidecars/symlinks are not originals.
        unexpected = copy.deepcopy(record)
        unexpected["open_call_status"] = "OPEN_CALL"
        (receipt / "manifest.json").write_text(
            json.dumps(unexpected, ensure_ascii=False), encoding="utf-8"
        )
        rejected(lambda: watch.replay_receipt(receipt), "unregistered fields")
        (receipt / "manifest.json").write_bytes(original_manifest)

        # Python's default JSON decoder silently keeps the last occurrence:
        # duplicate top-level or nested stage keys are untrusted evidence.
        # An escaped spelling is still the same JSON key after decoding.
        baseline = original_manifest.decode("utf-8")
        ambiguous_manifests = (
            baseline.replace(
                '"publish_authorized": false',
                '"publish_authorized": false, "publish_authorized": true', 1),
            baseline.replace(
                '"publish_authorized": false',
                '"publish_authorized": false, "\\u0070ublish_authorized": true', 1),
            baseline.replace(
                '"minimum_quality_points": 45',
                '"minimum_quality_points": 45, "minimum_quality_points": 20', 1),
            baseline.replace(
                f'"raw_bytes": {len(raw())}',
                '"raw_bytes": NaN', 1),
        )
        for untrusted in ambiguous_manifests:
            assert untrusted != baseline
            (receipt / "manifest.json").write_text(untrusted, encoding="utf-8")
            rejected(lambda: watch.replay_receipt(receipt), "JSON")
        (receipt / "manifest.json").write_bytes(original_manifest)

        altered_schema = copy.deepcopy(record)
        altered_schema["schema_version"] = "2.0"
        (receipt / "manifest.json").write_text(
            json.dumps(altered_schema, ensure_ascii=False), encoding="utf-8"
        )
        rejected(lambda: watch.replay_receipt(receipt), "schema")
        (receipt / "manifest.json").write_bytes(original_manifest)

        extra = receipt / "unregistered.json"
        extra.write_text('{"publish_authorized": true}', encoding="utf-8")
        rejected(lambda: watch.replay_receipt(receipt), "extra or symlinked")
        extra.unlink()

        if os.name != "nt":
            external = base / "notice-copy.html"
            external.write_bytes(raw())
            original = receipt / "notice.raw.html"
            original.unlink()
            original.symlink_to(external)
            rejected(lambda: watch.replay_receipt(receipt), "symlinked")
            original.unlink()
            original.write_bytes(raw())
            linked_dir = base / "linked-receipt"
            linked_dir.symlink_to(receipt, target_is_directory=True)
            rejected(lambda: watch.replay_receipt(linked_dir), "symlinked")
            linked_dir.unlink()

        assert watch.replay_receipt(receipt) == record
        assert record["fetched_at_utc"] == "2026-11-05T21:30:00Z"
        assert record["source_family"] == "AFIR"
        assert record["authority_class"] == "T1_OFFICIAL_AGENCY"
        assert record["programme"] == "PS_PAC_2023_2027/DR12"
        assert record["observation_state"].endswith("RECONCILIATION")
        assert record["exact_current_call_identifier_verified"] is False
        assert record["open_call_authorized"] is False
        assert record["eligibility_change_authorized"] is False
        assert record["publish_authorized"] is False
        assert record["distribution_authorized"] is False
        assert record["material_fact_action"] == "NONE"
        assert record["parser_version"] == watch.PARSER_VERSION
        # Immutable destination cannot be reused or updated on another run.
        before = (receipt / "manifest.json").read_bytes()
        rejected(lambda: watch.capture(fetched, receipt, run_id="other-run",
                     fetched_at_utc="2026-11-06T00:00:00Z"), "already exists")
        assert before == (receipt / "manifest.json").read_bytes()
        assert (receipt / "notice.raw.html").read_bytes() == raw()

        wrong_sources = [
            dict(fetched, url="https://example.com/mirror"),
            dict(fetched, url="http://www.afir.ro/comunicate/170-de-milioane-euro-pentru-exploatatiile-tinerilor-fermieri/"),
            dict(fetched, url="https://www.afir.ro/comunicate/unrelated/"),
            dict(fetched, ok=False),
            dict(fetched, status=403),
            dict(fetched, content_type="application/pdf"),
            dict(fetched, data=b""),
        ]
        for i, invalid in enumerate(wrong_sources):
            rejected(lambda invalid=invalid, i=i: watch.capture(
                invalid, base / f"bad-{i}", run_id="RUN",
                fetched_at_utc="2026-11-05T21:30:00Z"))
            assert not (base / f"bad-{i}").exists()
        rejected(lambda: watch.capture(fetched, base / "no-run", run_id="",
                     fetched_at_utc="2026-11-05T21:30:00Z"))
        rejected(lambda: watch.capture(fetched, base / "naive", run_id="RUN",
                     fetched_at_utc="2026-11-05T21:30:00"), "timezone-aware")

    assert watch.NOTICE_URL.startswith("https://www.afir.ro/comunicate/")
    assert watch.transport._strict_afir_https(watch.NOTICE_URL)
    print("PASS AFIR DR-12: 80-to-45 monthly quality threshold, immutable raw provenance; never OPEN_CALL")


if __name__ == "__main__":
    main()
