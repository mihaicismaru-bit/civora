#!/usr/bin/env python3
"""Hermetic counter-pair tests; synthetic figures are NOT live funding facts."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from unittest import mock
from copy import deepcopy
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))
probe = importlib.import_module("afir_counter_pair_watch")


def agency(zoo=65, other=578, funds="-"):
    return (f"""<!doctype html><html><body><table>
<tr><th>Intervenția</th><th>Sector</th><th>Allocation</th><th>Start</th>
<th>End</th><th>Ceiling</th><th>Value</th><th>Count</th><th>Funds</th></tr>
<tr><td>DR-12</td><td>Componenta SECTOR ZOOTEHNIC</td><td>84.794.823,50 EUR</td>
<td>06.10.2026 09:00:00</td><td>02.12.2026 15:59:59</td><td>-</td><td>12.523.748</td><td>{zoo}</td><td>{funds}</td></tr>
<tr><td>DR-12</td><td>Componenta ALTE SECTOARE</td><td>84.794.823,50 EUR</td>
<td>06.10.2026 09:00:00</td><td>02.12.2026 15:59:59</td><td>-</td><td>107.470.146</td><td>{other}</td><td>{funds}</td></tr>
</table></body></html>""").encode()


def delegated(zoo=65, other=578, funds="-"):
    return (f"""<!doctype html><html><body>
<h1>Fonduri alocate sesiunilor active</h1>
<div>Sesiune depunere dosare de finanțare DR-12 DATĂ ÎNCEPUT 06/10/2026 09:00:00
 | DATĂ FINAL 02/12/2026 15:59:59</div>
<div>DESCRIERE ALOCARE
 <b>DR-12</b><span>Investiții în consolidarea exploatațiilor - Componenta SECTOR ZOOTEHNIC</span>
 DATĂ ȘI ORĂ LANSARE 06/10/2026 09:00:00
 ALOCARE FINANCIARĂ 84794823.50000
 DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59
 PLAFON DEPUNERE -
 VALOAREA PROIECTELOR DEPUSE *1 12523748.00000
 NUMĂR DOSARE DEPUSE {zoo}
 FONDURI DISPONIBILE *2 {funds}
</div><div>DESCRIERE ALOCARE
 <b>DR-12</b><span>Investiții în consolidarea exploatațiilor - Componenta ALTE SECTOARE</span>
 DATĂ ȘI ORĂ LANSARE 06/10/2026 09:00:00
 ALOCARE FINANCIARĂ 84794823.50000
 DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59
 PLAFON DEPUNERE -
 VALOAREA PROIECTELOR DEPUSE *1 107470146.00000
 NUMĂR DOSARE DEPUSE {other}
 FONDURI DISPONIBILE *2 {funds}
