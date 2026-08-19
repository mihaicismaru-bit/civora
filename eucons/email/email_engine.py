#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "email" / "email_contract.json"


class EmailEngineError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(stable_json(value))


def normalize_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise EmailEngineError("invalid recipient email")
    return email


def recipient_hash(email: str) -> str:
    return sha256_text(email.lower())


def _validate_lead(lead_result: dict[str, Any], recipient: str, contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if lead_result.get("engine_id") != contract["input"]["required_lead_engine_id"]:
        raise EmailEngineError("unknown lead engine")
    lead = lead_result.get("lead") or {}
    consent = lead_result.get("consent") or {}
    if contract["consent"]["privacy_ack_required_all"] and consent.get("privacy_ack") is not True:
        raise EmailEngineError("privacy acknowledgement required")
    lead_email = normalize_email(lead.get("email"))
    if lead_email != recipient:
        raise EmailEngineError("recipient must match E11 lead contact")
    if not str(lead_result.get("dedupe_key") or "").strip():
        raise EmailEngineError("E11 dedupe key required")
    return lead, consent


def _validate_offer(offer: dict[str, Any] | None, contract: dict[str, Any]) -> dict[str, Any]:
    if not offer:
        raise EmailEngineError("offer required")
    policy = contract["offer"]
    if offer.get("engine_id") != policy["required_engine_id"]:
        raise EmailEngineError("unknown offer engine")
    if policy["automatic_send_flag_must_remain_false_during_e19"] and offer.get("automatic_send_allowed") is not False:
        raise EmailEngineError("E19 requires E13 automatic send disabled")
    pricing = offer.get("pricing") or {}
    state = pricing.get("state")
    if state not in {"HUMAN_REQUIRED", "DETERMINED"}:
        raise EmailEngineError("invalid offer pricing state")
    amount = pricing.get("amount_minor")
    if state != "DETERMINED" and amount is not None:
        raise EmailEngineError("numeric price forbidden without determined pricing")
    if state == "DETERMINED":
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise EmailEngineError("determined price requires non-negative integer amount_minor")
        if not str(pricing.get("currency") or "").strip() or not str(pricing.get("rule_id") or "").strip() or pricing.get("binding") is not True:
            raise EmailEngineError("determined price requires binding approved-rule lineage")
    if not str(offer.get("offer_id") or "").strip() or not str(offer.get("content_sha256") or "").strip():
        raise EmailEngineError("offer identity and immutable content hash required")
    return offer


def _validate_opportunity(opportunity: dict[str, Any] | None, contract: dict[str, Any]) -> dict[str, Any]:
    if not opportunity:
        raise EmailEngineError("opportunity required")
    policy = contract["opportunity"]
    provenance = opportunity.get("provenance") or opportunity.get("source_provenance") or {}
    if provenance.get("source_product") != policy["required_source_product"]:
        raise EmailEngineError("opportunity source must be PARTENER.EU")
    if policy["actionable_required"] and opportunity.get("actionable") is not True:
        raise EmailEngineError("opportunity alert requires actionable opportunity")
    if policy["verified_fact_classes_required"] and not (opportunity.get("verified_fact_classes") or []):
        raise EmailEngineError("opportunity alert requires verified fact classes")
    source_id = opportunity.get("id") or opportunity.get("source_opportunity_id") or provenance.get("source_opportunity_id")
    if not str(source_id or "").strip():
        raise EmailEngineError("opportunity source id required")
    return opportunity


def _offer_price_text(offer: dict[str, Any]) -> str:
    pricing = offer["pricing"]
    if pricing["state"] == "HUMAN_REQUIRED":
        return "Condițiile comerciale și prețul sunt în curs de validare; acest mesaj nu afirmă un preț numeric."
    amount = pricing["amount_minor"] / 100
    return f"Valoarea determinată conform regulii comerciale aprobate: {pricing['currency']} {amount:.2f}."


def _body(
    message_type: str,
    lead: dict[str, Any],
    contract: dict[str, Any],
    *,
    offer: dict[str, Any] | None,
    opportunity: dict[str, Any] | None,
    context: dict[str, Any],
) -> str:
    name = str(lead.get("contact_name") or "").strip() or "Bună ziua"
    greeting = f"Bună, {name}," if name != "Bună ziua" else "Bună ziua,"

    if message_type == "LEAD_ACKNOWLEDGEMENT":
        text = (
            f"{greeting}\n\nAm primit solicitarea transmisă către Euroconsult. "
            "O vom folosi pentru evaluarea cererii și pentru stabilirea următorului pas relevant.\n\n"
            "Acest mesaj confirmă primirea solicitării; nu reprezintă o confirmare a eligibilității sau a finanțării."
        )
    elif message_type == "QUALIFICATION_REQUEST":
        missing = context.get("missing_fields") or []
        if not isinstance(missing, list) or not missing or any(not str(item).strip() for item in missing):
            raise EmailEngineError("qualification request requires missing_fields")
        bullets = "\n".join(f"- {str(item).strip()}" for item in missing)
        text = (
            f"{greeting}\n\nPentru a continua evaluarea avem nevoie de câteva informații suplimentare:\n{bullets}\n\n"
            "După completare putem relua analiza. Solicitarea de informații nu constituie o confirmare a eligibilității."
        )
    elif message_type == "OPPORTUNITY_ALERT":
        opp = opportunity or {}
        title = str(opp.get("title") or "Oportunitate de finanțare verificată").strip()
        programme = str(opp.get("programme") or "").strip()
        source_id = str(opp.get("id") or opp.get("source_opportunity_id") or (opp.get("provenance") or opp.get("source_provenance") or {}).get("source_opportunity_id") or "").strip()
        url = f"https://eucons.ro/finantari/{source_id}/"
        programme_line = f"\nProgram: {programme}" if programme else ""
        text = (
            f"{greeting}\n\nAm identificat o oportunitate verificată care poate merita analizată în raport cu profilul transmis.\n\n"
            f"{title}{programme_line}\n\nDetalii: {url}\n\n"
            "Relevanța nu reprezintă o confirmare a eligibilității; criteriile trebuie verificate pe situația concretă.\n\n"
            f"Preferințe de comunicare: {contract['consent']['unsubscribe_placeholder']}"
        )
    elif message_type == "OFFER_EMAIL":
        off = offer or {}
        version = off.get("version")
        text = (
            f"{greeting}\n\nAm pregătit versiunea {version} a propunerii Euroconsult pentru solicitarea ta.\n\n"
            f"{_offer_price_text(off)}\n\n"
            "Documentul este o proiecție comercială controlată și rămâne supus validării condițiilor indicate în ofertă."
        )
    elif message_type == "FOLLOW_UP":
        interaction = str(context.get("prior_interaction_id") or "").strip()
        if not interaction:
            raise EmailEngineError("follow-up requires prior_interaction_id")
        text = (
            f"{greeting}\n\nRevenim privind solicitarea și interacțiunea anterioară. "
            "Dacă proiectul este încă de actualitate, putem continua de la informațiile deja transmise.\n\n"
            "Dacă situația s-a schimbat, răspunsul tău ne ajută să actualizăm evaluarea."
        )
    elif message_type == "OFFER_EXPIRATION":
        off = offer or {}
        expiry = str(context.get("expires_at") or "").strip()
        if not expiry:
            raise EmailEngineError("offer expiration requires expires_at")
        text = (
            f"{greeting}\n\nOferta Euroconsult versiunea {off.get('version')} are termenul de referință {expiry}. "
            "Dacă dorești continuarea, condițiile trebuie reconfirmate înainte de angajament.\n\n"
            f"{_offer_price_text(off)}"
        )
    else:
        raise EmailEngineError("unknown message type")

    if len(text) > int(contract["presentation"]["max_body_chars"]):
        raise EmailEngineError("email body exceeds deterministic maximum")
    return text


def build_email(
    request: dict[str, Any],
    lead_result: dict[str, Any],
    contract: dict[str, Any],
    *,
    offer: dict[str, Any] | None = None,
    opportunity: dict[str, Any] | None = None,
    suppressed_recipient_hashes: list[str] | None = None,
) -> dict[str, Any]:
    if request.get("product") != contract["input"]["required_product"]:
        raise EmailEngineError("unknown email request product")
    message_type = str(request.get("message_type") or "").strip()
    if message_type not in contract["input"]["allowed_message_types"]:
        raise EmailEngineError("unknown message type")
    recipient = normalize_email(request.get("recipient"))
    lead, consent = _validate_lead(lead_result, recipient, contract)
    context = request.get("context") or {}
    if not isinstance(context, dict):
        raise EmailEngineError("context must be an object")

    if message_type in {"OFFER_EMAIL", "OFFER_EXPIRATION"}:
        offer = _validate_offer(offer, contract)
    if message_type == "OPPORTUNITY_ALERT":
        opportunity = _validate_opportunity(opportunity, contract)

    marketing = message_type in set(contract["consent"]["marketing_types"])
    if marketing and contract["consent"]["marketing_consent_required_for_marketing_types"] and consent.get("marketing_allowed") is not True:
        decision = "HOLD"
        hold_reasons = ["MARKETING_CONSENT_REQUIRED"]
    else:
        decision = "READY"
        hold_reasons = []

    r_hash = recipient_hash(recipient)
    suppressed = set(suppressed_recipient_hashes or [])
    if r_hash in suppressed:
        decision = "HOLD"
        hold_reasons.append("RECIPIENT_SUPPRESSED")

    object_ref = ""
    if offer:
        object_ref = str(offer.get("offer_id") or "")
    elif opportunity:
        provenance = opportunity.get("provenance") or opportunity.get("source_provenance") or {}
        object_ref = str(opportunity.get("id") or opportunity.get("source_opportunity_id") or provenance.get("source_opportunity_id") or "")
    else:
        object_ref = str(request.get("reference_id") or lead_result.get("dedupe_key") or "")

    body = _body(message_type, lead, contract, offer=offer, opportunity=opportunity, context=context)
    subject = contract["presentation"]["subjects"][message_type]
    if len(subject) > int(contract["presentation"]["max_subject_chars"]):
        raise EmailEngineError("email subject exceeds deterministic maximum")
    content_hash = sha256_json({"subject": subject, "body": body, "message_type": message_type, "object_ref": object_ref})
    item_id = "EML-" + sha256_text(f"{message_type}|{lead_result['dedupe_key']}|{r_hash}|{object_ref}|{content_hash}")[:24]
    dispatch_state = contract["dispatch"]["dry_run_state"] if decision == "READY" else "EMAIL_HOLD"
    item = {
        "schema_version": 1,
        "channel": "email",
        "item_id": item_id,
        "message_type": message_type,
        "recipient_sha256": r_hash,
        "subject": subject,
        "body": body,
        "content_hash": content_hash,
        "decision": decision,
        "hold_reasons": sorted(set(hold_reasons)),
        "marketing_message": marketing,
        "marketing_consent_observed": consent.get("marketing_allowed") is True,
        "unsubscribe_required": marketing,
        "dispatch_state": dispatch_state,
        "sent": False,
        "provider_message_id": None,
        "attempts": 0,
        "max_attempts": int(contract["dispatch"]["max_attempts"]),
        "idempotency_key": item_id,
        "object_ref": object_ref,
    }
    receipt_core = {
        "schema_version": 1,
        "channel": "email",
        "item_id": item_id,
        "message_type": message_type,
        "recipient_sha256": r_hash,
        "content_hash": content_hash,
        "decision": decision,
        "hold_reasons": item["hold_reasons"],
        "dispatch_state": dispatch_state,
        "sent": False,
    }
    receipt = dict(receipt_core)
    receipt["receipt_id"] = "RCP-E19-" + sha256_json(receipt_core)[:24]
    receipt["receipt_hash"] = sha256_json(receipt)
    return {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["output"]["product"],
        "engine_id": contract["engine_id"],
        "channel": "email",
        "provider_neutral": True,
        "authorization_required": True,
        "direct_sending_enabled": False,
        "dry_run": True,
        "item": item,
        "receipt": receipt,
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise EmailEngineError("PII-derived email output cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--lead", required=True)
    parser.add_argument("--offer", default=None)
    parser.add_argument("--opportunity", default=None)
    parser.add_argument("--suppression", default=None)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    suppression: list[str] = []
    if args.suppression:
        payload = load_json(Path(args.suppression))
        suppression = list(payload.get("recipient_sha256") or []) if isinstance(payload, dict) else list(payload)
    result = build_email(
        load_json(Path(args.request)),
        load_json(Path(args.lead)),
        load_json(Path(args.contract)),
        offer=load_json(Path(args.offer)) if args.offer else None,
        opportunity=load_json(Path(args.opportunity)) if args.opportunity else None,
        suppressed_recipient_hashes=suppression,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
