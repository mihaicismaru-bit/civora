#!/usr/bin/env python3
"""Hermetic counter-pair tests; synthetic figures are NOT live funding facts."""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
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
 DATĂ FINAL 02/12/2026 15:59:59</div>
<div>DESCRIERE ALOCARE
 <b>DR-12</b><span>Investiții în consolidarea exploatațiilor - Componenta SECTOR ZOOTEHNIC</span>
 DATĂ ȘI ORĂ LANSARE 06/10/2026 09:00:00
 ALOCARE FINANCIARĂ 84794823.50000
 DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59
 PLAFON DEPUNERE -
 VALOAREA PROIECTELOR DEPUSE 12523748.00000
 NUMĂR DOSARE DEPUSE {zoo}
 FONDURI DISPONIBILE *2 {funds}
</div><div>DESCRIERE ALOCARE
 <b>DR-12</b><span>Investiții în consolidarea exploatațiilor - Componenta ALTE SECTOARE</span>
 DATĂ ȘI ORĂ LANSARE 06/10/2026 09:00:00
 ALOCARE FINANCIARĂ 84794823.50000
 DATĂ ȘI ORĂ ÎNCHIDERE 02/12/2026 15:59:59
 PLAFON DEPUNERE -
 VALOAREA PROIECTELOR DEPUSE 107470146.00000
 NUMĂR DOSARE DEPUSE {other}
 FONDURI DISPONIBILE *2 {funds}
</div></body></html>""").encode()


def fetches(a=None, b=None, hours=0):
    return {
        "agency": {
            "ok": True, "url": probe.AGENCY_URL, "status": 200,
            "content_type": "text/html; charset=utf-8",
            "fetched_at_utc": "2026-11-06T01:00:00Z", "data": agency() if a is None else a,
        },
        "delegated": {
            "ok": True, "url": probe.DELEGATED_URL, "status": 200,
            "content_type": "text/html; charset=utf-8",
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
            lambda m: m.update(run_id=""),
            lambda m: m["sources"]["agency"].update(final_url="https://attacker.example/counter"),
            lambda m: m["sources"]["delegated"].update(sha256="0" * 64),
            lambda m: m["sources"]["delegated"].update(byte_count=5),
            lambda m: m["sources"]["agency"].update(fetched_at_utc="2026-11-06T01:00:00"),
            lambda m: m["reconciliation"].update(observation_state="SOURCE_COUNTER_PAIR_MATCH_REVIEW"),
            lambda m: m.update(source_family="PRESS"),
        ):
            m = json.loads(original)
            adjust(m)
            (target / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
            reject(lambda: probe.replay(target))
        (target / "manifest.json").write_text(original, encoding="utf-8")
        for source in ("agency", "delegated"):
            path = target / f"{source}.raw.html"
            raw = path.read_bytes()
            path.write_bytes(raw + b"tamper")
            reject(lambda: probe.replay(target))
            path.write_bytes(raw)
        assert probe.replay(target)["verified"] is True


def test_capture_guards():
    for source in ("agency", "delegated"):
        reject(lambda source=source: probe.acquire.__globals__["strict_url"]("http://www.afir.ro/", source) or (_ for _ in ()).throw(ValueError()))
    for alter in (
        lambda d: d["delegated"].update(url="https://evil.example/"),
        lambda d: d["agency"].update(status=302),
        lambda d: d["delegated"].update(content_type="application/json"),
        lambda d: d["agency"].update(fetched_at_utc="2026-11-06T03:00:00+02:00"),
        lambda d: d["agency"].update(data=b""),
    ):
        with tempfile.TemporaryDirectory() as td:
            d = deepcopy(fetches())
            alter(d)
            reject(lambda: probe.capture(d, Path(td) / "proof", "42199991111"))
    assert probe.strict_url(probe.AGENCY_URL, "agency")
    assert probe.strict_url(probe.DELEGATED_URL, "delegated")
    assert not probe.strict_url("https://www.afir.ro:444/finantare/contor-fonduri-disponibile/", "agency")
    assert not probe.strict_url("https://evil.example/Sesiune/Lista", "delegated")


if __name__ == "__main__":
    test_parse_and_reconcile()
    test_immutable_receipt_and_replay()
    test_capture_guards()
    print("AFIR counter pair: hermetic official-host, two-component, divergence and tamper regressions PASS")
