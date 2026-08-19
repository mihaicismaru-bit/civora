#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "offers" / "offer_contract.json"
DEFAULT_SERVICES = EUCONS / "services" / "service_registry.json"


class OfferError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OfferError(f"{label} required")
    return text


def _require_text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise OfferError(f"{label} must be a non-empty list")
    out: list[str] = []
    for item in value:
        text = _require_text(item, label)
        if text in out:
            raise OfferError(f"duplicate {label} entry")
        out.append(text)
    return out


def _services_by_id(service_registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    services = service_registry.get("services") or []
    index = {str(row.get("id") or ""): row for row in services}
    if not index or "" in index or len(index) != len(services):
        raise OfferError("invalid E02 service registry")
    return index


def _validate_crm_context(
    crm_state: dict[str, Any],
    lead_id: str,
    opportunity_id: str,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    for entity in contract.get("required_crm_entities") or []:
        if not isinstance(crm_state.get(entity), dict):
            raise OfferError(f"CRM entity map missing: {entity}")
    lead = (crm_state.get("leads") or {}).get(lead_id)
    if not lead:
        raise OfferError("unknown CRM lead")
    if lead.get("stage") not in (contract.get("allowed_lead_stages") or []):
        raise OfferError("lead stage is not offer-eligible")
    if contract["provenance"].get("crm_owner_required") and lead.get("owner") in {None, "", "UNASSIGNED"}:
        raise OfferError("explicit CRM owner required")
    opportunity = (crm_state.get("opportunities") or {}).get(opportunity_id)
    if not opportunity or opportunity.get("lead_id") != lead_id:
        raise OfferError("CRM opportunity must belong to lead")
    provenance = opportunity.get("source_provenance") or {}
    if contract["provenance"].get("crm_opportunity_source_provenance_required"):
        _require_text(provenance.get("source_product"), "source_product")
        _require_text(provenance.get("source_opportunity_id"), "source_opportunity_id")
    return lead, opportunity


def _pricing(
    contract: dict[str, Any],
    pricing_rule: dict[str, Any] | None,
) -> dict[str, Any]:
    policy = contract["pricing"]
    if pricing_rule is None:
        return {
            "state": policy["default_state"],
            "rule_id": None,
            "amount_minor": None,
            "currency": None,
            "binding": False,
        }
    rule_id = _require_text(pricing_rule.get("rule_id"), "pricing rule id")
    approved = set(policy.get("approved_pricing_rule_ids") or [])
    if rule_id not in approved:
        raise OfferError("pricing rule is not canonically approved")
    amount = pricing_rule.get("amount_minor")
    currency = _require_text(pricing_rule.get("currency"), "pricing currency")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise OfferError("approved pricing amount_minor must be a non-negative integer")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise OfferError("pricing currency must be ISO-like uppercase code")
    return {
        "state": "DETERMINED",
        "rule_id": rule_id,
        "amount_minor": amount,
        "currency": currency,
        "binding": True,
    }


def _next_version(previous_offer: dict[str, Any] | None, lead_id: str, opportunity_id: str, contract: dict[str, Any]) -> tuple[int, str | None]:
    first = int(contract["versioning"]["first_version"])
    if previous_offer is None:
        return first, None
    if previous_offer.get("lead_id") != lead_id or previous_offer.get("opportunity_id") != opportunity_id:
        raise OfferError("offer lineage cannot change lead or opportunity")
    previous_id = _require_text(previous_offer.get("offer_id"), "previous offer id")
    previous_version = previous_offer.get("version")
    if not isinstance(previous_version, int) or isinstance(previous_version, bool) or previous_version < first:
        raise OfferError("invalid previous offer version")
    if not re.fullmatch(r"[0-9a-f]{64}", str(previous_offer.get("content_sha256") or "")):
        raise OfferError("previous offer immutable content hash required")
    return previous_version + 1, previous_id


def compose_offer(
    *,
    crm_state: dict[str, Any],
    lead_id: str,
    opportunity_id: str,
    service_ids: list[str],
    assumptions: list[str],
    exclusions: list[str],
    service_registry: dict[str, Any],
    contract: dict[str, Any],
    previous_offer: dict[str, Any] | None = None,
    pricing_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _lead, opportunity = _validate_crm_context(crm_state, lead_id, opportunity_id, contract)
    if not isinstance(service_ids, list) or not service_ids:
        raise OfferError("at least one service required")
    if len(set(service_ids)) != len(service_ids):
        raise OfferError("duplicate services forbidden")
    service_index = _services_by_id(service_registry)
    unknown = [sid for sid in service_ids if sid not in service_index]
    if unknown:
        raise OfferError(f"unknown E02 service: {unknown[0]}")
    assumptions = _require_text_list(assumptions, "assumption")
    exclusions = _require_text_list(exclusions, "exclusion")
    pricing = _pricing(contract, pricing_rule)
    version, parent_offer_id = _next_version(previous_offer, lead_id, opportunity_id, contract)

    scope = []
    for service_id in service_ids:
        row = service_index[service_id]
        scope.append({
            "service_id": service_id,
            "label": _require_text(row.get("label"), "service label"),
            "summary": _require_text(row.get("summary"), "service summary"),
            "deliverables": _require_text_list(row.get("deliverables"), "deliverable"),
            "boundaries": _require_text_list(row.get("boundaries"), "boundary"),
            "pricing_mode": _require_text(row.get("pricing_mode"), "service pricing mode"),
        })

    core = {
        "schema_version": 1,
        "engine_id": contract["engine_id"],
        "lead_id": lead_id,
        "opportunity_id": opportunity_id,
        "source_opportunity_id": opportunity.get("source_opportunity_id") or (opportunity.get("source_provenance") or {}).get("source_opportunity_id"),
        "opportunity_title": opportunity.get("title") or "",
        "programme": opportunity.get("programme") or "",
        "version": version,
        "parent_offer_id": parent_offer_id,
        "scope": scope,
        "assumptions": assumptions,
        "exclusions": exclusions,
        "pricing": pricing,
        "source_provenance": opportunity.get("source_provenance") or {},
    }
    offer_id = sha256({
        "engine_id": core["engine_id"],
        "lead_id": lead_id,
        "opportunity_id": opportunity_id,
        "version": version,
        "parent_offer_id": parent_offer_id,
        "service_ids": service_ids,
    })
    core["offer_id"] = offer_id
    core["content_sha256"] = sha256(core)
    human_price = pricing["state"] == "HUMAN_REQUIRED"
    core["status"] = "DRAFT_HUMAN_PRICE_REQUIRED" if human_price else "DRAFT_READY_FOR_COMMERCIAL_APPROVAL"
    core["automatic_send_allowed"] = False
    core["send_state"] = "BLOCKED_PRICE_HUMAN_REQUIRED" if human_price else "BLOCKED_PRODUCTION_SENDING_DISABLED"
    core["html"] = render_offer_html(core, contract)
    return core


def render_offer_html(offer: dict[str, Any], contract: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value or ""), quote=True)

    scope_html = []
    for service in offer["scope"]:
        deliverables = "".join(f"<li>{esc(item)}</li>" for item in service["deliverables"])
        boundaries = "".join(f"<li>{esc(item)}</li>" for item in service["boundaries"])
        scope_html.append(
            f"<section><h2>{esc(service['label'])}</h2><p>{esc(service['summary'])}</p>"
            f"<h3>Livrabile</h3><ul>{deliverables}</ul><h3>Limite</h3><ul>{boundaries}</ul></section>"
        )
    assumptions = "".join(f"<li>{esc(item)}</li>" for item in offer["assumptions"])
    exclusions = "".join(f"<li>{esc(item)}</li>" for item in offer["exclusions"])
    if offer["pricing"]["state"] == "HUMAN_REQUIRED":
        pricing_html = f"<p>{esc(contract['projection']['human_price_placeholder'])}</p>"
    else:
        amount = offer["pricing"]["amount_minor"] / 100
        pricing_html = f"<p>{esc(offer['pricing']['currency'])} {amount:.2f}</p>"
    return (
        "<!doctype html><html lang=\"ro\"><head><meta charset=\"utf-8\">"
        "<meta name=\"robots\" content=\"noindex,nofollow\">"
        "<style>@media print{body{font-family:serif}section{break-inside:avoid}}</style>"
        f"<title>Ofertă Euroconsult v{offer['version']}</title></head><body>"
        f"<h1>Ofertă de servicii Euroconsult — versiunea {offer['version']}</h1>"
        f"<p>Oportunitate: {esc(offer['opportunity_title'])}</p>"
        + "".join(scope_html)
        + f"<section><h2>Ipoteze</h2><ul>{assumptions}</ul></section>"
        + f"<section><h2>Excluderi</h2><ul>{exclusions}</ul></section>"
        + f"<section><h2>Condiții comerciale</h2>{pricing_html}</section>"
        + "</body></html>"
    )


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise OfferError("runtime offer artifacts cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crm-state", required=True)
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--opportunity-id", required=True)
    parser.add_argument("--service-id", action="append", required=True)
    parser.add_argument("--assumption", action="append", required=True)
    parser.add_argument("--exclusion", action="append", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--services", default=str(DEFAULT_SERVICES))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    offer = compose_offer(
        crm_state=load_json(Path(args.crm_state)),
        lead_id=args.lead_id,
        opportunity_id=args.opportunity_id,
        service_ids=args.service_id,
        assumptions=args.assumption,
        exclusions=args.exclusion,
        service_registry=load_json(Path(args.services)),
        contract=load_json(Path(args.contract)),
    )
    payload = json.dumps(offer, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
