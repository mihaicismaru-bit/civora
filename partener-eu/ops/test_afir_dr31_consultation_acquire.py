#!/usr/bin/env python3
"""DR-31 consultation stage: hermetic identity, fail-closed and immutable replay tests."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
import afir_dr31_consultation_acquire as mod  # noqa: E402

ARTICLE = b"""<html><body><main>
<h1>VERSIUNEA CONSULTATIVA a Ghidului solicitantului DR-31</h1>
<p>11 noiembrie 2026, 18:00 - Agentia pentru Finantarea Investitiilor Rurale.</p>
<p>Contributii financiare la plata primelor de asigurare.</p>
<p>A fost publicata pentru dezbatere publica versiunea consultativa a ghidului
solicitantului DR-31. Documentele aflate in consultare nu sunt lansarea
unei sesiuni de primire proiecte si nu confirma eligibilitatea sau bugetul.</p>
</main></body></html>"""
DEBATE = b"""<html><body><main>
<h1>Documente aflate in dezbatere publica</h1>
<p>Documentele si ghidurile consultative sunt publicate inaintea aprobarii
acestora prin Ordin pentru transparenta decizionala.</p>
<p>Ghid Solicitant DR 31 Consultativ - Contributii financiare la plata
primelor de asigurare. Perioada consultarii: 11.11.2026 - 02.12.2026.</p>
<p>Proiectul de ghid este disponibil pentru observatii si propuneri.
Acest interval reprezinta consultare, nu o sesiune de depunere.</p>
</main></body></html>"""
MIME = "text/html; charset=UTF-8"


def rejection(fn, message=None):
    try:
        fn()
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        if message:
            assert message in str(error), str(error)
    else:
        raise AssertionError("Unverified DR31 assertion or altered original admitted")


def originals():
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {mod.PRIMARY: (ARTICLE, MIME, stamp),
            mod.DEBATE: (DEBATE, MIME, stamp)}


def main():
    mod.registry_check()
    mod.validate(mod.PRIMARY, ARTICLE, MIME)
    mod.validate(mod.DEBATE, DEBATE, MIME)
    # Official CMS markup may interrupt a visible intervention title inline.
    inline_markup = ARTICLE.replace(
        b"Contributii financiare la plata primelor de asigurare.",
        b"Contributii <strong>financiare</strong> la plata <em>primelor</em> de asigurare.")
    mod.validate(mod.PRIMARY, inline_markup, MIME)
    rejection(lambda: mod.validate(mod.PRIMARY,
        ARTICLE.replace(b"primelor", b"ultimelor"), MIME),
        "intervention title")

    rejection(lambda: mod.validate(mod.PRIMARY,
        ARTICLE.replace(b"11 noiembrie 2026", b"12 noiembrie 2026"), MIME),
        "consultation source")
    rejection(lambda: mod.validate(mod.DEBATE,
        DEBATE.replace(b"11.11.2026 - 02.12.2026",
                       b"11.11.2026 - 12.12.2026"), MIME),
        "consultation source")
    rejection(lambda: mod.validate(mod.DEBATE, DEBATE,
        "application/json; text/html"), "MIME")
    rejection(lambda: mod.validate(mod.PRIMARY, b"not a document", MIME))

    # Hidden source identity/date cannot pass visible-HTML authority binding.
    for hidden in ("d-none", "d-md-none", "d-lg-none", "visually-hidden"):
        only_hidden = (b"<html><body><main><div class='" +
                       hidden.encode() + b"'>" + ARTICLE +
                       b"</div><p>Generic official home page. " + b"filler " * 55 +
                       b"</p></main></body></html>")
        rejection(lambda raw=only_hidden: mod.validate(mod.PRIMARY, raw, MIME))
    rejection(lambda: mod.validate(mod.PRIMARY,
        ARTICLE.replace(b"<main>", b"<main style='display:none'>"), MIME))
    rejection(lambda: mod.validate(mod.PRIMARY,
        ARTICLE.replace(b"<main>", b"<main hidden/>"), MIME))
    rejection(lambda: mod.validate(mod.PRIMARY,
        ARTICLE.replace(b"<main>", b"<main class='d-lg-none'>"), MIME))
    rejection(lambda: mod.validate(mod.PRIMARY,
        ARTICLE.replace(b"<main>", b"<main aria-hidden='true'>"), MIME))
    rejection(lambda: mod.validate(mod.PRIMARY,
        ARTICLE.replace(b"<main>", b"<main class='visible' class='d-none'>"), MIME))

    # A consultation source must remain non-authorizing even with valid SHA.
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        pair = base / "pair"
        manifest = mod.seal(pair, originals(), "dr31-test-1")
        assert manifest["pending_source_ids"] == []
        assert len(manifest["receipts"]) == 2
        assert mod.replay(pair)["status"] == "DR31_CONSULTATION_PAIR_RAW_REPLAY_VERIFIED"
        assert manifest["observation_state"] == "PROGRAMMING_PIPELINE"
        assert manifest["consultation_state"] == "CONSULTATION"
        for key in mod.OFF:
            assert manifest[key] is False
            assert all(row[key] is False for row in manifest["receipts"])
        rejection(lambda: mod.seal(pair, originals(), "dr31-test-1"))

        original_manifest = (pair / "manifest.json").read_bytes()
        compromised = mod.strict(original_manifest)
        compromised["open_call_authorized"] = True
        compromised["handoff_sha256"] = mod.sha(mod.canonical({
            k: v for k, v in compromised.items() if k != "handoff_sha256"}))
        (pair / "manifest.json").write_bytes(mod.canonical(compromised))
        rejection(lambda: mod.replay(pair), "replay")
        (pair / "manifest.json").write_bytes(original_manifest)

        path = pair / ("raw-" + mod.PRIMARY + ".html")
        orig = path.read_bytes()
        path.write_bytes(orig + b"<!-- altered -->")
        rejection(lambda: mod.replay(pair), "modified")
        path.write_bytes(orig)
        assert mod.replay(pair)["open_call_authorized"] is False

        only = base / "article_only"
        partial = {mod.PRIMARY: originals()[mod.PRIMARY]}
        m = mod.seal(only, partial, "dr31-test-2")
        assert m["pending_source_ids"] == [mod.DEBATE]
        assert mod.replay(only)["status"] == "DR31_ARTICLE_RAW_REPLAY_VERIFIED_DEBATE_PENDING"
        assert mod.replay(only)["publish_authorized"] is False

        rejection(lambda: mod.seal(base / "missing", {
            mod.DEBATE: originals()[mod.DEBATE]}, "dr31-test-3"),
            "announcement original required")
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(
            microsecond=0).isoformat().replace("+00:00", "Z")
        rejection(lambda: mod.build({
            mod.PRIMARY: (ARTICLE, MIME, future)}, "dr31-test-4"), "future")
        past = (mod.PUBLISHED_UTC - timedelta(seconds=1)).isoformat(
            timespec="seconds").replace("+00:00", "Z")
        rejection(lambda: mod.build({
            mod.PRIMARY: (ARTICLE, MIME, past)}, "dr31-test-5"),
            "predates publication")
        rejection(lambda: mod.strict(b'{"schema":"one","schema":"two"}'), "duplicate")
        rejection(lambda: mod.strict(b'{"schema":NaN}'), "non-finite")
    print(json.dumps({"ok": True, "status": "DR31_CONSULTATION_ONLY_REPLAY_VERIFIED",
                      "open_call_authorized": False, "publication_effect": "NONE"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
