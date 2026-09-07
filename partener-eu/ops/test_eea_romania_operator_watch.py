#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "ingest" / "eea_romania_operator_watch.py"
REGISTRY_PATH = HERE.parent / "ingest" / "eea_romania_operator_watch_registry.json"

spec = importlib.util.spec_from_file_location("eea_operator_watch", MODULE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("FAIL: cannot load EEA operator-watch adapter")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def expect_raises(fn, label: str) -> None:
    try:
        fn()
    except Exception:
        return
    fail(f"expected failure: {label}")


def main() -> int:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    mod.validate_registry(registry)
    routes = {row["route_id"]: row for row in registry["routes"]}
    expected_routes = {
        "EEA-RO-RESEARCH-UEFISCDI-WATCH",
        "EEA-RO-GREEN-TRANSITION-MMAP-WATCH",
        "EEA-RO-LOCAL-DEVELOPMENT-FRDS-WATCH",
        "EEA-RO-CULTURE-MC-UMP-WATCH",
        "EEA-RO-JUSTICE-MJ-WATCH",
        "EEA-RO-HOME-AFFAIRS-MAI-WATCH",
        "EEA-RO-INSTITUTIONAL-COOPERATION-MIPE-WATCH",
        "EEA-RO-INNOVATION-NORWAY-FUND-OPERATOR-WATCH",
        "EEA-RO-CIVIL-SOCIETY-FUND-CALL-INDEX-WATCH",
    }
    if set(routes) != expected_routes:
        fail("unexpected bounded route inventory")

    research = routes["EEA-RO-RESEARCH-UEFISCDI-WATCH"]
    if research["observation_state"] != "OPERATOR_WATCH" or "/eea-grants-2021-2028" not in research["watch_url"]:
        fail("UEFISCDI route must remain the current 2021-2028 operator watch surface")

    green = routes["EEA-RO-GREEN-TRANSITION-MMAP-WATCH"]
    if (
        green["observation_state"] != "OPERATOR_WATCH"
        or green["operator_name"] != "Ministry of Environment, Water and Forestry"
        or "mmediu.ro/en/comunicare/comunicate-de-presa/" not in green["watch_url"]
        or green["programme_ids"] != ["green-transition"]
    ):
        fail("MMAP Green Transition route must remain bounded to the current official 2021-2028 operator evidence surface")

    local = routes["EEA-RO-LOCAL-DEVELOPMENT-FRDS-WATCH"]
    if (
        local["observation_state"] != "OPERATOR_WATCH"
        or local["operator_name"] != "Romanian Social Development Fund"
        or local["watch_url"] != "https://frds.ro/en/home/"
        or local["programme_ids"] != ["local-development"]
        or "dezvoltare-locala.frds.ro" not in set(local.get("allowed_hosts") or [])
    ):
        fail("FRDS Local Development route must remain bounded to the current official 2021-2028 Programme Operator surface")

    culture = routes["EEA-RO-CULTURE-MC-UMP-WATCH"]
    if (
        culture["observation_state"] != "OPERATOR_WATCH"
        or culture["operator_name"] != "Ministry of Culture"
        or culture["programme_ids"] != ["culture"]
        or (culture.get("watch_url") or "").split("/", 3)[2] not in {"umpcultura.ro", "www.umpcultura.ro"}
        or "2021-2028" not in culture["period_context"]
    ):
        fail("Culture route must remain bounded to the Ministry Project Management Unit current-period preparation evidence surface")

    justice = routes["EEA-RO-JUSTICE-MJ-WATCH"]
    if (
        justice["observation_state"] != "OPERATOR_WATCH_HISTORICAL_LANDING"
        or justice["operator_name"] != "Ministry of Justice"
        or justice["watch_url"] != "https://www.just.ro/norwaygrants/"
        or justice["programme_ids"] != ["justice"]
    ):
        fail("Justice route must remain a historical ministry landing watch until current-period operator/call evidence appears")

    home_affairs = routes["EEA-RO-HOME-AFFAIRS-MAI-WATCH"]
    if (
        home_affairs["observation_state"] != "OPERATOR_WATCH_HISTORICAL_LANDING"
        or home_affairs["operator_name"] != "Ministry of Internal Affairs"
        or home_affairs["watch_url"] != "https://norwaygrants-en.mai.gov.ro/"
        or home_affairs["programme_ids"] != ["home-affairs"]
    ):
        fail("Home Affairs route must remain a historical dedicated-operator-site watch until current-period evidence appears")

    institutional = routes["EEA-RO-INSTITUTIONAL-COOPERATION-MIPE-WATCH"]
    if (
        institutional["observation_state"] != "OPERATOR_WATCH_HISTORICAL_LANDING"
        or institutional["operator_name"] != "Ministry of Investments and European Projects"
        or institutional["watch_url"] != "https://www.eeagrants.ro/despre"
        or institutional["programme_ids"] != ["institutional-cooperation-and-capacity-building"]
    ):
        fail("MIPE Institutional Cooperation route must remain a historical national EEA landing watch until current-period operator/call evidence appears")

    innovation = routes["EEA-RO-INNOVATION-NORWAY-FUND-OPERATOR-WATCH"]
    if innovation["observation_state"] != "OPERATOR_WATCH" or innovation["watch_url"] != "https://www.innovasjonnorge.no/seksjon/eos-midlene":
        fail("Innovation Norway route must remain the current official EEA operator surface")

    civil = routes["EEA-RO-CIVIL-SOCIETY-FUND-CALL-INDEX-WATCH"]
    if (
        civil["observation_state"] != "OPERATOR_WATCH"
        or civil["operator_role"] != "Fund Operator"
        or civil["programme_ids"] != ["civil-society-fund"]
        or civil["watch_url"] != "https://eeagrants.org/en/eea-civil-society-fund-romania/calls"
        or civil["authority_class"] != "T1_OFFICIAL_FUND_OPERATOR"
        or civil["freshness_hours"] != 6
    ):
        fail("Civil Society Fund route must remain bounded to the current official Romania calls-index discovery surface")

    synthetic = b'''<html><body>
      <a href="/eea-grants-2021-2028/open-call-2027">OPEN CALL Romania Research 2027</a>
      <a href="https://example.com/open-call">External open call</a>
      <a href="/unrelated">Contact</a>
    </body></html>'''
    receipt = mod.build_healthy_receipt(
        synthetic,
        research,
        final_url=research["watch_url"],
        status=200,
        content_type="text/html",
        run_id="regression",
        fetched_at="2026-08-30T18:00:00+00:00",
    )
    mod.validate_receipt(receipt, research)
    if receipt["candidate_count"] != 1:
        fail(f"expected one same-authority discovery candidate, got {receipt['candidate_count']}")
    if any(receipt.get(key) is not False for key in mod.AUTHORIZATION_KEYS):
        fail("lexical OPEN CALL escaped non-authorizing boundary")
    if receipt["candidates"][0]["candidate_observation_state"] != "DISCOVERY_ONLY":
        fail("candidate escaped DISCOVERY_ONLY")

    civil_synthetic = b'''<html><body>
      <article><a href="/en/eea-civil-society-fund-romania/calls/call-1-strengthening-democracy">Call #1 Strengthening Democracy</a><span>Open</span><time>08/10/2026</time></article>
      <article><a href="/en/eea-civil-society-fund-romania/calls/call-5-roma-inclusion">Call #5 Roma Inclusion</a><span>Open</span><time>08/10/2026</time></article>
      <a href="https://example.com/calls/call-99">External call</a>
    </body></html>'''
    civil_receipt = mod.build_healthy_receipt(
        civil_synthetic,
        civil,
        final_url=civil["watch_url"],
        status=200,
        content_type="text/html",
        run_id="civil-society-regression",
        fetched_at="2026-09-03T02:50:00+00:00",
    )
    mod.validate_receipt(civil_receipt, civil)
    if civil_receipt["candidate_count"] != 2:
        fail(f"expected two bounded Civil Society Fund call discoveries, got {civil_receipt['candidate_count']}")
    if any(c.get("candidate_observation_state") != "DISCOVERY_ONLY" for c in civil_receipt["candidates"]):
        fail("Civil Society Fund call-index candidate escaped DISCOVERY_ONLY")
    if any(civil_receipt.get(key) is not False for key in mod.AUTHORIZATION_KEYS):
        fail("Civil Society Fund call-index OPEN labels escaped the non-authorizing boundary")

    expect_raises(lambda: mod.validate_route_url("http://uefiscdi.gov.ro/eea-grants-2021-2028", research), "HTTP downgrade")
    expect_raises(lambda: mod.validate_route_url("https://example.com/eea-grants-2021-2028", research), "host drift")
    expect_raises(lambda: mod.validate_route_url("https://uefiscdi.gov.ro/other", research, final=True), "path drift")
    expect_raises(lambda: mod.validate_route_url("https://mmediu.ro/comunicare/comunicate-de-presa/other", green, final=True), "MMAP path drift")
    expect_raises(lambda: mod.validate_route_url("https://frds.ro/en/other/", local, final=True), "FRDS path drift")
    expect_raises(lambda: mod.validate_route_url("https://example.frds.ro/en/home/", local), "FRDS host drift")
    expect_raises(lambda: mod.validate_route_url("https://www.umpcultura.ro/ctg_2_noutati_pg_0.htm", culture, final=True), "Culture operator path drift")
    expect_raises(lambda: mod.validate_route_url("https://www.just.ro/other/", justice, final=True), "Justice historical landing path drift")
    expect_raises(lambda: mod.validate_route_url("https://www.mai.gov.ro/", home_affairs), "Home Affairs dedicated host drift")
    expect_raises(lambda: mod.validate_route_url("https://www.eeagrants.ro/programe", institutional, final=True), "MIPE historical landing path drift")
    expect_raises(lambda: mod.validate_route_url("https://example.com/en/eea-civil-society-fund-romania/calls", civil), "Civil Society Fund host drift")
    expect_raises(lambda: mod.validate_route_url("https://eeagrants.org/en/other-programme/calls", civil, final=True), "Civil Society Fund path drift")

    bad_registry = copy.deepcopy(registry)
    bad_registry["policy"]["open_call_authorized"] = True
    expect_raises(lambda: mod.validate_registry(bad_registry), "authorizing registry policy")

    historical_promoted = copy.deepcopy(registry)
    hist_routes = {row["route_id"]: row for row in historical_promoted["routes"]}
    hist_routes["EEA-RO-JUSTICE-MJ-WATCH"]["observation_state"] = "OPEN_CALL"
    expect_raises(lambda: mod.validate_registry(historical_promoted), "historical Justice landing promoted to OPEN_CALL")

    institutional_promoted = copy.deepcopy(registry)
    inst_routes = {row["route_id"]: row for row in institutional_promoted["routes"]}
    inst_routes["EEA-RO-INSTITUTIONAL-COOPERATION-MIPE-WATCH"]["observation_state"] = "OPEN_CALL"
    expect_raises(lambda: mod.validate_registry(institutional_promoted), "historical MIPE landing promoted to OPEN_CALL")

    civil_promoted = copy.deepcopy(registry)
    civil_routes = {row["route_id"]: row for row in civil_promoted["routes"]}
    civil_routes["EEA-RO-CIVIL-SOCIETY-FUND-CALL-INDEX-WATCH"]["observation_state"] = "OPEN_CALL"
    expect_raises(lambda: mod.validate_registry(civil_promoted), "Civil Society Fund calls index promoted to OPEN_CALL")

    degraded = mod.build_degraded_receipt(
        research,
        run_id="regression",
        fetched_at="2026-08-30T18:00:00+00:00",
        error=RuntimeError("simulated source outage"),
    )
    mod.validate_receipt(degraded, research)
    if degraded["lkg_required"] is not True or degraded["candidate_count"] != 0:
        fail("degraded route did not fail closed to LKG")

    missing = set(receipt.get("missing_for_open_confirmation") or [])
    required = {
        "exact_call_or_topic_identifier",
        "current_official_exact_call_endpoint",
        "explicit_current_official_open_status",
        "semantic_reconciliation",
    }
    if not required.issubset(missing):
        fail("OPEN proof requirements incomplete")

    print(json.dumps({
        "routes": len(routes),
        "synthetic_candidates": receipt["candidate_count"],
        "civil_society_fund_candidates": civil_receipt["candidate_count"],
        "research_state": research["observation_state"],
        "green_transition_route": green["watch_url"],
        "local_development_route": local["watch_url"],
        "culture_route": culture["watch_url"],
        "justice_state": justice["observation_state"],
        "home_affairs_state": home_affairs["observation_state"],
        "institutional_state": institutional["observation_state"],
        "innovation_route": innovation["watch_url"],
        "civil_society_fund_route": civil["watch_url"],
        "degraded_lkg_required": degraded["lkg_required"],
        "open_call_authorized": receipt["open_call_authorized"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
