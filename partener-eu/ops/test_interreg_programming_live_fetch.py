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
            original_dir = Path(tmp) / "immutable-originals"
            envelope = live.build_live_evidence(registry, run_id="TEST-INTERREG-LIVE", raw_dir=original_dir)
        finally:
            live._fetch = original_fetch
            live._utc_now = original_now

        live.validate_envelope(envelope)
        assert live.replay_live_evidence(envelope, original_dir, registry) == 2
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


        # The manifest/hash alone is not replayable provenance; the original
        # article bytes must exist and match the exact source registry.
        original = original_dir / "SRC-INTERREG-ROHU.raw.html"
        saved = original.read_bytes()
        original.write_bytes(saved.replace(b"STAKEHOLDER", b"COUNTERFEIT"))
        try:
            live.replay_live_evidence(envelope, original_dir, registry)
        except ValueError as exc:
            assert "SHA mismatch" in str(exc)
        else:
            raise AssertionError("tampered original must be rejected")
        original.write_bytes(saved)
        assert live.replay_live_evidence(envelope, original_dir, registry) == 2
        for key, value in (
            ("raw_hash", "0" * 64),
            ("raw_evidence_file", "../untrusted.html"),
            ("run_id", "forged-run"),
            ("registered_url", "https://example.invalid/mirror"),
        ):
            bad = json.loads(json.dumps(envelope))
            bad["rows"][0][key] = value
            try:
                live.replay_live_evidence(bad, original_dir, registry)
            except ValueError:
                pass
            else:
                raise AssertionError(f"forged raw manifest admitted: {key}")
        bad = json.loads(json.dumps(envelope))
        bad["rows"][0]["normalized"]["observation_state"] = "PLANNED"
        try:
            live.replay_live_evidence(bad, original_dir, registry)
        except ValueError:
            pass
        else:
            raise AssertionError("semantic state detached from original raw bytes")
        extra = original_dir / "unclaimed.raw.html"
        extra.write_bytes(saved)
        try:
            live.replay_live_evidence(envelope, original_dir, registry)
        except ValueError as exc:
            assert "orphaned" in str(exc)
        else:
            raise AssertionError("unclaimed raw file admitted")
        extra.unlink()
        assert live.replay_live_evidence(envelope, original_dir, registry) == 2
        try:
            live.build_live_evidence(registry, run_id="second-run", raw_dir=original_dir)
        except ValueError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("immutable raw directory overwritten")

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
