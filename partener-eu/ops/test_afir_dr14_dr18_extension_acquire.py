#!/usr/bin/env python3
"""Offline adversarial contract for AFIR notice original-byte acquisition/replay."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))
import afir_dr14_dr18_extension_acquire as notice  # noqa: E402

HTML = ("""
<!doctype html><html><head><title>AFIR</title></head><body>
<h1>Prelungire sesiune depunere proiecte de investiții aferente DR-14 si DR-18</h1>
<div>30 octombrie 2026, 11:40</div>
<article>
<p>Sesiunile de primire a cererilor de finanțare pentru DR-14 și DR-18
rămân deschise până la 16 noiembrie, ora 16:00.</p>
<p>Prelungirea depunerii de la 31 octombrie la 16 noiembrie 2026
se aplică exclusiv componentelor pentru care mai sunt fonduri disponibile
– astfel, nu se prelungește depunerea și pentru componenta Achiziții simple,
pentru care fondurile disponibile s-au epuizat în data de 6 octombrie.</p>
</article></body></html>
""").encode("utf-8")


def reject(fn, expected):
    try:
        fn()
    except (ValueError, OSError) as exc:
        assert expected in str(exc), (expected, str(exc))
    else:
        raise AssertionError(f"unsafe AFIR notice admitted: {expected}")


def fixture():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test():
    notice.validate_official_notice(HTML, "text/html; charset=utf-8")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        notice.seal(root, HTML, "text/html; charset=utf-8", fixture(), "TEST-1")
        result = notice.replay(root)
        assert result["status"] == "RAW_NOTICE_REPLAY_VERIFIED_NOT_PUBLISHED"
        assert result["publish_authorized"] is False
        assert result["open_call_authorized"] is False
        reject(lambda: notice.seal(root, HTML, "text/html", fixture(), "TEST-1"), "File exists")
        raw = root / notice.RAW_NAME
        raw.write_bytes(HTML + b"<!-- tampered -->")
        reject(lambda: notice.replay(root), "original SHA mismatch")
        raw.write_bytes(HTML)
        manifest_path = root / "manifest.json"
        original = manifest_path.read_text("utf-8")
        parsed = json.loads(original)
        parsed["publish_authorized"] = True
        parsed["handoff_sha256"] = notice.sha(notice.canonical({
            k: v for k, v in parsed.items() if k != "handoff_sha256"}))
        manifest_path.write_text(json.dumps(parsed), encoding="utf-8")
        reject(lambda: notice.replay(root), "authority/publication gate mismatch")
        parsed = json.loads(original)
        parsed["open_call_authorized"] = True
        parsed["handoff_sha256"] = notice.sha(notice.canonical({
            k: v for k, v in parsed.items() if k != "handoff_sha256"}))
        manifest_path.write_text(json.dumps(parsed), encoding="utf-8")
        reject(lambda: notice.replay(root), "authority/publication gate mismatch")
        parsed = json.loads(original)
        parsed["distribution_authorized"] = True
        parsed["handoff_sha256"] = notice.sha(notice.canonical({
            k: v for k, v in parsed.items() if k != "handoff_sha256"}))
        manifest_path.write_text(json.dumps(parsed), encoding="utf-8")
        reject(lambda: notice.replay(root), "authority/publication gate mismatch")
        parsed = json.loads(original)
        parsed["extra_authority"] = "YES"
        manifest_path.write_text(json.dumps(parsed), encoding="utf-8")
        reject(lambda: notice.replay(root), "schema mismatch")
        manifest_path.write_text(original.replace(
            '"publish_authorized": false', '"publish_authorized": false, "publish_authorized": true'
        ), encoding="utf-8")
        reject(lambda: notice.replay(root), "duplicate notice manifest key")
        manifest_path.write_text(original, encoding="utf-8")
        assert notice.replay(root)["status"] == "RAW_NOTICE_REPLAY_VERIFIED_NOT_PUBLISHED"
        (root / "extra.json").write_text("{}", encoding="utf-8")
        reject(lambda: notice.replay(root), "extra or missing evidence files")

    invalid_html = (
        HTML.replace(b"nu se prelunge", b"se prelunge") ,
        HTML.replace(b"16 noiembrie 2026", b"31 octombrie 2026"),
        HTML.replace(b"6 octombrie", b"8 octombrie"),
        HTML.replace(b"DR-18", b"DR-19"),
        b"<html><head><h1>Prelungire DR-14 DR-18</h1></head></html>"
    )
    for wrong in invalid_html:
        reject(lambda wrong=wrong: notice.validate_official_notice(wrong, "text/html"),
               "notice identity or conditional scope missing" if
               b"nu se prelung" not in wrong or b"DR-18" not in wrong or b"16 noiembrie 2026" not in wrong or
               b"6 octombrie" not in wrong or b"<head><h1>" in wrong else
               "exhausted component exclusion not proven")
    reject(lambda: notice.validate_official_notice(HTML, "application/json; note=html"),
           "not official HTML")
    reject(lambda: notice.validate_official_notice(HTML + b"x" * notice.MAX_BYTES, "text/html"),
           "raw size invalid")
    reject(lambda: notice._time("2026-11-09T03:00:00+00:00"), "must be UTC")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    reject(lambda: notice._time(future), "in future")
    print("PASS AFIR DR14/DR18 notice: raw fingerprint, exact provenance, conditional scope, no OPEN/publication")


if __name__ == "__main__":
    test()
