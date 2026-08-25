#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "inbound_runtime_contract.json"
DEFAULT_FORMS = EUCONS / "leads" / "forms.json"
DEFAULT_UX = EUCONS / "web" / "jtbd_ux_contract.json"
DEFAULT_LEAD_CONTRACT = EUCONS / "leads" / "lead_contract.json"

LIST_FIELDS = {"organization_labels", "activity_codes", "region_terms", "investment_terms"}
ENUM_FIELDS = {"audience_id", "timeline", "project_stage"}
CONTACT_FIELDS = {"contact_name", "email", "phone", "privacy_ack", "marketing_consent", "submitted_at"}


class InboundError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_lead_engine():
    path = EUCONS / "leads" / "process_lead.py"
    spec = importlib.util.spec_from_file_location("eucons_r05_lead_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def clean_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        raise InboundError(f"text exceeds {limit} characters")
    return text


def digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def journey_index(ux: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in ux.get("journeys") or []}


def forms_index(forms: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in forms.get("forms") or []}


def recovery_token(session_id: str, journey_id: str, revision: int) -> str:
    return hashlib.sha256(f"R05|{session_id}|{journey_id}|{revision}".encode("utf-8")).hexdigest()


def empty_session(session_id: str, journey_id: str, contract: dict[str, Any], forms: dict[str, Any], ux: dict[str, Any]) -> dict[str, Any]:
    session_id = clean_text(session_id, 200)
    if not session_id:
        raise InboundError("session_id is required")
    journeys = journey_index(ux)
    form_map = contract.get("journey_form_map") or {}
    if journey_id not in journeys or journey_id not in form_map:
        raise InboundError("unknown journey_id")
    if form_map[journey_id] not in forms_index(forms):
        raise InboundError("journey form is unavailable")
    return {
        "schema_version": 1,
        "engine_id": contract["engine_id"],
        "session_id": session_id,
        "journey_id": journey_id,
        "form_id": form_map[journey_id],
        "stage": "PROFILE",
        "revision": 0,
        "answers": {},
        "request_receipts": {},
        "resume": {
            "token": recovery_token(session_id, journey_id, 0),
            "authentication_state": "PROVIDER_AUTH_REQUIRED",
        },
        "storage_state": contract["storage"]["resumable_session_state"],
    }


def validate_abuse_envelope(request: dict[str, Any], contract: dict[str, Any]) -> None:
    required = set(contract["request_contract"]["required_envelope_fields"])
    missing = required - set(request)
    if missing:
        raise InboundError(f"request envelope missing fields: {sorted(missing)}")
    unknown = set(request) - required
    if unknown:
        raise InboundError(f"request envelope contains unsupported fields: {sorted(unknown)}")
    request_id = clean_text(request.get("request_id"), int(contract["anti_abuse"]["request_id_max_length"]))
    if not request_id:
        raise InboundError("request_id is required")
    if contract["anti_abuse"]["honeypot_must_be_blank"] and clean_text(request.get("website"), 300):
        raise InboundError("spam honeypot triggered")
    age = request.get("submission_age_ms")
    low = contract["anti_abuse"]["minimum_submission_age_ms"]
    high = contract["anti_abuse"]["maximum_submission_age_ms"]
    if not isinstance(age, (int, float)) or not (low <= age <= high):
        raise InboundError("invalid submission_age_ms")
    if request.get("step") not in {"PROFILE", "CONTEXT", "CONTACT"}:
        raise InboundError("invalid step")
    if not isinstance(request.get("answers"), dict):
        raise InboundError("answers must be an object")


def normalize_answers(answers: dict[str, Any], allowed: set[str], lead_contract: dict[str, Any]) -> dict[str, Any]:
    unknown = set(answers) - allowed
    if unknown:
        raise InboundError(f"fields are not allowed in this step: {sorted(unknown)}")
    limits = lead_contract["validation"]
    normalized: dict[str, Any] = {}
    for field, value in answers.items():
        if field in LIST_FIELDS:
            if not isinstance(value, list):
                raise InboundError(f"{field} must be a list")
            rows = []
            for item in value:
                text = clean_text(item, limits["max_short_text_length"])
                if text and text not in rows:
                    rows.append(text)
            normalized[field] = rows
        elif field == "requested_grant_eur":
            if value is not None and (not isinstance(value, (int, float)) or value <= 0):
                raise InboundError("requested_grant_eur must be positive")
            normalized[field] = float(value) if value is not None else None
        elif field == "privacy_ack":
            normalized[field] = value is True
        elif field == "marketing_consent":
            normalized[field] = value is True
        else:
            limit = limits["max_text_length"] if field == "message" else limits["max_short_text_length"]
            normalized[field] = clean_text(value, limit)

    if normalized.get("audience_id") and normalized["audience_id"] not in limits["allowed_audiences"]:
        raise InboundError("invalid audience_id")
    if normalized.get("timeline") and normalized["timeline"] not in limits["allowed_timelines"]:
        raise InboundError("invalid timeline")
    if normalized.get("project_stage") and normalized["project_stage"] not in limits["allowed_project_stages"]:
        raise InboundError("invalid project_stage")
    if normalized.get("email") and not re.match(limits["email_pattern"], normalized["email"].lower()):
        raise InboundError("invalid email")
    if "email" in normalized:
        normalized["email"] = normalized["email"].lower()
    return normalized


def response_for(session: dict[str, Any], contract: dict[str, Any], ux: dict[str, Any], *, replay: bool = False) -> dict[str, Any]:
    journey = journey_index(ux)[session["journey_id"]]
    return {
        "state": "IDEMPOTENT_REPLAY" if replay else ("QUALIFIED_INTAKE" if session["stage"] == "COMPLETED" else "PRELIMINARY_NEXT_STEP"),
        "journey_id": session["journey_id"],
        "revision": session["revision"],
        "next_stage": None if session["stage"] == "COMPLETED" else session["stage"],
        "recommended_service_ids": list(journey.get("service_ids") or []),
        "eligibility_state": contract["preliminary_response"]["eligibility_state"],
        "funding_claim_state": contract["preliminary_response"]["funding_claim_state"],
        "message": contract["preliminary_response"]["messages"][session["journey_id"]],
        "resume_token": session["resume"]["token"],
        "resume_authentication_state": session["resume"]["authentication_state"],
    }


def advance(
    state: dict[str, Any],
    request: dict[str, Any],
    contract: dict[str, Any],
    forms: dict[str, Any],
    ux: dict[str, Any],
    lead_contract: dict[str, Any],
    matching_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_abuse_envelope(request, contract)
    session = copy.deepcopy(state)
    if session.get("engine_id") != contract.get("engine_id"):
        raise InboundError("session engine mismatch")
    journeys = journey_index(ux)
    journey = journeys.get(session.get("journey_id"))
    if not journey:
        raise InboundError("session journey is unavailable")
    if session.get("form_id") != contract["journey_form_map"].get(session["journey_id"]):
        raise InboundError("session form mapping drift")

    request_id = clean_text(request["request_id"], contract["anti_abuse"]["request_id_max_length"])
    request_digest = digest(request)
    receipts = session.get("request_receipts") or {}
    if request_id in receipts:
        if receipts[request_id]["digest"] != request_digest:
            raise InboundError("idempotency conflict")
        return {"session": session, "response": response_for(session, contract, ux, replay=True), "lead_record": None}

    step = request["step"]
    if session.get("stage") == "COMPLETED":
        raise InboundError("completed session cannot accept a new request")
    if step != session.get("stage"):
        raise InboundError(f"step order violation: expected {session.get('stage')}")

    if step == "PROFILE":
        allowed = set(journey.get("first_step_fields") or [])
        normalized = normalize_answers(request["answers"], allowed, lead_contract)
        missing = [field for field in allowed if normalized.get(field) in (None, "", [])]
        if missing:
            raise InboundError(f"profile fields required: {sorted(missing)}")
        if CONTACT_FIELDS.intersection(request["answers"]):
            raise InboundError("contact fields are forbidden before CONTACT")
        session["answers"].update(normalized)
        session["stage"] = "CONTEXT"
        lead_record = None
    elif step == "CONTEXT":
        allowed = set(journey.get("later_fields") or [])
        normalized = normalize_answers(request["answers"], allowed, lead_contract)
        if CONTACT_FIELDS.intersection(request["answers"]):
            raise InboundError("contact fields are forbidden before CONTACT")
        session["answers"].update(normalized)
        session["stage"] = "CONTACT"
        lead_record = None
    else:
        allowed = set(contract["request_contract"]["contact_fields"])
        contact = normalize_answers(request["answers"], allowed, lead_contract)
        for field in ("contact_name", "email", "privacy_ack"):
            if contact.get(field) in (None, "", False):
                raise InboundError(f"contact field required: {field}")
        payload = {
            "form_id": session["form_id"],
            "submission_id": session["session_id"],
            "submission_age_ms": request["submission_age_ms"],
            "website": request["website"],
            "privacy_ack": True,
            "marketing_consent": contact.get("marketing_consent") is True,
            "contact_name": contact["contact_name"],
            "email": contact["email"],
            "phone": contact.get("phone", ""),
            "submitted_at": contact.get("submitted_at", ""),
            **session["answers"],
        }
        lead_engine = load_lead_engine()
        lead_record = lead_engine.process(payload, lead_contract, forms, matching_result)
        session["stage"] = "COMPLETED"
        session["contact_receipt"] = {
            "dedupe_key": lead_record["dedupe_key"],
            "privacy_ack": True,
            "marketing_consent": lead_record["consent"]["marketing_consent"],
            "raw_contact_retained_in_session": False,
        }

    session["revision"] = int(session.get("revision") or 0) + 1
    session["resume"] = {
        "token": recovery_token(session["session_id"], session["journey_id"], session["revision"]),
        "authentication_state": "PROVIDER_AUTH_REQUIRED",
    }
    session.setdefault("request_receipts", {})[request_id] = {
        "digest": request_digest,
        "revision": session["revision"],
    }
    return {
        "session": session,
        "response": response_for(session, contract, ux),
        "lead_record": lead_record,
    }


def assert_output_path_safe(path: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return
    raise InboundError("PII-bearing inbound state cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--journey-id", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--state", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    contract = load_json(DEFAULT_CONTRACT)
    forms = load_json(DEFAULT_FORMS)
    ux = load_json(DEFAULT_UX)
    lead_contract = load_json(DEFAULT_LEAD_CONTRACT)
    state = load_json(Path(args.state)) if args.state else empty_session(args.session_id, args.journey_id, contract, forms, ux)
    result = advance(state, load_json(Path(args.request)), contract, forms, ux, lead_contract)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
