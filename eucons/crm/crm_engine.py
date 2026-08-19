#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "crm" / "crm_contract.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def hid(namespace: str, value: str) -> str:
    digest = hashlib.sha256(f"{namespace}|{value}".encode("utf-8")).hexdigest()
    return f"{namespace[:3].upper()}-{digest[:24]}"


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "revision": 0,
        "organizations": {},
        "contacts": {},
        "leads": {},
        "opportunities": {},
        "offers": {},
        "activities": [],
    }


def _copy(state: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(state)


def append_activity(state: dict[str, Any], event_type: str, entity_type: str, entity_id: str, details: dict[str, Any], at: str | None = None) -> None:
    sequence = len(state["activities"]) + 1
    state["activities"].append({
        "sequence": sequence,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "at": at or now_iso(),
        "details": copy.deepcopy(details),
    })


def validate_e11_record(record: dict[str, Any]) -> None:
    if record.get("engine_id") != "EUCONS_E11_LEAD_ENGINE":
        raise ValueError("unsupported lead source engine")
    if record.get("record_state") != "QUALIFIED_INTAKE":
        raise ValueError("lead record is not qualified intake")
    if not record.get("dedupe_key") or not re.fullmatch(r"[0-9a-f]{64}", record["dedupe_key"]):
        raise ValueError("valid E11 dedupe_key required")
    lead = record.get("lead") or {}
    if not lead.get("email") or not lead.get("contact_name"):
        raise ValueError("contact identity required")
    if (record.get("consent") or {}).get("privacy_ack") is not True:
        raise ValueError("E11 privacy consent state must be preserved")


def find_lead_by_dedupe(state: dict[str, Any], dedupe_key: str) -> dict[str, Any] | None:
    return next((row for row in state["leads"].values() if row.get("dedupe_key") == dedupe_key), None)


def ingest_lead(state: dict[str, Any], e11_record: dict[str, Any], contract: dict[str, Any], at: str | None = None) -> tuple[dict[str, Any], str]:
    validate_e11_record(e11_record)
    out = _copy(state)
    existing = find_lead_by_dedupe(out, e11_record["dedupe_key"])
    if existing:
        append_activity(out, "LEAD_SEEN_AGAIN", "lead", existing["id"], {"dedupe_key": e11_record["dedupe_key"]}, at)
        out["revision"] += 1
        return out, existing["id"]

    lead_payload = e11_record["lead"]
    organization_name = lead_payload.get("organization_name") or "UNSPECIFIED_ORGANIZATION"
    org_id = hid("organization", fold(organization_name))
    contact_id = hid("contact", lead_payload["email"].strip().lower())
    lead_id = hid("lead", e11_record["dedupe_key"])

    if org_id not in out["organizations"]:
        out["organizations"][org_id] = {
            "id": org_id,
            "name": organization_name,
            "audience_id": lead_payload.get("audience_id") or "",
            "created_from_lead_id": lead_id,
        }
        append_activity(out, "ORGANIZATION_CREATED", "organization", org_id, {"source": "E11"}, at)

    if contact_id not in out["contacts"]:
        out["contacts"][contact_id] = {
            "id": contact_id,
            "name": lead_payload["contact_name"],
            "email": lead_payload["email"],
            "phone": lead_payload.get("phone") or "",
            "organization_id": org_id,
            "consent": copy.deepcopy(e11_record.get("consent") or {}),
        }
        append_activity(out, "CONTACT_CREATED", "contact", contact_id, {"source": "E11"}, at)

    out["leads"][lead_id] = {
        "id": lead_id,
        "dedupe_key": e11_record["dedupe_key"],
        "organization_id": org_id,
        "contact_id": contact_id,
        "stage": "NEW",
        "owner": contract["ownership"]["default_owner"],
        "next_action": e11_record.get("next_action") or "REQUEST_MISSING_DATA",
        "scores": copy.deepcopy(e11_record.get("scores") or {}),
        "matching_profile": copy.deepcopy(e11_record.get("matching_profile") or {}),
        "consent": copy.deepcopy(e11_record.get("consent") or {}),
    }
    append_activity(out, "LEAD_CREATED", "lead", lead_id, {"stage": "NEW", "source": "E11"}, at)
    out["revision"] += 1
    return out, lead_id


def assign_owner(state: dict[str, Any], lead_id: str, owner: str, at: str | None = None) -> dict[str, Any]:
    if lead_id not in state["leads"]:
        raise ValueError("unknown lead")
    owner = str(owner or "").strip()
    if not owner or owner == "UNASSIGNED":
        raise ValueError("explicit owner required")
    out = _copy(state)
    previous = out["leads"][lead_id]["owner"]
    out["leads"][lead_id]["owner"] = owner
    append_activity(out, "OWNER_ASSIGNED", "lead", lead_id, {"previous": previous, "owner": owner}, at)
    out["revision"] += 1
    return out


def create_opportunity(state: dict[str, Any], lead_id: str, match_record: dict[str, Any], at: str | None = None) -> tuple[dict[str, Any], str]:
    if lead_id not in state["leads"]:
        raise ValueError("unknown lead")
    if match_record.get("state") != "MATCH_CANDIDATE":
        raise ValueError("only an E10 MATCH_CANDIDATE can create CRM opportunity")
    source_id = str(match_record.get("opportunity_id") or "").strip()
    provenance = match_record.get("source_provenance") or {}
    if not source_id or provenance.get("source_product") != "PARTENER.EU":
        raise ValueError("verified E10 source provenance required")
    opportunity_id = hid("opportunity", f"{lead_id}|{source_id}")
    out = _copy(state)
    if opportunity_id not in out["opportunities"]:
        out["opportunities"][opportunity_id] = {
            "id": opportunity_id,
            "lead_id": lead_id,
            "source_opportunity_id": source_id,
            "title": match_record.get("title") or "",
            "programme": match_record.get("programme") or "",
            "relevance_score": match_record.get("score") or 0,
            "confidence": match_record.get("confidence") or "LOW",
            "source_provenance": copy.deepcopy(provenance),
        }
        append_activity(out, "OPPORTUNITY_CREATED", "opportunity", opportunity_id, {"lead_id": lead_id, "source_opportunity_id": source_id}, at)
        out["revision"] += 1
    return out, opportunity_id


def register_offer(state: dict[str, Any], lead_id: str, version: str, artifact_ref: str, at: str | None = None) -> tuple[dict[str, Any], str]:
    if lead_id not in state["leads"]:
        raise ValueError("unknown lead")
    version = str(version or "").strip()
    artifact_ref = str(artifact_ref or "").strip()
    if not version or not artifact_ref:
        raise ValueError("offer version and artifact_ref required")
    offer_id = hid("offer", f"{lead_id}|{version}")
    out = _copy(state)
    if offer_id not in out["offers"]:
        out["offers"][offer_id] = {"id": offer_id, "lead_id": lead_id, "version": version, "artifact_ref": artifact_ref}
        append_activity(out, "OFFER_REGISTERED", "offer", offer_id, {"lead_id": lead_id, "version": version}, at)
        out["revision"] += 1
    return out, offer_id


def transition(state: dict[str, Any], lead_id: str, target_stage: str, contract: dict[str, Any], *, next_action: str | None = None, at: str | None = None) -> dict[str, Any]:
    if lead_id not in state["leads"]:
        raise ValueError("unknown lead")
    lead = state["leads"][lead_id]
    current = lead["stage"]
    allowed = (contract["allowed_transitions"] or {}).get(current)
    if allowed is None:
        raise ValueError("unknown current stage")
    if target_stage not in allowed:
        raise ValueError(f"invalid CRM transition {current}->{target_stage}")
    if target_stage == "OPPORTUNITY":
        if lead.get("owner") == contract["ownership"]["default_owner"]:
            raise ValueError("owner required before OPPORTUNITY")
        if not any(row.get("lead_id") == lead_id for row in state["opportunities"].values()):
            raise ValueError("CRM opportunity entity required before OPPORTUNITY stage")
    if target_stage in {"OFFER", "NEGOTIATION", "WON"} and not any(row.get("lead_id") == lead_id for row in state["offers"].values()):
        raise ValueError("offer entity required for offer/negotiation/won stages")
    terminal = not contract["allowed_transitions"].get(target_stage, [])
    if not terminal and not (next_action or lead.get("next_action")):
        raise ValueError("next_action required for non-terminal stage")

    out = _copy(state)
    out["leads"][lead_id]["stage"] = target_stage
    if next_action is not None:
        out["leads"][lead_id]["next_action"] = next_action
    if terminal:
        out["leads"][lead_id]["next_action"] = None
    append_activity(out, "STAGE_CHANGED", "lead", lead_id, {"from": current, "to": target_stage, "next_action": out["leads"][lead_id].get("next_action")}, at)
    out["revision"] += 1
    return out


def assert_audit(state: dict[str, Any], contract: dict[str, Any]) -> None:
    required = set(contract["audit"]["required_fields"])
    sequences = []
    for activity in state.get("activities") or []:
        if not required <= set(activity):
            raise ValueError("activity missing audit fields")
        sequences.append(activity["sequence"])
    expected = list(range(contract["audit"]["sequence_starts_at"], contract["audit"]["sequence_starts_at"] + len(sequences)))
    if sequences != expected:
        raise ValueError("activity sequence is not append-only contiguous")


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("runtime CRM state cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lead-record", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    contract = load_json(Path(args.contract))
    state, lead_id = ingest_lead(empty_state(), load_json(Path(args.lead_record)), contract)
    assert_audit(state, contract)
    result = {"lead_id": lead_id, "state": state}
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
