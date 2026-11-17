#!/usr/bin/env python3
"""Hermetic fail-closed regression for UEFISCDI THCS planning index evidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
import thcs_2027_national_index as mod  # noqa: E402
import thcs_2027_preannouncement_pair as core  # noqa: E402

MIME = "text/html; charset=utf-8"
BASE = """<html><body><main>
<h2>Competiții deschise</h2><ul><li>ERA4Health IICS4all 2027</li></ul>
<h2>Competiții în pregătire</h2><ul>
<li>Transforming Health and Care Systems (THCS) Lansare: 16 Noiembrie 2026</li>
<li>ERA4Health NanoDiagNCD2027 Lansare: 17 Noiembrie 2026</li></ul>
<h2>Competiții închise</h2><ul><li>THCS-2026</li></ul>
</main></body></html>"""
# A historical closed THCS-2026 may appear in the list; it must not be confused
# with THCS-2027. Live case: only exact THCS-2027 identity is stage-sensitive.
RAW = BASE.replace("<li>THCS-2026</li>", "<li>AgData-2026</li>").encode()


def reject(fn, message):
    try:
        fn()
    except (ValueError, FileExistsError) as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError("unsafe official-source evidence accepted")


def test():
    mod.validate_registry()
    mod.validate_html(RAW, MIME)
    # Historical THCS-2026 is allowed; exact THCS-2027 in any other
    # lifecycle section must quarantine the index rather than validate it.
    mod.validate_html(BASE.encode(), MIME)
    for conflicting in (
        RAW.replace(b"ERA4Health IICS4all 2027", b"THCS-2027"),
        RAW.replace(b"ERA4Health IICS4all 2027", b"THCS 2027"),
        RAW.replace(b"AgData-2026", b"THCS-2027"),
        RAW.replace(b"AgData-2026", b"Transforming Health and Care Systems (THCS)"),
    ):
        reject(lambda h=conflicting: mod.validate_html(h, MIME), "outside planned lifecycle")
    bad = [
        (RAW.replace(b"16 Noiembrie", b"19 Noiembrie"), "exact THCS"),
        (RAW.replace(b"Competi\xc8\x9bii \xc3\xaen preg\xc4\x83tire",
                     b"Competitii viitoare"), "lifecycle"),
        (RAW.replace(b"Competi\xc8\x9bii \xc3\xaenchise", b"Apeluri vechi"),
         "lifecycle"),
        (RAW.replace(b"Transforming Health and Care Systems (THCS)",
                     b"Transforming Healthcare 2027"), "exact THCS"),
    ]
    for html, why in bad:
        reject(lambda html=html: mod.validate_html(html, MIME), why)
    for css in ("hidden", 'class="d-md-none"', 'style="display:none"',
                'aria-hidden="true"', 'class="visually-hidden"',
                'class="collapse"', 'class="collapsing"',
                'class="tab-pane"'):
        tag = "<div " + css + ">" if css == "hidden" else "<div " + css + ">"
        hidden = (RAW.decode().replace(
            "<li>Transforming Health and Care Systems (THCS) Lansare: 16 Noiembrie 2026</li>",
            tag + "<li>Transforming Health and Care Systems (THCS) Lansare: 16 Noiembrie 2026</li></div>")).encode()
        reject(lambda h=hidden: mod.validate_html(h, MIME), "exact THCS")
    for css in ('class="collapse show"', 'class="tab-pane active"'):
        expanded = RAW.decode().replace(
            "<li>Transforming Health and Care Systems (THCS) Lansare: 16 Noiembrie 2026</li>",
            "<div " + css + "><li>Transforming Health and Care Systems (THCS) "
            "Lansare: 16 Noiembrie 2026</li></div>").encode()
        mod.validate_html(expanded, MIME)
    reject(lambda: mod.validate_html(RAW, "application/pdf"), "MIME")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest = mod.build(RAW, MIME, stamp, "THCS-INDEX-HERMETIC")
    assert manifest["observation_state"] == "PROGRAMMING_PIPELINE"
    assert all(manifest[k] is False for k in mod.OFF)
    # Index transition can be semantically unverified while RAW/transport remain
    # genuine; retention and replay must still work without stage promotion.
    unknown = RAW.replace(b"16 Noiembrie", b"19 Noiembrie")
    quarantined = mod.build(unknown, MIME, stamp, "THCS-INDEX-DRIFT")
    assert quarantined["source_identity_verified"] is False
    assert quarantined["observation_state"] == "NATIONAL_INDEX_RAW_QUARANTINED"
    assert quarantined["unverified_reason_code"] == "VISIBLE_LIFECYCLE_OR_THCS_IDENTITY_UNVERIFIED"
    assert all(quarantined[k] is False for k in mod.OFF)
    with tempfile.TemporaryDirectory() as tmp:
        badfolder = Path(tmp) / "drifted-official-original"
        mod.seal(badfolder, unknown, MIME, stamp, "THCS-INDEX-DRIFT")
        quarantined_replay = mod.replay(badfolder)
        assert quarantined_replay["status"] == "THCS_INDEX_RAW_QUARANTINED_REPLAY_VERIFIED_NO_SEMANTIC_AUTHORITY"
        assert quarantined_replay["source_identity_verified"] is False
        forged = json.loads((badfolder / "manifest.json").read_bytes())
        forged["source_identity_verified"] = True
        forged["observation_state"] = "PROGRAMMING_PIPELINE"
        forged["unverified_reason_code"] = None
        forged["handoff_sha256"] = core.sha(core.canonical({
            k:v for k,v in forged.items() if k != "handoff_sha256"}))
        (badfolder / "manifest.json").write_bytes(core.canonical(forged))
        reject(lambda: mod.replay(badfolder), "semantic replay drift")
        folder = Path(tmp) / "immutable"
        mod.seal(folder, RAW, MIME, stamp, "THCS-INDEX-HERMETIC")
        status = mod.replay(folder)
        assert status["status"].endswith("DISCOVERY_ONLY")
        assert status["national_detail_verified"] is False
        reject(lambda: mod.seal(folder, RAW, MIME, stamp, "DUPLICATE"), "exists")
        (folder / mod.RAW_NAME).write_bytes(RAW + b"tamper")
        reject(lambda: mod.replay(folder), "SHA/size")
        (folder / mod.RAW_NAME).write_bytes(RAW)
        initial = (folder / "manifest.json").read_bytes()
        obj = json.loads(initial)
        obj["open_call_authorized"] = True
        obj["handoff_sha256"] = core.sha(core.canonical({
            k:v for k,v in obj.items() if k != "handoff_sha256"}))
        (folder / "manifest.json").write_bytes(core.canonical(obj))
        reject(lambda: mod.replay(folder), "authority gate")
        (folder / "manifest.json").write_bytes(initial)
        (folder / "alien.txt").write_text("other")
        reject(lambda: mod.replay(folder), "extra or missing")
        (folder / "alien.txt").unlink()
        (folder / "manifest.json").write_bytes(initial.replace(
            b'"run_id":"THCS-INDEX-HERMETIC"',
            b'"run_id":"OTHER","run_id":"THCS-INDEX-HERMETIC"', 1))
        reject(lambda: mod.replay(folder), "duplicate")
        linked = Path(tmp) / "symlink"
        linked.symlink_to(folder, target_is_directory=True)
        reject(lambda: mod.replay(linked), "symlinked")
    # 17 Nov 2026 exact live stage: operator JTC2027 call and EPSS exist,
    # but this registry is evidence only; legacy pre-announcement is NOT open.
    import urllib.parse
    registry = json.loads(core.REGISTRY.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in registry["sources"]}
    launched = "SRC-EU-THCS-JTC2027-LAUNCH"
    call_text = "SRC-EU-THCS-JTC2027-CALL-TEXT-V1"
    epss = "SRC-EU-THCS-JTC2027-EPSS-EXACT"
    expected_urls = {
        launched: "https://www.thcspartnership.eu/funding/jtc-2027.kl",
        call_text: "https://www.thcspartnership.eu/kdocs/2254775/thcs-jtc-2027-call-text-v1.0-02.pdf",
        epss: "https://epss.proposals.ee/thcs/2027",
    }
    for sid, url in expected_urls.items():
        r = by_id[sid]
        assert r["url"] == url
        assert urllib.parse.urlsplit(url).scheme == "https"
        assert r["exact_call_identifier_discovery"] == "THCS2027 / fifth JTC 2027"
        assert r["programme_family"] == "Horizon Europe / THCS Joint Transnational Call 2027"
        assert r["readback_date_discovery"] == "2026-11-17"
        assert r["authority_scope"].endswith("DISCOVERY_ONLY")
        assert r["observation_state"] != "OPEN_CALL"
        for gate in ("material_fact_use", "open_call_authorized", "material_fact_publication_authorized"):
            assert r[gate] is False
        assert "RAW_PENDING" in r["observation_state"]
    assert by_id[launched]["paired_official_source_id"] == "SRC-RO-UEFISCDI-THCS-2027"
    assert by_id[launched]["supersedes_preannouncement_source_id"] == "SRC-EU-THCS-2027-PREANNOUNCEMENT"
    assert by_id["SRC-EU-THCS-2027-PREANNOUNCEMENT"]["observation_state"] == "PROGRAMMING_PIPELINE"
    assert by_id["SRC-RO-UEFISCDI-THCS-2027"]["observation_state"] == "PROGRAMMING_PIPELINE"
    assert "Annex 1.24 Romania" in by_id[call_text]["note"]
    assert "EPSS" in by_id[epss]["note"]
    # UEFISCDI index moved the 2027 edition into OPEN; do not let the
    # old planned-only raw extractor silently accept this as either stage.
    moved = RAW.decode().replace(
        "<li>Transforming Health and Care Systems (THCS) Lansare: 16 Noiembrie 2026</li>", ""
    ).replace("<li>ERA4Health IICS4all 2027</li>",
              "<li>ERA4Health IICS4all 2027</li><li>Transforming Health and Care Systems (THCS)</li>").encode()
    reject(lambda: mod.validate_html(moved, MIME), "outside planned lifecycle")
    moved_manifest = mod.build(moved, MIME, stamp, "THCS-JTC2027-NATIONAL-INDEX-TRANSITION")
    assert moved_manifest["source_identity_verified"] is False
    assert moved_manifest["observation_state"] == "NATIONAL_INDEX_RAW_QUARANTINED"
    assert all(moved_manifest[k] is False for k in mod.OFF)
    print("PASS UEFISCDI exact planned index raw/replay; detail quarantine preserved")


if __name__ == "__main__":
    test()
