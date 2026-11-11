#!/usr/bin/env python3
"""Hermetic negative tests for immutable THCS JTC 2027 pre-launch pair."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
import thcs_2027_preannouncement_pair as mod  # noqa: E402

E = b"""<html><body><main><h1>JTC 2027 - Pre-announcement</h1>
<p>Transforming the Health and Care Workforce for Sustainable and Resilient Systems</p>
<p>The fifth Joint Transnational Call will launch 16 November 2026.</p>
<p>January 21, 2027 | Deadline for submission of pre-proposal</p>
<p>June 24, 2027 | Deadline for full-proposals</p></main></body></html>"""
R = """<html><body><main><h1>Transforming Health and Care Systems</h1>
<section><h2>THCS-2027</h2><p>Lansare apel: 16 noiembrie 2026</p>
<p>Termen pre-propuneri: 21 ianuarie 2027, ora 14:00 CET</p>
<p>Termen propuneri finale: 24 iunie 2027, ora 14:00 CEST</p>
<p>THCS 2027 pregateste transformarea sistemelor de sanatate.</p></section>
</main></body></html>""".encode()
MIME = "text/html; charset=utf-8"
SID_E, SID_RO = sorted(mod.SOURCE_SPECS)

def reject(fn, fragment=None):
    try:
        fn()
    except (ValueError, FileExistsError) as e:
        if fragment:
            assert fragment in str(e), str(e)
    else:
        raise AssertionError("unverified programming fact admitted")

def originals():
    t = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {SID_E: (E, MIME, t), SID_RO: (R, MIME, t)}

def test():
    mod.validate_html(SID_E, E, MIME)
    mod.validate_html(SID_RO, R, MIME)
    mod.validate_registry()
    reject(lambda: mod.validate_html(SID_E, E.replace(b"16 November", b"19 November"), MIME), "markers")
    reject(lambda: mod.validate_html(SID_RO, R.replace(b"THCS-2027", b"THCS-2026"), MIME), "markers")
    reject(lambda: mod.validate_html(SID_E, E, "application/pdf; file=text/html"), "MIME")
    for sid, raw in ((SID_E, E), (SID_RO, R)):
        hidden = b"<html><body><section hidden>" + raw.split(b"<main>")[1].split(b"</main>")[0] + b"</section></body></html>"
        reject(lambda sid=sid, hidden=hidden: mod.validate_html(sid, hidden, MIME), "markers")
        visible_after = hidden.replace(b"</body>", b"<div>" + raw.split(b"<main>")[1].split(b"</main>")[0] + b"</div></body>")
        mod.validate_html(sid, visible_after, MIME)
    reject(lambda: mod.exact_url(SID_E, mod.SOURCE_SPECS[SID_E]["url"] + "?stale=1"), "URL")
    reject(lambda: mod.exact_url(SID_RO, "https://evil.invalid/"), "URL")
    reject(lambda: mod.build({SID_E: originals()[SID_E]}, "T1"), "both")
    reject(lambda: mod.build(originals(), "BAD/ID"), "run_id")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "evidence"
        manifest = mod.seal(d, originals(), "PR-HERMETIC-THCS-1")
        assert manifest["observation_state"] == "PROGRAMMING_PIPELINE"
        assert all(manifest[x] is False for x in mod.OFF)
        status = mod.replay(d)
        assert status["status"] == "THCS_PREANNOUNCEMENT_PAIR_RAW_REPLAY_VERIFIED"
        assert status["open_call_authorized"] is False
        reject(lambda: mod.seal(d, originals(), "PR-HERMETIC-THCS-2"), "exists")
        original_manifest = (d / "manifest.json").read_bytes()
        for key, value in (("open_call_authorized", True),
                           ("observation_state", "OPEN_CALL"),
                           ("publication_effect", "PUBLISH")):
            forged = json.loads(original_manifest)
            forged[key] = value
            forged["handoff_sha256"] = mod.sha(mod.canonical({
                k: v for k, v in forged.items() if k != "handoff_sha256"}))
            (d / "manifest.json").write_bytes(mod.canonical(forged))
            reject(lambda: mod.replay(d), "gate")
        (d / "manifest.json").write_bytes(original_manifest)
        (d / ("raw-" + SID_E + ".html")).write_bytes(E + b"tamper")
        reject(lambda: mod.replay(d), "SHA/size")
        (d / ("raw-" + SID_E + ".html")).write_bytes(E)
        (d / "foreign.json").write_text("{}")
        reject(lambda: mod.replay(d), "extra/missing")
        (d / "foreign.json").unlink()
        (d / "manifest.json").write_bytes(original_manifest.replace(
            b'"run_id":"PR-HERMETIC-THCS-1"',
            b'"run_id":"OTHER","run_id":"PR-HERMETIC-THCS-1"', 1))
        reject(lambda: mod.replay(d), "duplicate")
        (d / "manifest.json").write_bytes(original_manifest)
        assert mod.replay(d)["publish_authorized"] is False
        linked = Path(tmp) / "symlink"
        linked.symlink_to(d, target_is_directory=True)
        reject(lambda: mod.replay(linked), "symlinked")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    reject(lambda: mod.timestamp(future), "bounds")
    print("PASS THCS 2027 paired preannouncement immutable replay; no OPEN_CALL")

if __name__ == "__main__":
    test()
