#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "adversarial" / "adversarial_contract.json"

CANONICAL_SCENARIOS = [
    "STALE_OPEN_OPPORTUNITY_HOLD",
    "SPAM_HONEYPOT_REJECTED",
    "INVALID_EMAIL_REJECTED",
    "MISSING_PROVENANCE_OFFER_REJECTED",
    "MISSING_PRICING_HUMAN_REQUIRED",
    "DUPLICATE_CONFLICT_HOLD",
    "DUPLICATE_SAME_KEY_COLLAPSED",
    "ORPHAN_PREPARE_DISCARDED",
    "STALE_LEASE_RESUME",
    "LINKEDIN_OUTAGE_RETRY",
    "FACEBOOK_OUTAGE_EXHAUSTED_HOLD",
    "INDEXABLE_PREVIEW_REJECTED",
    "PRODUCTION_DEPLOYMENT_REJECTED",
    "SOCIAL_LIVE_GATES_CLOSED",
    "EMAIL_LIVE_GATE_CLOSED",
    "PII_REPOSITORY_WRITE_REJECTED",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load module {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result(scenario_id: str, outcome: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"scenario_id": scenario_id, "status": "PASS", "safe_outcome": outcome, "evidence": evidence or {}}


def _expect_error(fn: Callable[[], Any]) -> str:
    try:
        fn()
    except (ValueError, OSError):
        return "REJECTED"
    raise ValueError("adversarial fixture failed open")


def base_lead_payload() -> dict[str, Any]:
    return {
        "form_id": "proposal_request",
        "submission_id": "SYNTH-E26-ADVERSARIAL",
        "submission_age_ms": 2500,
        "website": "",
        "privacy_ack": True,
        "marketing_consent": False,
        "contact_name": "Synthetic Adversarial Person",
        "email": "adversarial.e26@example.invalid",
        "organization_name": "Synthetic Organization",
        "audience_id": "companies_entrepreneurs",
        "message": "Synthetic E26 adversarial fixture.",
        "timeline": "31_90_days",
        "project_stage": "preparation",
    }


def recovery_operation(recovery, operation_id: str, domain: str, *, status: str = "PENDING", attempt: int = 0, max_attempts: int = 3, retryable: bool = True, expected_state_hash: str | None = None, lease=None, orphan_prepare: bool = False, input_seed: str | None = None, **extra) -> dict[str, Any]:
    row = {
        "operation_id": operation_id,
        "domain": domain,
        "status": status,
        "input_hash": recovery.digest_json({"seed": input_seed or operation_id, "domain": domain}),
        "expected_state_hash": expected_state_hash,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "retryable": retryable,
        "lease": lease,
        "orphan_prepare": orphan_prepare,
    }
    row.update(extra)
    return row


def run_suite(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("engine_id") != "EUCONS_E26_ADVERSARIAL_QA":
        raise ValueError("E26 engine id drift")
    if contract.get("production_side_effects_enabled") is not False or contract.get("fail_closed_required") is not True:
        raise ValueError("E26 safety gates invalid")
    if contract.get("fixture_policy") != "SYNTHETIC_ONLY":
        raise ValueError("E26 fixtures must remain synthetic")
    if contract.get("required_scenarios") != CANONICAL_SCENARIOS:
        raise ValueError("E26 canonical scenario matrix drift")
    if not all(contract.get("forbidden", {}).values()):
        raise ValueError("E26 forbidden-state matrix incomplete")

    preview = load_module("e26_preview", EUCONS / "preview" / "preview_engine.py")
    matcher = load_module("e26_matcher", EUCONS / "opportunities" / "match_opportunities.py")
    lead_engine = load_module("e26_lead", EUCONS / "leads" / "process_lead.py")
    offer_engine = load_module("e26_offer", EUCONS / "offers" / "offer_engine.py")
    recovery = load_module("e26_recovery", EUCONS / "ops" / "recovery.py")
    persistence = load_module("e26_persistence", EUCONS / "ops" / "persistence.py")
    builder = load_module("e26_builder", EUCONS / "web" / "build_public_site.py")

    matching_contract = load_json(EUCONS / "opportunities" / "matching_contract.json")
    lead_contract = load_json(EUCONS / "leads" / "lead_contract.json")
    forms = load_json(EUCONS / "leads" / "forms.json")
    offer_contract = load_json(EUCONS / "offers" / "offer_contract.json")
    services = load_json(EUCONS / "services" / "service_registry.json")
    preview_contract = load_json(EUCONS / "preview" / "preview_contract.json")

    results: list[dict[str, Any]] = []

    stale_bridge = preview.synthetic_match_bridge()
    stale_bridge["opportunities"][0]["commercial_state"] = "HOLD_STALE_SOURCE"
    stale_bridge["opportunities"][0]["actionable"] = True
    profile = {
        "profile_id": "e26-stale",
        "audience_id": "companies_entrepreneurs",
        "organization_labels": ["întreprindere agricolă"],
        "activity_codes": ["CAEN 10"],
        "region_terms": [],
        "investment_terms": ["energie", "solară"],
        "requested_grant_eur": 500000,
    }
    stale = matcher.match(profile, stale_bridge, matching_contract)["results"][0]
    if stale["state"] != "HOLD_SOURCE_STATE" or stale["score"] != 0:
        raise ValueError("contradictory stale/open opportunity failed open")
    results.append(_result("STALE_OPEN_OPPORTUNITY_HOLD", stale["state"], {"score": stale["score"]}))

    spam = base_lead_payload(); spam["website"] = "bot-filled"
    results.append(_result("SPAM_HONEYPOT_REJECTED", _expect_error(lambda: lead_engine.process(spam, lead_contract, forms))))
    invalid_email = base_lead_payload(); invalid_email["email"] = "invalid"
    results.append(_result("INVALID_EMAIL_REJECTED", _expect_error(lambda: lead_engine.process(invalid_email, lead_contract, forms))))

    commercial = preview.synthetic_commercial_journey()
    broken_crm = copy.deepcopy(commercial["crm_state"])
    lead_id = commercial["lead_id"]
    opportunity_id = commercial["opportunity_id"]
    broken_crm["leads"][lead_id]["stage"] = "OPPORTUNITY"
    broken_crm["opportunities"][opportunity_id]["source_provenance"] = {}
    provenance_outcome = _expect_error(lambda: offer_engine.compose_offer(
        crm_state=broken_crm,
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        service_ids=["funding_strategy_and_eligibility"],
        assumptions=["Synthetic assumption."],
        exclusions=["Synthetic exclusion."],
        service_registry=services,
        contract=offer_contract,
    ))
    results.append(_result("MISSING_PROVENANCE_OFFER_REJECTED", provenance_outcome))

    offer = commercial["offer"]
    if offer["pricing"]["state"] != "HUMAN_REQUIRED" or offer["pricing"]["amount_minor"] is not None or offer["automatic_send_allowed"] is not False:
        raise ValueError("missing pricing did not remain human-required")
    results.append(_result("MISSING_PRICING_HUMAN_REQUIRED", "HUMAN_REQUIRED", {"auto_send": False}))

    state_hash = recovery.digest_json({"canonical": "e26"})
    dup_a = recovery_operation(recovery, "dup-e26", "PUBLICATION", expected_state_hash=state_hash, input_seed="a")
    dup_b = dict(dup_a); dup_b["input_hash"] = recovery.digest_json({"seed": "b", "domain": "PUBLICATION"})
    conflict = recovery.build_recovery_plan([dup_a, dup_b], reference_time="2026-08-19T13:00:00Z", current_state_hashes={"dup-e26": state_hash})
    if conflict["decisions"][0]["action"] != "HOLD_DUPLICATE_CONFLICT":
        raise ValueError("conflicting duplicate execution failed open")
    results.append(_result("DUPLICATE_CONFLICT_HOLD", "HOLD_DUPLICATE_CONFLICT"))

    same_b = dict(dup_a); same_b["attempt"] = 1
    collapsed = recovery.build_recovery_plan([same_b, dup_a], reference_time="2026-08-19T13:00:00Z", current_state_hashes={"dup-e26": state_hash})
    if len(collapsed["decisions"]) != 1 or collapsed["decisions"][0]["duplicate_count"] != 2:
        raise ValueError("same-key duplicate was not collapsed")
    results.append(_result("DUPLICATE_SAME_KEY_COLLAPSED", "COLLAPSED", {"duplicate_count": 2}))

    with tempfile.TemporaryDirectory() as td:
        directory = Path(td)
        (directory / ".state.json.crash.prepare").write_text("{}", encoding="utf-8")
        orphans = persistence.find_orphan_prepare_files(directory)
        if orphans != [".state.json.crash.prepare"]:
            raise ValueError("interrupted prepare was not detected")
    orphan_op = recovery_operation(recovery, "orphan-e26", "PUBLICATION", expected_state_hash=state_hash, orphan_prepare=True)
    orphan_decision = recovery.decide_recovery(orphan_op, reference_time="2026-08-19T13:00:00Z", current_state_hash=state_hash, delivery_receipt_exists=False)
    if orphan_decision["action"] != "DISCARD_ORPHAN_PREPARE":
        raise ValueError("orphan prepared state was promoted")
    results.append(_result("ORPHAN_PREPARE_DISCARDED", "DISCARD_ORPHAN_PREPARE"))

    stale_lease_op = recovery_operation(
        recovery, "lease-e26", "PUBLICATION", status="RUNNING", attempt=1, expected_state_hash=state_hash,
        lease={"owner": "synthetic-runner", "acquired_at": "2026-08-19T11:00:00Z", "expires_at": "2026-08-19T12:00:00Z"},
    )
    stale_lease = recovery.decide_recovery(stale_lease_op, reference_time="2026-08-19T13:00:00Z", current_state_hash=state_hash, delivery_receipt_exists=False)
    if stale_lease["action"] != "RESUME_AFTER_STALE_LEASE":
        raise ValueError("stale lease did not recover deterministically")
    results.append(_result("STALE_LEASE_RESUME", "RESUME_AFTER_STALE_LEASE"))

    linkedin_outage = recovery_operation(recovery, "li-outage-e26", "LINKEDIN", status="FAILED", attempt=1, expected_state_hash=state_hash)
    li_decision = recovery.decide_recovery(linkedin_outage, reference_time="2026-08-19T13:00:00Z", current_state_hash=state_hash, delivery_receipt_exists=False)
    if li_decision["action"] != "RETRY":
        raise ValueError("LinkedIn retryable outage did not enter controlled retry")
    results.append(_result("LINKEDIN_OUTAGE_RETRY", "RETRY"))

    facebook_outage = recovery_operation(recovery, "fb-outage-e26", "FACEBOOK", status="FAILED", attempt=3, max_attempts=3, expected_state_hash=state_hash)
    fb_decision = recovery.decide_recovery(facebook_outage, reference_time="2026-08-19T13:00:00Z", current_state_hash=state_hash, delivery_receipt_exists=False)
    if fb_decision["action"] != "HOLD_RETRY_EXHAUSTED":
        raise ValueError("Facebook exhausted outage retry failed open")
    results.append(_result("FACEBOOK_OUTAGE_EXHAUSTED_HOLD", "HOLD_RETRY_EXHAUSTED"))

    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        builder.build_site(build_dir)
        routes = preview.materialize_preview_support_files(build_dir, preview_contract)
        home = build_dir / "index.html"
        home.write_text(home.read_text(encoding="utf-8").replace('content="noindex,nofollow"', 'content="index,follow"'), encoding="utf-8")
        index_outcome = _expect_error(lambda: preview.validate_static_build(build_dir, routes, preview_contract))
    results.append(_result("INDEXABLE_PREVIEW_REJECTED", index_outcome))

    bad_preview_contract = copy.deepcopy(preview_contract); bad_preview_contract["production_deployment_enabled"] = True
    with tempfile.TemporaryDirectory() as td:
        deployment_outcome = _expect_error(lambda: preview.build_preview_receipt(Path(td), bad_preview_contract))
    results.append(_result("PRODUCTION_DEPLOYMENT_REJECTED", deployment_outcome))

    li_contract = load_json(EUCONS / "social" / "linkedin_contract.json")
    fb_contract = load_json(EUCONS / "social" / "facebook_contract.json")
    if li_contract["dispatch"]["real_publication_enabled"] is not False or fb_contract["dispatch"]["real_publication_enabled"] is not False:
        raise ValueError("social live dispatch gate open")
    results.append(_result("SOCIAL_LIVE_GATES_CLOSED", "CLOSED"))

    email_contract = load_json(EUCONS / "email" / "email_contract.json")
    if email_contract["dispatch"]["real_sending_enabled"] is not False:
        raise ValueError("email live sending gate open")
    results.append(_result("EMAIL_LIVE_GATE_CLOSED", "CLOSED"))

    pii_outcome = _expect_error(lambda: lead_engine.assert_output_path_safe(EUCONS / "leads" / "e26-real-lead.json"))
    results.append(_result("PII_REPOSITORY_WRITE_REJECTED", pii_outcome))

    if [row["scenario_id"] for row in results] != CANONICAL_SCENARIOS:
        raise ValueError("E26 scenario execution order drift")
    safe = set(contract["safe_outcomes"])
    unsafe = [row for row in results if row["safe_outcome"] not in safe]
    if unsafe:
        raise ValueError(f"E26 unsafe outcome: {unsafe[0]['scenario_id']}={unsafe[0]['safe_outcome']}")

    body = {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "engine_id": contract["engine_id"],
        "production_side_effects_enabled": False,
        "scenario_count": len(results),
        "scenarios": results,
    }
    body["suite_sha256"] = digest_json(body)
    return body


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("E26 runtime adversarial report cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    report = run_suite(load_json(Path(args.contract)))
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
