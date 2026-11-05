#!/usr/bin/env python3
"""Hermetic DR-12 monthly-stage/provenance negative tests. No live network."""
from __future__ import annotations

import hashlib
import importlib.util
import json
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


def main() -> None:
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
