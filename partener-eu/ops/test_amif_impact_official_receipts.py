#!/usr/bin/env python3
"""Hermetic adversarial AMIF IMPACT original-byte handoff test."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "amif_impact_official_receipts", ROOT / "partener-eu" / "ingest" /
    "amif_impact_official_receipts.py",
)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

HTML_ID = "SRC-MAI-AMIF-IMPACT-LOT3-20261110"
PDF_ID = "SRC-EC-AMIF-IMPACT-2026-51-PDF"
HTML = b"""<!doctype html><html><head><title>Example</title></head><body>
<h1>Clarificari COM - Actiunea specifica IMPACT</h1>
<p>publicat 10 noiembrie 2026</p>
<p>Numai pentru Lotul 3 a fost extins termenul pana la 20 noiembrie 2026.</p>
<p>Documentul HOME-Funds/2026/51 a fost transmis statelor membre.</p>
</body></html>"""
PDF = b"%PDF-1.7\n1 0 obj\n<</Type/Catalog>>\nendobj\nstartxref\n0\n%%EOF\n"
STAMP = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
ORIGINALS = {HTML_ID: (HTML, "text/html; charset=utf-8", STAMP),
             PDF_ID: (PDF, "application/pdf", STAMP)}


def reject(fn, substring):
    try:
        fn()
    except (ValueError, OSError, KeyError) as exc:
        assert substring in str(exc), (substring, exc)
    else:
        raise AssertionError(f"Unsafe AMIF receipt accepted: {substring}")


def test():
    mod.validate_registry()
    for source_id, source in mod.SOURCES.items():
        url = source["url"]
        mod.assert_url(source_id, url)
        reject(lambda u=url, s=source_id: mod.assert_url(s, u.replace("https:", "http:", 1)), "URL")
        reject(lambda u=url, s=source_id: mod.assert_url(s, u + "?status=OPEN"), "URL")
        reject(lambda u=url, s=source_id: mod.assert_url(s, u.replace("fed.mai.gov.ro", "evil.invalid")), "URL")
    mod.validate_raw(HTML_ID, HTML, "text/html; charset=utf-8")
    mod.validate_raw(PDF_ID, PDF, "application/pdf")
    reject(lambda: mod.validate_raw(HTML_ID, HTML.replace(b"20 noiembrie", b"11 noiembrie"), "text/html"), "identity")
    reject(lambda: mod.validate_raw(HTML_ID, b"<html><script>" + HTML + b"</script></html>", "text/html"), "identity")
    reject(lambda: mod.validate_raw(HTML_ID, b"<html><div hidden>" + HTML + b"</div></html>", "text/html"), "identity")
    reject(lambda: mod.validate_raw(HTML_ID, HTML, "text/plain; note=text/html"), "MIME")
    reject(lambda: mod.validate_raw(PDF_ID, b"<html>just a moment</html>", "application/pdf"), "PDF")
    reject(lambda: mod.validate_raw(PDF_ID, b"%PDF-1.7\ntruncated", "application/pdf"), "PDF")
    reject(lambda: mod.validate_raw(PDF_ID, PDF, "text/html"), "PDF")
    reject(lambda: mod.valid_timestamp("2026-11-09T00:00:00Z"), "source date")
    reject(lambda: mod.valid_timestamp("2026-11-11T10:00:00+02:00"), "UTC")
    reject(lambda: mod.build_handoff({HTML_ID: ORIGINALS[HTML_ID]}, "run-1"), "paired")
    reject(lambda: mod.build_handoff(ORIGINALS, "invalid/run/id"), "run_id")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        dest = root / "official-pair"
        done = mod.seal(dest, ORIGINALS, "qa-run-001")
        assert done == {"status": "PAIRED_IMMUTABLE_RAW_REPLAY_VERIFIED_NON_AUTHORIZING",
                        "run_id": "qa-run-001", "source_count": 2,
                        "publication_effect": "NONE", "open_call_authorized": False}
        assert mod.replay(dest) == done
        reject(lambda: mod.seal(dest, ORIGINALS, "duplicate"), "immutable")
        raw_file = dest / "raw" / f"{PDF_ID}.pdf"
        raw_file.write_bytes(PDF + b"tamper")
        reject(lambda: mod.replay(dest), "size/hash")
        raw_file.write_bytes(PDF)
        manifest_file = dest / "handoff.json"
        unchanged = manifest_file.read_bytes()
        bad = json.loads(unchanged)
        bad["open_call_authorized"] = True
        bad["handoff_sha256"] = mod.digest(mod.canonical({k: v for k, v in bad.items() if k != "handoff_sha256"}))
        manifest_file.write_bytes(mod.canonical(bad))
        reject(lambda: mod.replay(dest), "publication gate")
        bad["open_call_authorized"] = False
        bad["receipts"][0]["source_family"] = "FORGED"
        bad["handoff_sha256"] = mod.digest(mod.canonical({k: v for k, v in bad.items() if k != "handoff_sha256"}))
        manifest_file.write_bytes(mod.canonical(bad))
        reject(lambda: mod.replay(dest), "provenance")
        manifest_file.write_bytes(unchanged.replace(b'"schema":', b'"schema":"fake","schema":'))
        reject(lambda: mod.replay(dest), "duplicate")
        manifest_file.write_bytes(unchanged)
        assert mod.replay(dest) == done
        (dest / "raw" / "unexpected").write_text("unexpected")
        reject(lambda: mod.replay(dest), "file-set")
    print("AMIF IMPACT exact official paired raw/replay PASS; OPEN and distribution locked")


if __name__ == "__main__":
    test()
