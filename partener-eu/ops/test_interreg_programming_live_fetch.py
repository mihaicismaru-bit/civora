#!/usr/bin/env python3
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import interreg_programming_live_fetch as live  # noqa: E402


def _registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "SRC-INTERREG-ROHU",
                        "tier": "T1",
                        "url": "https://interreg-rohu.eu/en/",
                        "programmes": ["Interreg Romania-Hungary 2028-2034"],
                        "material_fact_use": True,
                        "source_families": ["INTERREG", "CBC"],
                        "extract": ["calls", "future_programming_consultations"],
                    },
                    {
                        "id": "SRC-INTERREG-ROMD-2028-2034",
                        "tier": "T1",
                        "url": "https://ro-md.net/en/news-2021-2027/public-consultation-on-the-future-interreg-romania-moldova-chapter-2028-2034",
                        "programmes": ["Interreg Romania-Republic of Moldova 2028-2034"],
                        "material_fact_use": False,
                        "source_families": ["INTERREG", "CBC", "NEXT", "PROGRAMMING_PIPELINE"],
                        "extract": ["stakeholder_consultations", "programming_updates"],
                    },
                    {
                        "id": "SRC-INTERREG-ROHU-CALLS",
                        "tier": "T1",
                        "url": "https://interreg-rohu.eu/en/calls/",
                        "programmes": ["Interreg VI-A Romania-Hungary 2021-2027"],
                        "material_fact_use": True,
                        "source_families": ["INTERREG", "CBC"],
                        "extract": ["calls"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def main():
    with tempfile.TemporaryDirectory() as tmp:
        registry = Path(tmp) / "registry.json"
        _registry(registry)
        selected = live._programming_sources(live._load_registry(registry))
        assert [row["id"] for row in selected] == ["SRC-INTERREG-ROHU", "SRC-INTERREG-ROMD-2028-2034"]

        html = b"""<!doctype html><html><head><title>Programming 2027+</title></head>
        <body><h1>STAKEHOLDER SURVEY NOW OPEN</h1>
        <p>The preparation of the future Interreg Programme between Romania and Hungary
        for the 2028-2034 period has officially started.</p>
        <p>Stakeholder consultation survey open from 08.06.2026 to 01.08.2026.</p>
        <script>OPEN CALL fake javascript content</script></body></html>"""
        text = live._visible_text(html, "text/html; charset=utf-8")
        assert "STAKEHOLDER SURVEY NOW OPEN" in text
        assert "fake javascript" not in text

        original_fetch = live._fetch
        original_now = live._utc_now
        try:
            live._fetch = lambda url: (html, url, 200, "text/html; charset=utf-8")
            live._utc_now = lambda: "2026-08-28T01:51:17Z"
            envelope = live.build_live_evidence(registry, run_id="TEST-INTERREG-LIVE")
        finally:
            live._fetch = original_fetch
            live._utc_now = original_now

        live.validate_envelope(envelope)
        assert envelope["source_count"] == 2
        assert envelope["fetch_pass"] == 2
        assert envelope["fetch_fail"] == 0
        rows = {row["source_id"]: row for row in envelope["rows"]}
        row = rows["SRC-INTERREG-ROHU"]
        assert row["raw_hash"]
        normalized = row["normalized"]
        assert normalized["observation_state"] == "CONSULTATION_CLOSED", normalized
        assert normalized["stale_open_copy"] is True
        assert normalized["not_a_call"] is True
        assert normalized["open_call_authorized"] is False
        assert normalized["publish_authorized"] is False
        assert normalized["material_fact_use"] is False

        romd = rows["SRC-INTERREG-ROMD-2028-2034"]["normalized"]
        assert romd["programme_family"] == "Interreg Romania-Republic of Moldova 2028-2034"
        assert romd["not_a_call"] is True
        assert romd["open_call_authorized"] is False
        assert romd["publish_authorized"] is False
        assert romd["material_fact_use"] is False

        unsafe = json.loads(json.dumps(envelope))
        unsafe["rows"][0]["normalized"]["open_call_authorized"] = True
        try:
            live.validate_envelope(unsafe)
        except ValueError as exc:
            assert "authorized OPEN" in str(exc)
        else:
            raise AssertionError("unsafe programming envelope must fail closed")

    print("PASS Interreg live programming evidence: exact official bytes remain non-authorizing")


if __name__ == "__main__":
    main()
