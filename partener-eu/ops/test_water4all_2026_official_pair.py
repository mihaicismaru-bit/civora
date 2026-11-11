#!/usr/bin/env python3
"""Hermetic adversarial replay for the Water4All 2026 official HTML pair."""
import importlib.util
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "water4all_pair", ROOT / "partener-eu" / "ingest" / "water4all_2026_official_pair.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

EU = "SRC-EU-WATER4ALL-2026-JTC"
RO = "SRC-RO-UEFISCDI-WATER4ALL-2026"
EU_HTML = ("""<!doctype html><html><head><title>Water</title></head><body>
<h1>Water4All 2026 Joint Transnational Call</h1>
<p>Submission deadline of preproposals: 10 November 2026, 15:00 CET.</p>
<p>Submission deadline of full proposals: 6 April 2027, 15:00 CEST.</p>
<p>Following 23 October 2026 change use the new EPSS link.</p>
<p>Stage 2 selection is not a new open intake.</p>
</body></html>""").encode("utf-8")
RO_HTML = ("""<!doctype html><html><head><title>2026</title></head><body>
<h1>Apelul Water4All 2026</h1><p>Water4all-2026</p>
<p>Termen limită de depunere a pre-propunerilor 10 noiembrie 2026, ora 15:00 CET.</p>
<p>Termen limită de depunere a propunerilor finale 06 aprilie 2027, ora 15:00 CEST.</p>
<p>Link apel: https://www.water4all-partnership.eu/joint-activities/water4all-2026-joint-transnational-call</p>
</body></html>""").encode("utf-8")
STAMP = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
ORIGINALS = {EU: (EU_HTML, "text/html; charset=UTF-8", STAMP),
             RO: (RO_HTML, "text/html; charset=UTF-8", STAMP)}


def reject(action, name):
    try:
        action()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        assert name in str(exc), (name, exc)
    else:
        raise AssertionError("unsafe Water4All evidence was accepted: " + name)


def run():
    mod.validate_registry()
    for sid in mod.SOURCES:
        url = mod.SOURCES[sid]["url"]
        mod.exact_url(sid, url)
        for variant in (url.replace("https:", "http:", 1),
                        url.replace(mod.SOURCES[sid]["host"], "evil.invalid"),
                        url + "?status=OPEN_CALL", url + "#untrusted"):
            reject(lambda v=variant, s=sid: mod.exact_url(s, v), "URL")
    for sid, (raw, mime, _) in ORIGINALS.items():
        mod.validate_html(sid, raw, mime)
        reject(lambda s=sid, b=raw: mod.validate_html(s, b, "text/plain; note=text/html"), "MIME")
        reject(lambda s=sid, b=raw: mod.validate_html(s, b"<html>" + b[:10], "text/html"), "implausible")
        reject(lambda s=sid, b=raw: mod.validate_html(s, b"<html><script>" + b.decode().replace("<", "&lt;").encode() + b"</script></html>", "text/html"), "marker")
    reject(lambda: mod.validate_html(EU, EU_HTML.replace(b"10 November 2026", b"11 November 2026"), "text/html"), "marker")
    reject(lambda: mod.validate_html(RO, RO_HTML.replace(b"06 aprilie 2027", b"06 martie 2027"), "text/html"), "marker")
    reject(lambda: mod.timestamp_ok("2026-11-09T10:00:00Z"), "clock")
    reject(lambda: mod.timestamp_ok("2026-11-11T12:00:00+02:00"), "format")
    reject(lambda: mod.build({EU: ORIGINALS[EU]}, "qa-1"), "paired")
    reject(lambda: mod.build(ORIGINALS, "../bad-run"), "run_id")

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        out = root / "immutable-pair"
        result = mod.seal(out, ORIGINALS, "water4all-test-001")
        assert result == {"status": "PAIRED_RAW_REPLAY_VERIFIED_NON_AUTHORIZING",
                          "run_id": "water4all-test-001", "source_count": 2,
                          "publication_effect": "NONE", "open_call_authorized": False}
        assert mod.replay(out) == result
        reject(lambda: mod.seal(out, ORIGINALS, "again"), "immutable")
        raw = out / "raw" / f"{EU}.html"
        raw.write_bytes(EU_HTML + b"<p>tamper</p>")
        reject(lambda: mod.replay(out), "marker" if False else "mismatch")
        raw.write_bytes(EU_HTML)
        manifest = out / "handoff.json"
        clean = manifest.read_bytes()
        row = json.loads(clean)
        row["open_call_authorized"] = True
        row["handoff_sha256"] = mod.sha(mod.canonical({k: v for k, v in row.items() if k != "handoff_sha256"}))
        manifest.write_bytes(mod.canonical(row))
        reject(lambda: mod.replay(out), "mismatch")
        row = json.loads(clean)
        row["receipts"][0]["authority_class"] = "FORGED"
        row["handoff_sha256"] = mod.sha(mod.canonical({k: v for k, v in row.items() if k != "handoff_sha256"}))
        manifest.write_bytes(mod.canonical(row))
        reject(lambda: mod.replay(out), "mismatch")
        manifest.write_bytes(clean.replace(b'"schema":', b'"schema":"fake","schema":'))
        reject(lambda: mod.replay(out), "duplicate")
        manifest.write_bytes(clean)
        (out / "raw" / "unexpected.html").write_text("surprise")
        reject(lambda: mod.replay(out), "file-set")
        (out / "raw" / "unexpected.html").unlink()
        assert mod.replay(out) == result
    print("Water4All 2026 official paired immutable HTML acquisition/replay PASS; stage 2 not OPEN_CALL")


if __name__ == "__main__":
    run()
