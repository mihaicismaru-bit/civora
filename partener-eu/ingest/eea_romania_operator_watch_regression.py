#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "eea_romania_operator_watch.py"
REGISTRY_PATH = HERE / "eea_romania_operator_watch_registry.json"

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
    if set(routes) != {"EEA-RO-RESEARCH-UEFISCDI-WATCH", "EEA-RO-INNOVATION-NORWAY-FUND-OPERATOR-WATCH"}:
        fail("unexpected bounded route inventory")

    research = routes["EEA-RO-RESEARCH-UEFISCDI-WATCH"]
    if research["observation_state"] != "OPERATOR_WATCH_HISTORICAL_LANDING":
        fail("historical UEFISCDI landing must remain explicitly historical")

    synthetic = b'''<html><body>
      <a href="/eea-norway-grants/open-call-2027">OPEN CALL Romania Research 2027</a>
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

    expect_raises(lambda: mod.validate_route_url("http://uefiscdi.gov.ro/eea-norway-grants", research), "HTTP downgrade")
    expect_raises(lambda: mod.validate_route_url("https://example.com/eea-norway-grants", research), "host drift")
    expect_raises(lambda: mod.validate_route_url("https://uefiscdi.gov.ro/other", research, final=True), "path drift")

    bad_registry = copy.deepcopy(registry)
    bad_registry["policy"]["open_call_authorized"] = True
    expect_raises(lambda: mod.validate_registry(bad_registry), "authorizing registry policy")

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
        "historical_state": research["observation_state"],
        "degraded_lkg_required": degraded["lkg_required"],
        "open_call_authorized": receipt["open_call_authorized"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
