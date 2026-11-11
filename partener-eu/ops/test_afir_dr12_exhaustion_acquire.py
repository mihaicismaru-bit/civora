#!/usr/bin/env python3
"""Hermetic adversarial DR-12 exhaustion original-byte capture, no publication."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))
import afir_dr12_exhaustion_acquire as notice  # noqa: E402

HTML = """
<html><head><title>AFIR</title></head><body>
<h2>Fondurile pentru componenta „alte sectoare” (DR-12) au fost epuizate</h2>
<p>11 noiembrie 2026, 08:48</p>
<article>
<p>Fondurile alocate prin intervenția DR-12 pentru componenta alte sectoare
au fost epuizate integral înainte de data limită a sesiunii (2 decembrie 2026).</p>
<p>Astfel, sesiunea pentru componenta alte sectoare din cadrul intervenției
DR-12 s-a închis din cauza depășirii plafonului de depunere.</p>
<p>Reamintim că sesiunea de depunere a solicitărilor de finanțare prin DR-12
continua pentru sectorul zootehnic până la termenul limită de 2 decembrie
2026 sau până la epuizarea fondurilor alocate.</p>
</article></body></html>
""".encode("utf-8")


def reject(fn, message=None):
    try:
        fn()
    except (ValueError, OSError) as exc:
        if message:
            assert message in str(exc), (message, str(exc))
    else:
        raise AssertionError("unverified DR-12 material observation admitted")


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test():
    notice.validate_official_notice(HTML, "text/html; charset=utf-8")
    assert notice.URL == (
        "https://www.afir.ro/comunicate/"
        "fondurile-pentru-componenta-alte-sectoare-dr-12-au-fost-epuizate/"
    )
    assert notice.NOTICE_PUBLISHED_AT_UTC.isoformat() == "2026-11-11T06:48:00+00:00"

    for raw in (
        HTML.replace("s-a închis".encode(), b"se poate deschide"),
        HTML.replace("alte sectoare".encode(), b"toate sectoarele"),
        HTML.replace("DR-12".encode(), b"DR-13"),
        HTML.replace("11 noiembrie 2026".encode(), b"10 noiembrie 2026"),
        HTML.replace("2 decembrie 2026".encode(), b"3 decembrie 2026"),
        HTML.replace("continua pentru sectorul zootehnic".encode(),
                     b"este inchisa si pentru sectorul zootehnic"),
        HTML.replace("sesiunea pentru componenta alte sectoare".encode(),
                     b"sesiunea pentru toate componentele"),
        HTML.replace(b"</article>",
                     b"<p>sectorul zootehnic s-a inchis</p></article>"),
    ):
        assert raw != HTML
        reject(lambda raw=raw: notice.validate_official_notice(raw, "text/html"))

    reject(lambda: notice.validate_official_notice(
        HTML, "application/json; note=text/html"), "not official HTML")
    reject(lambda: notice.validate_official_notice(
        HTML + b"x" * notice.MAX_BYTES, "text/html"), "raw size invalid")
    article = HTML.split(b"<body>", 1)[1].split(b"</body>", 1)[0]
    for opening, closing in (
        (b"<div hidden/>", b"</div>"),
        (b"<section aria-hidden='true'/>", b"</section>"),
        (b"<script/>", b"</script>"),
        (b"<template/>", b"</template>"),
        (b"<div style='display:none'/>", b"</div>"),
    ):
        hidden_only = (b"<html><body>" + opening + article + closing +
                       b"</body></html>")
        reject(lambda raw=hidden_only: notice.validate_official_notice(
            raw, "text/html"), "identity missing")
        visible_after_hidden = (b"<html><body>" + opening + article +
                                closing + article + b"</body></html>")
        notice.validate_official_notice(visible_after_hidden, "text/html")

    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp) / "receipt"
        manifest = notice.seal(out, HTML, "text/html; charset=utf-8",
                               now(), "PR-TEST-1")
        assert manifest["programme_family"] == "PS_PAC_2023_2027/DR12/ALTE_SECTOARE"
        assert manifest["observation_state"] == "RAW_VERIFIED_SEMANTIC_REVIEW_REQUIRED"
        for prop in notice.OFF:
            assert manifest[prop] is False
        assert notice.replay(out)["status"] == "RAW_NOTICE_REPLAY_VERIFIED_NOT_PUBLISHED"
        reject(lambda: notice.seal(out, HTML, "text/html", now(), "PR-TEST-2"),
               "File exists")
        original = (out / "manifest.json").read_text("utf-8")
        man_path = out / "manifest.json"
        for key, value in (
            ("open_call_authorized", True),
            ("publish_authorized", True),
            ("distribution_authorized", True),
            ("material_fact_use", True),
            ("observation_state", "CLOSED_CALL"),
            ("programme_family", "PS_PAC_2023_2027/DR12/SECTOR_ZOOTEHNIC"),
            ("authority_class", "T3_DISCOVERY"),
        ):
            modified = json.loads(original)
            modified[key] = value
            modified["handoff_sha256"] = notice.sha(notice.canonical({
                k: v for k, v in modified.items() if k != "handoff_sha256"
            }))
            man_path.write_text(json.dumps(modified), encoding="utf-8")
            reject(lambda: notice.replay(out), "authority/publication gate mismatch")
        modified = json.loads(original)
        modified["extra_authority"] = True
        man_path.write_text(json.dumps(modified), encoding="utf-8")
        reject(lambda: notice.replay(out), "schema mismatch")
        man_path.write_text(original.replace(
            '"publish_authorized": false',
            '"publish_authorized": true, "publish_authorized": false', 1
        ), encoding="utf-8")
        reject(lambda: notice.replay(out), "duplicate notice manifest key")
        man_path.write_text(original, encoding="utf-8")
        raw_path = out / notice.RAW_NAME
        raw_path.write_bytes(HTML + b"tamper")
        reject(lambda: notice.replay(out), "raw size mismatch")
        raw_path.write_bytes(HTML.replace(b"AFIR", b"AFRX", 1))
        reject(lambda: notice.replay(out), "original SHA mismatch")
        raw_path.write_bytes(HTML)
        assert notice.replay(out)["publish_authorized"] is False
        (out / "foreign.json").write_text("{}", encoding="utf-8")
        reject(lambda: notice.replay(out), "extra or missing evidence files")

    reject(lambda: notice._time("2026-11-11T06:47:59Z"),
           "predates official publication")
    notice._time("2026-11-11T06:48:00Z")
    reject(lambda: notice._time("2026-11-11T06:48:00+00:00"), "must be UTC")
    future = (dt.datetime.now(dt.timezone.utc) +
              dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    reject(lambda: notice._time(future), "in future")
    print("PASS AFIR DR12 other-sectors closure receipt: exact scope, immutable replay, no publication")


if __name__ == "__main__":
    test()
