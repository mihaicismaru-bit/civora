#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "acceptance" / "full_acceptance_contract.json"
EXPECTED_PHASES = [f"E{index:02d}" for index in range(27)]
EXPECTED_ANALYTICS_EVENTS = [
    "page_view",
    "opportunity_view",
    "evaluation_completed",
    "lead_created",
    "lead_qualified",
    "offer_generated",
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


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("engine_id") != "EUCONS_E27_FULL_ACCEPTANCE":
        raise ValueError("E27 engine id drift")
    if contract.get("product") != "EUCONS_COMMERCIAL_OS":
        raise ValueError("E27 product drift")
    if contract.get("production_side_effects_enabled") is not False:
        raise ValueError("E27 production side effects must remain disabled")
    if contract.get("required_completed_phases") != EXPECTED_PHASES:
        raise ValueError("E27 prerequisite phase list drift")
    if contract.get("required_analytics_events") != EXPECTED_ANALYTICS_EVENTS:
        raise ValueError("E27 analytics event list drift")
    gates = contract.get("external_gates") or {}
    if not gates or not all(value == "CLOSED" for value in gates.values()):
        raise ValueError("E27 external gates must remain CLOSED")
    deterministic = contract.get("determinism") or {}
    if not all(deterministic.values()):
        raise ValueError("E27 determinism contract incomplete")
    if not all((contract.get("forbidden") or {}).values()):
        raise ValueError("E27 forbidden-state contract incomplete")


def completed_receipt_manifest(contract: dict[str, Any]) -> list[dict[str, str]]:
    receipt_dir = EUCONS / "ops" / "receipts"
    manifest: list[dict[str, str]] = []
    for phase in contract["required_completed_phases"]:
        matches = sorted(receipt_dir.glob(f"{phase}_*.json"))
        if len(matches) != 1:
            raise ValueError(f"E27 requires exactly one receipt for {phase}")
        receipt = load_json(matches[0])
        if receipt.get("phase") != phase or receipt.get("status") != "PASS":
            raise ValueError(f"E27 prerequisite receipt is not PASS: {phase}")
        manifest.append({
            "phase": phase,
            "path": matches[0].relative_to(ROOT).as_posix(),
            "sha256": digest_json(receipt),
        })
    return manifest


def assert_cross_engine_lineage(commercial: dict[str, Any]) -> dict[str, Any]:
    match_record = commercial["match_record"]
    crm_state = commercial["crm_state"]
    crm_opportunity = crm_state["opportunities"][commercial["opportunity_id"]]
    offer = commercial["offer"]

    if match_record["state"] != "MATCH_CANDIDATE":
        raise ValueError("E27 match candidate missing")
    if crm_opportunity["source_opportunity_id"] != match_record["opportunity_id"]:
        raise ValueError("E27 match -> CRM source id lineage broken")
    if crm_opportunity["source_provenance"] != match_record["source_provenance"]:
        raise ValueError("E27 match -> CRM provenance lineage broken")
    if offer["opportunity_id"] != commercial["opportunity_id"]:
        raise ValueError("E27 CRM -> offer opportunity lineage broken")
    if offer["source_opportunity_id"] != match_record["opportunity_id"]:
        raise ValueError("E27 offer source opportunity lineage broken")
    if offer["source_provenance"] != match_record["source_provenance"]:
        raise ValueError("E27 offer provenance lineage broken")
    if offer["lead_id"] != commercial["lead_id"]:
        raise ValueError("E27 lead -> offer lineage broken")
    if offer["pricing"]["state"] != "HUMAN_REQUIRED" or offer["pricing"]["amount_minor"] is not None:
        raise ValueError("E27 offer pricing failed open")
    if offer["automatic_send_allowed"] is not False:
        raise ValueError("E27 offer automatic send failed open")
    return {
        "source_product": match_record["source_provenance"]["source_product"],
        "source_opportunity_id": match_record["opportunity_id"],
        "match_to_crm": "PASS",
        "crm_to_offer": "PASS",
        "provenance_preserved": "PASS",
        "lead_sha256": digest_text(commercial["lead_id"]),
        "offer_sha256": digest_json({key: value for key, value in offer.items() if key != "html"}),
    }


def build_analytics(commercial: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    analytics = load_module("e27_analytics", EUCONS / "analytics" / "analytics_engine.py")
    analytics_contract = load_json(EUCONS / "analytics" / "analytics_contract.json")
    lead_id = digest_text(commercial["lead_id"])
    session_id = digest_text("EUCONS-E27-SYNTHETIC-SESSION")
    source_opportunity_id = commercial["match_record"]["opportunity_id"]
    offer_id = commercial["offer"]["offer_id"]
    score = int(commercial["lead_record"]["scores"]["lead_score"])

    event_specs = [
        ("page_view", {"path": "/"}),
        ("opportunity_view", {"opportunity_id": source_opportunity_id, "path": "/finantari/"}),
        ("evaluation_completed", {"form_id": "proposal_request"}),
        ("lead_created", {"lead_id": lead_id}),
        ("lead_qualified", {"lead_id": lead_id, "lead_score": score}),
        ("offer_generated", {"lead_id": lead_id, "offer_id": offer_id}),
    ]
    if [name for name, _ in event_specs] != contract["required_analytics_events"]:
        raise ValueError("E27 analytics journey event order drift")

    outputs: list[dict[str, Any]] = []
    for index, (event_name, properties) in enumerate(event_specs):
        payload = {
            "product": "EUCONS_COMMERCIAL_OS",
            "event_name": event_name,
            "occurred_at": f"2026-08-19T13:27:{index:02d}Z",
            "session_id": session_id,
            "properties": properties,
            "attribution": {},
        }
        output = analytics.build_event(payload, analytics_contract)
        if output["direct_transport_enabled"] is not False or output["dry_run"] is not True:
            raise ValueError("E27 analytics transport gate failed open")
        if output["event"]["transported"] is not False or output["receipt"]["transported"] is not False:
            raise ValueError("E27 analytics event was marked transported")
        outputs.append(output)

    event_ids = [row["event"]["event_id"] for row in outputs]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("E27 analytics event ids are not unique")
    return {
        "event_count": len(outputs),
        "event_names": [row["event"]["event_name"] for row in outputs],
        "funnel_stages": [row["event"]["funnel_stage"] for row in outputs],
        "transport": "DRY_RUN_ONLY",
        "stream_sha256": digest_json(outputs),
        "receipt_sha256": digest_json([row["receipt"] for row in outputs]),
    }


def build_full_acceptance(contract: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    preview = load_module("e27_preview", EUCONS / "preview" / "preview_engine.py")
    adversarial = load_module("e27_adversarial", EUCONS / "adversarial" / "adversarial_suite.py")

    prerequisites = completed_receipt_manifest(contract)
    commercial = preview.synthetic_commercial_journey()
    lineage = assert_cross_engine_lineage(commercial)
    distribution = preview.synthetic_distribution_journey(commercial)
    if distribution["editorial_ready"] < 1:
        raise ValueError("E27 editorial journey produced no READY content")
    if distribution["linkedin_items"] < 1 or distribution["facebook_items"] < 1:
        raise ValueError("E27 social outboxes are empty")
    if distribution["email_decision"] != "READY":
        raise ValueError("E27 commercial email outbox is not READY")
    if distribution["email_dispatch_state"] != "EMAIL_OUTBOX_READY_MAILBOX_AUTH_REQUIRED":
        raise ValueError("E27 mailbox authorization gate drift")

    analytics = build_analytics(commercial, contract)
    adversarial_report = adversarial.run_suite(load_json(EUCONS / "adversarial" / "adversarial_contract.json"))
    if adversarial_report["scenario_count"] != 16 or adversarial_report["production_side_effects_enabled"] is not False:
        raise ValueError("E27 E26 adversarial prerequisite drift")

    first = {
        "commercial": commercial["summary"],
        "lineage": lineage,
        "distribution": distribution,
        "analytics": analytics,
        "adversarial_suite_sha256": adversarial_report["suite_sha256"],
    }
    replay_commercial = preview.synthetic_commercial_journey()
    replay_lineage = assert_cross_engine_lineage(replay_commercial)
    replay_distribution = preview.synthetic_distribution_journey(replay_commercial)
    replay_analytics = build_analytics(replay_commercial, contract)
    replay_adversarial = adversarial.run_suite(load_json(EUCONS / "adversarial" / "adversarial_contract.json"))
    replay = {
        "commercial": replay_commercial["summary"],
        "lineage": replay_lineage,
        "distribution": replay_distribution,
        "analytics": replay_analytics,
        "adversarial_suite_sha256": replay_adversarial["suite_sha256"],
    }
    if digest_json(first) != digest_json(replay):
        raise ValueError("E27 deterministic replay mismatch")

    body = {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "engine_id": contract["engine_id"],
        "status": "PASS",
        "prerequisites": prerequisites,
        "commercial": commercial["summary"],
        "lineage": lineage,
        "distribution": distribution,
        "analytics": analytics,
        "adversarial": {
            "scenario_count": adversarial_report["scenario_count"],
            "suite_sha256": adversarial_report["suite_sha256"],
            "fail_closed": "PASS",
        },
        "external_gates": dict(contract["external_gates"]),
        "production_side_effects_enabled": False,
        "replay_sha256": digest_json(replay),
    }
    body["journey_sha256"] = digest_json(first)
    body["receipt_hash"] = digest_json(body)
    return body


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("E27 runtime acceptance receipt cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_full_acceptance(load_json(Path(args.contract)))
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