</div></body></html>""").encode()


def fetches(a=None, b=None, hours=0):
    return {
        "agency": {
            "ok": True, "url": probe.AGENCY_URL, "status": 200,
            "content_type": "text/html; charset=utf-8",
            "content_encoding": "identity",
            "fetched_at_utc": "2026-11-06T01:00:00Z", "data": agency() if a is None else a,
        },
        "delegated": {
            "ok": True, "url": probe.DELEGATED_URL, "status": 200,
            "content_type": "text/html; charset=utf-8",
            "content_encoding": "identity",
            "fetched_at_utc": "2026-11-06T01:00:12Z" if hours == 0 else "2026-11-06T01:03:00Z",
            "data": delegated() if b is None else b,
        },
    }


def reject(fn):
    try:
        fn()
    except (ValueError, KeyError, FileNotFoundError):
        return
    raise AssertionError("counter source mutation unexpectedly accepted")


def test_parse_and_reconcile():
    data = fetches()
    a, b = probe.parse_agency(data["agency"]["data"]), probe.parse_delegated(data["delegated"]["data"])
    assert a["SECTOR ZOOTEHNIC"]["submitted_count"] == b["SECTOR ZOOTEHNIC"]["submitted_count"] == 65
    assert a["ALTE SECTOARE"]["submitted_count"] == b["ALTE SECTOARE"]["submitted_count"] == 578
    assert probe.reconcile({"agency": agency(), "delegated": delegated()}, 12)["observation_state"] == "SOURCE_COUNTER_FUNDS_WITHHELD_REVIEW"
    assert probe.reconcile({"agency": agency(), "delegated": delegated(zoo=66)}, 12)["observation_state"] == "SOURCE_COUNTER_DIVERGENCE_REVIEW"
    assert probe.reconcile({"agency": agency(), "delegated": delegated()}, 150)["observation_state"] == "SOURCE_COUNTER_CAPTURE_SKEW_REVIEW"
    assert probe.reconcile({"agency": agency(funds="100,00 EUR"), "delegated": delegated(funds="100.00000")}, 12)["observation_state"] == "SOURCE_COUNTER_PAIR_MATCH_REVIEW"
    assert probe.reconcile({"agency": agency(funds="100,00 EUR"), "delegated": delegated(funds="99.00000")}, 12)["observation_state"] == "SOURCE_COUNTER_DIVERGENCE_REVIEW"
    assert probe.reconcile({"agency": agency(), "delegated": b"<html>DR-12</html>"}, 12)["observation_state"] == "SOURCE_COUNTER_PARSE_REVIEW"
    assert probe.reconcile({"agency": agency(other=580), "delegated": delegated()}, 12)["observation_state"] == "SOURCE_COUNTER_DIVERGENCE_REVIEW"
    reject(lambda: probe.parse_agency(agency().replace(b"</table>", agency()[agency().find(b"<tr><td>DR-12"):agency().find(b"</table>")] + b"</table>")))
    reject(lambda: probe.parse_delegated(delegated().replace("NUMĂR".encode("utf-8"), b"COUNT")))
    reject(lambda: probe.parse_delegated(delegated().replace(b"ALTE SECTOARE", b"UNKNOWN COMPONENT")))
    # A valid-looking component card cannot overrule the delegated session banner.
    # All values here are synthetic hermetic fixtures, not live funding facts.
    original = delegated()
    changed_header = original.replace(
        "DATĂ FINAL 02/12/2026 15:59:59".encode("utf-8"),
        "DATĂ FINAL 03/12/2026 15:59:59".encode("utf-8"),
    )
    assert changed_header != original
    parsed_header = probe.parse_delegated(changed_header)
    assert all(not row["session_window_matches"] for row in parsed_header.values())
    assert parsed_header["ALTE SECTOARE"]["session_closes_at"] == "03.12.2026 15:59:59"
    assert probe.reconcile({"agency": agency(), "delegated": changed_header}, 12)["observation_state"] == "SOURCE_COUNTER_DIVERGENCE_REVIEW"

    changed_component = original.replace(
        "DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59".encode("utf-8"),
        "DATĂ ȘI ORĂ ÎNCHIDERE 03/12/2026 15:59:59".encode("utf-8"),
        1,
    )
    assert changed_component != original
    parsed_component = probe.parse_delegated(changed_component)
    assert parsed_component["SECTOR ZOOTEHNIC"]["session_window_matches"] is False
    assert parsed_component["ALTE SECTOARE"]["session_window_matches"] is True
    reconciled = probe.reconcile({"agency": agency(), "delegated": changed_component}, 12)
    assert reconciled["observation_state"] == "SOURCE_COUNTER_DIVERGENCE_REVIEW"
    assert reconciled["components"]["SECTOR ZOOTEHNIC"]["delegated_session_window_matches"] is False
    assert reconciled["material_fact_action"] == "NONE"
    # Invalid dates and reversed windows are NOT legitimate source discrepancies.
    reject(lambda: probe.parse_delegated(original.replace(
        "DATĂ FINAL 02/12/2026 15:59:59".encode("utf-8"),
        "DATĂ FINAL 32/12/2026 15:59:59".encode("utf-8"), 1,
    )))
    reject(lambda: probe.parse_delegated(original.replace(
        "DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59".encode("utf-8"),
        "DATĂ ȘI ORĂ ÎNCHIDERE 05/10/2026 15:59:59".encode("utf-8"), 1,
    )))

    extra_header = (
        "<div>Sesiune depunere dosare de finanțare DR-12 "
        "DATĂ ÎNCEPUT 06/10/2026 09:00:00 "
        "DATĂ FINAL 02/12/2026 15:59:59</div>"
    ).encode("utf-8")
    duplicate_session = original.replace(b"</body>", extra_header + b"</body>")
    assert duplicate_session != original
    reject(lambda: probe.parse_delegated(duplicate_session))
    # A contradictory DR-12 session whose date label is malformed must not be
    # silently ignored just because the original well-formed banner still matches.
    malformed_banner = (
        "<div>Sesiune depunere dosare de finanțare DR-12 "
        "DATĂ ÎNCEPUT 07/10/2026 09:00:00 "
        "DATĂ FINALĂ 03/12/2026 15:59:59</div>"
    ).encode("utf-8")
    conflicting_unparseable = original.replace(b"</body>", malformed_banner + b"</body>")
    assert conflicting_unparseable != original
    reject(lambda: probe.parse_delegated(conflicting_unparseable))
    assert probe.reconcile(
        {"agency": agency(), "delegated": conflicting_unparseable}, 12
    )["observation_state"] == "SOURCE_COUNTER_PARSE_REVIEW"
    # A valid first count/amount/date must not mask a second conflicting
    # material label in the SAME delegated DR-12 card. All numbers are
    # synthetic hermetic values and never funding facts.
    for original_text, duplicate_text in (
        ("NUMĂR DOSARE DEPUSE 65", "NUMĂR DOSARE DEPUSE 65 NUMĂR DOSARE DEPUSE 999"),
        ("ALOCARE FINANCIARĂ 84794823.50000",
         "ALOCARE FINANCIARĂ 84794823.50000 ALOCARE FINANCIARĂ 1.00000"),
        ("FONDURI DISPONIBILE *2 -",
         "FONDURI DISPONIBILE *2 - FONDURI DISPONIBILE *2 999.00000"),
        ("DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59",
         "DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59 "
         "DATĂ ȘI ORĂ ÎNCHIDERE 03/12/2026 15:59:59"),
        ("Componenta SECTOR ZOOTEHNIC",
         "Componenta SECTOR ZOOTEHNIC Componenta ALTE SECTOARE"),
    ):
        altered = original.replace(
            original_text.encode("utf-8"), duplicate_text.encode("utf-8"), 1
        )
        assert altered != original
        reject(lambda altered=altered: probe.parse_delegated(altered))
        assert probe.reconcile(
            {"agency": agency(), "delegated": altered}, 12
        )["observation_state"] == "SOURCE_COUNTER_PARSE_REVIEW"

    # Also accept the historical portal rendering without the date pipe.
    without_separator = original.replace(
        "| DATĂ FINAL 02/12/2026 15:59:59".encode("utf-8"),
        "DATĂ FINAL 02/12/2026 15:59:59".encode("utf-8"),
    )
    assert without_separator != original
    assert probe.parse_delegated(without_separator)["SECTOR ZOOTEHNIC"]["submitted_count"] == 65

    # Footnote *1 is permitted only as an exact label, never treated as a value.
    no_footnote = original.replace(
        "VALOAREA PROIECTELOR DEPUSE *1 ".encode("utf-8"),
        "VALOAREA PROIECTELOR DEPUSE ".encode("utf-8"),
    )
    assert no_footnote != original
    assert probe.parse_delegated(no_footnote)["ALTE SECTOARE"]["submitted_count"] == 578
    wrong_footnote = original.replace(
        "VALOAREA PROIECTELOR DEPUSE *1 ".encode("utf-8"),
        "VALOAREA PROIECTELOR DEPUSE *2 ".encode("utf-8"),
        1,
    )
    assert wrong_footnote != original
    reject(lambda: probe.parse_delegated(wrong_footnote))



def test_hidden_counter_dom_fail_closed():
    """Invisible or inert DOM cannot act as official DR-12 counter proof."""
    real = delegated()
    forged_banner = (
        "Sesiune depunere dosare de finanțare DR-12 "
        "DATĂ ÎNCEPUT 06/10/2026 09:00:00 "
        "DATĂ FINAL 30/12/2026 15:59:59"
    )
    hiding = (
        ("div hidden", "div"),
        ("div hidden='false'", "div"),
        ("div popover='manual'", "div"),
        ("div aria-hidden='true'", "div"),
        ("div class='d-none'", "div"),
        ("div style='display:none'", "div"),
        ("div style='visibility: hidden !important'", "div"),
        ("div style='content-visibility: hidden'", "div"),
        ("div style='opacity:0!important'", "div"),
        ("div style='opacity:0.0'", "div"),
        ("template", "template"),
        ("textarea", "textarea"),
        ("canvas", "canvas"),
        ("noscript", "noscript"),
    )
    for opening, closing in hiding:
        fake = f"<{opening}>{forged_banner}</{closing}>".encode("utf-8")
        with_inert_duplicate = real.replace(b"<body>", b"<body>" + fake, 1)
        assert probe.parse_delegated(with_inert_duplicate) == probe.parse_delegated(real), opening
        assert probe.reconcile(
            {"agency": agency(), "delegated": with_inert_duplicate}, 12
        )["observation_state"] == "SOURCE_COUNTER_FUNDS_WITHHELD_REVIEW", opening
        # When ALL apparent DR-12 evidence is hidden, parsing must fail
        # rather than accepting hidden date/count/budget as source proof.
        all_hidden = real.replace(b"<body>", b"<body>" + f"<{opening}>".encode(), 1)
        all_hidden = all_hidden.replace(b"</body>", f"</{closing}></body>".encode(), 1)
        reject(lambda all_hidden=all_hidden: probe.parse_delegated(all_hidden))
        assert probe.reconcile(
            {"agency": agency(), "delegated": all_hidden}, 12
        )["observation_state"] == "SOURCE_COUNTER_PARSE_REVIEW", opening

    visible = real.replace(b"<body>", b"<body style='opacity:0.65'>", 1)
    assert probe.parse_delegated(visible) == probe.parse_delegated(real)
    with tempfile.TemporaryDirectory() as td:
        body = real.replace(
            b"<body>", b"<body><div popover='auto'>" + forged_banner.encode() + b"</div>", 1
        )
        receipt = probe.capture(fetches(b=body), Path(td) / "proof", "42199991120")
        assert receipt["parser_version"] == "afir-dr12-official-counter-pair-v10"
        assert receipt["observation_state"] == "SOURCE_COUNTER_FUNDS_WITHHELD_REVIEW"
        assert receipt["open_call_authorized"] is False
        assert receipt["publish_authorized"] is False
        assert probe.replay(Path(td) / "proof")["verified"] is True


def test_immutable_receipt_and_replay():
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "proof"
        record = probe.capture(fetches(), target, "42199991111", "1")
        assert record["parser_version"] == probe.PARSER_VERSION
        assert record["source_family"] == "AFIR"
        assert record["observation_state"] == "SOURCE_COUNTER_FUNDS_WITHHELD_REVIEW"
        assert record["open_call_authorized"] is False
        assert record["publish_authorized"] is False
        assert record["budget_authorized"] is False
        assert record["material_fact_action"] == "NONE"
        assert probe.replay(target)["verified"] is True
        reject(lambda: probe.capture(fetches(), target, "42199991111"))
        original = (target / "manifest.json").read_text(encoding="utf-8")
        for adjust in (
            lambda m: m.update(parser_version="v999"),
            lambda m: m.update(open_call_authorized=True),
            lambda m: m.update(publish_authorized=True),
            lambda m: m.update(budget_authorized=True),
            lambda m: m.update(material_fact_action="OPEN_CALL"),
            lambda m: m.update(observation_state="OPEN_CALL"),
            # Reject additive or missing fields even when the source hash and
            # normalized counter output remain unchanged.
            lambda m: m.update(open_call_status="OPEN_CALL"),
            lambda m: m.update(publication_instruction="PUBLISH"),
            lambda m: m.pop("distribution_authorized"),
            lambda m: m["sources"]["agency"].update(open_call_status="OPEN_CALL"),
            lambda m: m["sources"]["delegated"].update(authority_class="T0"),
            lambda m: m["sources"]["agency"].pop("etag"),
            lambda m: m.update(run_id=""),
            lambda m: m["sources"]["agency"].update(final_url="https://attacker.example/counter"),
            lambda m: m["sources"]["delegated"].update(sha256="0" * 64),
            lambda m: m["sources"]["delegated"].update(byte_count=5),
            lambda m: m["sources"]["agency"].update(content_encoding="gzip"),
            lambda m: m["sources"]["agency"].update(content_type="application/x-nothtml"),
            lambda m: m["sources"]["delegated"].update(content_type="text/plain; note=text/html"),
            lambda m: m["sources"]["agency"].update(fetched_at_utc="2026-11-06T01:00:00"),
            lambda m: m["reconciliation"].update(observation_state="SOURCE_COUNTER_PAIR_MATCH_REVIEW"),
            lambda m: m["reconciliation"]["components"]["ALTE SECTOARE"]["delegated"].update(session_window_matches=False),
            lambda m: m.update(source_family="PRESS"),
        ):
            m = json.loads(original)
            adjust(m)
            (target / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
            reject(lambda: probe.replay(target))
        # Duplicate keys are intrinsically ambiguous across JSON consumers:
        # some retain the first value and others the last. No green replay.
        for ambiguous in (
            original.replace(
                '"publish_authorized": false',
                '"publish_authorized": true, "publish_authorized": false', 1
            ),
            original.replace(
                '"raw_file": "agency.raw.html"',
                '"raw_file": "swapped.html", "raw_file": "agency.raw.html"', 1
            ),
        ):
            assert ambiguous != original
            (target / "manifest.json").write_text(ambiguous, encoding="utf-8")
            reject(lambda: probe.replay(target))
        (target / "manifest.json").write_text(original, encoding="utf-8")
        for source in ("agency", "delegated"):
            path = target / f"{source}.raw.html"
            raw = path.read_bytes()
            path.write_bytes(raw + b"tamper")
            reject(lambda: probe.replay(target))
            path.write_bytes(raw)
        assert probe.replay(target)["verified"] is True
        # Reproduce an internally inconsistent, but valid, official-looking
        # component window. Preserve original values and force review on replay.
        conflict = target.parent / "conflict"
        raw_conflict = delegated().replace(
            "DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59".encode("utf-8"),
            "DATĂ ȘI ORĂ ÎNCHIDERE 11/11/2026 00:00:00".encode("utf-8"), 1,
        )
        proof = probe.capture(fetches(b=raw_conflict), conflict, "42199991112")
        assert proof["observation_state"] == "SOURCE_COUNTER_DIVERGENCE_REVIEW"
        assert proof["reconciliation"]["components"]["SECTOR ZOOTEHNIC"]["delegated"]["closes_at"] == "11.11.2026 00:00:00"
        assert proof["publish_authorized"] is False
        assert probe.replay(conflict)["verified"] is True
        # The original receipt is an exact immutable file set. An extra file
        # or a same-byte symlink is not independent primary-source evidence.
        orphan = target / "orphaned.html"
        orphan.write_bytes(b"unregistered source")
        reject(lambda: probe.replay(target))
        orphan.unlink()
        if os.name != "nt":
            original_path = target / "agency.raw.html"
            original_bytes = original_path.read_bytes()
            external = target.parent / "copied-agency.html"
            external.write_bytes(original_bytes)
            original_path.unlink()
            original_path.symlink_to(external)
            reject(lambda: probe.replay(target))
            original_path.unlink()
            original_path.write_bytes(original_bytes)
        assert probe.replay(target)["verified"] is True


def test_acquire_identity_encoding():
    # A server may ignore Accept-Encoding: identity and return gzip/br.
    # Reject before writing any original or declaring an HTML receipt.
    class Response:
        status = 200
        def __init__(self, encoding, content_type="text/html"):
            self.headers = {"Content-Type": content_type, "Content-Length": str(len(agency()))}
            if encoding is not None:
                self.headers["Content-Encoding"] = encoding
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def geturl(self):
            return probe.AGENCY_URL
        def read(self, max_bytes):
            return agency()[:max_bytes]
    class Opener:
        def __init__(self, encoding, content_type="text/html"):
            self.response = Response(encoding, content_type)
        def open(self, *_args, **_kwargs):
            return self.response
    for encoding in ("gzip", "br", "identity, gzip"):
        with mock.patch.object(probe.urllib.request, "build_opener", return_value=Opener(encoding)):
            reject(lambda: probe.acquire("agency"))
    for encoding in (None, "identity"):
        with mock.patch.object(probe.urllib.request, "build_opener", return_value=Opener(encoding)):
            receipt = probe.acquire("agency")
            assert receipt["content_encoding"] == "identity"
            assert receipt["data"] == agency()
    for mime in ("application/x-nothtml", "text/html-fake",
                 "text/plain; note=text/html", "application/xhtml+xml-fake", ""):
        with mock.patch.object(probe.urllib.request, "build_opener",
                               return_value=Opener(None, mime)):
            reject(lambda: probe.acquire("agency"))
    with mock.patch.object(probe.urllib.request, "build_opener",
                           return_value=Opener(None, "application/xhtml+xml; charset=utf-8")):
        assert probe.acquire("agency")["content_type"].startswith("application/xhtml+xml")


def test_cache_freshness_fail_closed():
    # Synthetic cached 200s must never be treated as a fresh paired counter,
    # even when capture times are 12 seconds apart and values match exactly.
    variants = (
        ("source_age_header", "301", "HTTP_AGE_EXCEEDS_300_SECONDS"),
        ("source_age_header", "not-a-number", "INVALID_HTTP_AGE"),
        ("source_age_header", "999999999999", "INVALID_HTTP_AGE"),
        ("source_date_header", "Thu, 05 Nov 2026 01:00:00 GMT",
         "HTTP_DATE_SKEW_EXCEEDS_300_SECONDS"),
        ("source_date_header", "not-rfc-7231", "INVALID_HTTP_DATE"),
    )
    for key, value, reason in variants:
        with tempfile.TemporaryDirectory() as td:
            rows = deepcopy(fetches())
            rows["agency"][key] = value
            proof = Path(td) / "proof"
            rec = probe.capture(rows, proof, "42199991112")
            assert rec["observation_state"] == "SOURCE_COUNTER_CACHE_FRESHNESS_REVIEW"
            assert rec["reconciliation"]["cache_health"]["review_required"] is True
            assert rec["reconciliation"]["cache_health"]["sources"]["agency"]["reasons"] == [reason]
            assert rec["publish_authorized"] is False
            assert probe.replay(proof)["verified"] is True
            # Altering an archived Age without updating semantic reconciliation
            # must be caught by replay; the raw bytes are left untouched.
            manifest = json.loads((proof / "manifest.json").read_text(encoding="utf-8"))
            manifest["sources"]["agency"]["age_header" if key == "source_age_header" else "date_header"] = (
                "0" if key == "source_age_header" else "Fri, 06 Nov 2026 01:00:00 GMT"
            )
            (proof / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            reject(lambda: probe.replay(proof))

    with tempfile.TemporaryDirectory() as td:
        rows = deepcopy(fetches())
        rows["agency"]["source_age_header"] = "0"
        rows["delegated"]["source_date_header"] = "Fri, 06 Nov 2026 01:00:12 GMT"
        rec = probe.capture(rows, Path(td) / "fresh", "42199991113")
        assert rec["observation_state"] == "SOURCE_COUNTER_FUNDS_WITHHELD_REVIEW"
        assert rec["reconciliation"]["cache_health"]["review_required"] is False
        assert probe.replay(Path(td) / "fresh")["verified"] is True

    with tempfile.TemporaryDirectory() as td:
        rows = deepcopy(fetches())
        rows["agency"]["source_age_header"] = "3600"
        rows["delegated"]["data"] = b"<html>invalid DR-12 session</html>"
        rec = probe.capture(rows, Path(td) / "parse-review", "42199991114")
        # A stale-cache finding does not conceal a more serious semantic error.
        assert rec["observation_state"] == "SOURCE_COUNTER_PARSE_REVIEW"
        assert rec["reconciliation"]["cache_health"]["review_required"] is True
        assert probe.replay(Path(td) / "parse-review")["verified"] is True


def test_capture_guards():
    for source in ("agency", "delegated"):
        reject(lambda source=source: probe.acquire.__globals__["strict_url"]("http://www.afir.ro/", source) or (_ for _ in ()).throw(ValueError()))
    for alter in (
        lambda d: d["delegated"].update(url="https://evil.example/"),
        lambda d: d["agency"].update(status=302),
        lambda d: d["delegated"].update(content_type="application/json"),
        lambda d: d["delegated"].update(content_type="application/x-nothtml"),
        lambda d: d["agency"].update(content_type="text/plain; charset=text/html"),
        lambda d: d["agency"].update(content_encoding="gzip"),
        lambda d: d["agency"].update(fetched_at_utc="2026-11-06T03:00:00+02:00"),
        lambda d: d["agency"].update(data=b""),
    ):
        with tempfile.TemporaryDirectory() as td:
            d = deepcopy(fetches())
            alter(d)
            reject(lambda: probe.capture(d, Path(td) / "proof", "42199991111"))
    with tempfile.TemporaryDirectory() as td:
        rows = deepcopy(fetches())
        rows["agency"]["content_type"] = "application/xhtml+xml; charset=utf-8"
        proof = Path(td) / "xhtml-positive"
        record = probe.capture(rows, proof, "42199991115")
        assert record["open_call_authorized"] is False
        assert probe.replay(proof)["verified"] is True
    assert probe.strict_url(probe.AGENCY_URL, "agency")
    assert probe.strict_url(probe.DELEGATED_URL, "delegated")
    assert not probe.strict_url("https://www.afir.ro:444/finantare/contor-fonduri-disponibile/", "agency")
    assert not probe.strict_url("https://evil.example/Sesiune/Lista", "delegated")


def test_dr12_other_sectors_component_window_discrepancy():
    """Synthetic Nov-11 component close in BOTH counters must not override Dec-2 banner.

    The values are test fixtures, not current AFIR source receipts or a
    verified closure decision. Keep the component date observable, require
    semantic review, and preserve LKG even when the counter pages agree.
    """
    original_agency = agency()
    other_agency_row = b"<td>02.12.2026 15:59:59</td><td>-</td><td>107.470.146</td>"
    assert original_agency.count(other_agency_row) == 1
    agency_early = original_agency.replace(
        other_agency_row,
        b"<td>11.11.2026 00:00:00</td><td>-</td><td>107.470.146</td>",
    )
    original_delegated = delegated()
    end_marker = "DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59".encode("utf-8")
    assert original_delegated.count(end_marker) == 2
    head, tail = original_delegated.rsplit(end_marker, 1)
    delegated_early = (
        head + "DATĂ ȘI ORĂ ÎNCHIDERE 11/11/2026 00:00:00".encode("utf-8") + tail
    )

    agency_rows = probe.parse_agency(agency_early)
    delegated_rows = probe.parse_delegated(delegated_early)
    assert agency_rows["ALTE SECTOARE"]["closes_at"] == "11.11.2026 00:00:00"
    assert delegated_rows["ALTE SECTOARE"]["closes_at"] == "11.11.2026 00:00:00"
    assert delegated_rows["ALTE SECTOARE"]["session_closes_at"] == "02.12.2026 15:59:59"
    assert delegated_rows["ALTE SECTOARE"]["session_window_matches"] is False
    assert delegated_rows["SECTOR ZOOTEHNIC"]["session_window_matches"] is True

    observation = probe.reconcile({"agency": agency_early, "delegated": delegated_early}, 12)
    other = observation["components"]["ALTE SECTOARE"]
    assert other["closing_time_matches"] is True
    assert other["delegated_session_window_matches"] is False
    assert observation["observation_state"] == "SOURCE_COUNTER_DIVERGENCE_REVIEW"
    assert observation["material_fact_action"] == "NONE"

    with tempfile.TemporaryDirectory() as td:
        receipt_dir = Path(td) / "early-close-review"
        manifest = probe.capture(fetches(a=agency_early, b=delegated_early), receipt_dir, "42700011234")
        assert manifest["observation_state"] == "SOURCE_COUNTER_DIVERGENCE_REVIEW"
        assert manifest["last_known_good_action"] == "PRESERVE"
        for field in (
            "open_call_authorized", "publish_authorized", "distribution_authorized",
            "budget_authorized", "eligibility_authorized",
        ):
            assert manifest[field] is False
        assert probe.replay(receipt_dir) == {
            "verified": True,
            "observation_state": "SOURCE_COUNTER_DIVERGENCE_REVIEW",
            "run_id": "42700011234",
            "publish_authorized": False,
        }
        # A downstream caller cannot change the review verdict in the
        # immutable receipt even if the original raw counter bytes are intact.
        manifest_path = receipt_dir / "manifest.json"
        forged = json.loads(manifest_path.read_text(encoding="utf-8"))
        forged["observation_state"] = "SOURCE_COUNTER_PAIR_MATCH_REVIEW"
        manifest_path.write_text(json.dumps(forged), encoding="utf-8")
        reject(lambda: probe.replay(receipt_dir))


if __name__ == "__main__":
    test_parse_and_reconcile()
    test_hidden_counter_dom_fail_closed()
    test_immutable_receipt_and_replay()
    test_acquire_identity_encoding()
    test_capture_guards()
    test_cache_freshness_fail_closed()
    test_dr12_other_sectors_component_window_discrepancy()
    print("AFIR counter pair: hermetic official-host, two-component, divergence and tamper regressions PASS")
