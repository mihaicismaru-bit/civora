#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "security" / "privacy_security_contract.json"
GUARDS_PATH = ROOT / "eucons" / "security" / "security_guards.py"
LEAD_CONTRACT_PATH = ROOT / "eucons" / "leads" / "lead_contract.json"
LEAD_STORAGE_PATH = ROOT / "eucons" / "leads" / "storage_contract.json"
ANALYTICS_CONTRACT_PATH = ROOT / "eucons" / "analytics" / "analytics_contract.json"


def load_guards():
    spec = importlib.util.spec_from_file_location("eucons_security_guards", GUARDS_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E21 security guards")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    lead = json.loads(LEAD_CONTRACT_PATH.read_text(encoding="utf-8"))
    storage = json.loads(LEAD_STORAGE_PATH.read_text(encoding="utf-8"))
    analytics = json.loads(ANALYTICS_CONTRACT_PATH.read_text(encoding="utf-8"))
    guards = load_guards()

    if contract["engine_id"] != "EUCONS_E21_PRIVACY_SECURITY":
        raise SystemExit("E21 engine id drift")
    if contract["production_collection_enabled"] is not False:
        raise SystemExit("E21 must not enable production data collection")
    required_principles = {"purpose_limitation", "data_minimization", "storage_limitation", "integrity_confidentiality", "accountability", "privacy_by_design_default"}
    if set(contract["scope"]["principles"]) != required_principles:
        raise SystemExit("E21 privacy principles incomplete")

    allowed_authorities = {"eur-lex.europa.eu", "www.edpb.europa.eu"}
    sources = contract["official_sources"]
    if len(sources) < 3:
        raise SystemExit("E21 official legal grounding incomplete")
    for source in sources:
        if urlparse(source["url"]).hostname not in allowed_authorities:
            raise SystemExit(f"E21 non-official privacy source: {source['url']}")
    gdpr = next((row for row in sources if row["id"] == "GDPR"), None)
    if not gdpr or not {"5", "6", "7", "25", "32"}.issubset(set(gdpr["articles"])):
        raise SystemExit("E21 GDPR article coverage incomplete")

    purpose_ids = set(contract["data_map"])
    if purpose_ids != {"service_inquiry", "commercial_relationship", "marketing_messages", "suppression", "analytics"}:
        raise SystemExit("E21 data-map purpose coverage drift")
    for purpose_id, spec in contract["data_map"].items():
        if not spec["purpose"] or not spec["basis_candidate"] or not spec["retention_class"]:
            raise SystemExit(f"{purpose_id}: missing purpose/basis/retention mapping")
        if set(spec["required_fields"]) & set(spec["forbidden_fields"]):
            raise SystemExit(f"{purpose_id}: required field is also forbidden")

    if lead["consent"]["marketing_consent_default"] is not False or lead["consent"]["marketing_consent_independent"] is not True:
        raise SystemExit("E21/E11 marketing consent boundary drift")
    if "privacy_ack" not in lead["required_global_fields"]:
        raise SystemExit("E21/E11 privacy acknowledgement missing")
    if storage["production_enabled"] is not False:
        raise SystemExit("E21/E11 storage prematurely enabled")
    activation = set(storage["activation_requirements"])
    if not {"privacy_retention_policy_active", "secret_store_configured"}.issubset(activation):
        raise SystemExit("E21/E11 production storage activation lacks privacy/security gates")

    analytics_privacy = analytics["privacy"]
    if analytics_privacy["raw_pii_forbidden"] is not True or analytics_privacy["data_minimization"] is not True:
        raise SystemExit("E21/E20 analytics minimization drift")
    expected_forbidden = {"email", "phone", "contact_name", "organization_name", "message", "ip", "ip_address", "user_agent", "full_url", "referrer_url"}
    if not expected_forbidden.issubset(set(analytics_privacy["forbidden_keys"])):
        raise SystemExit("E21/E20 analytics PII guard incomplete")

    retention_classes = contract["retention"]["classes"]
    mapped_classes = {spec["retention_class"] for spec in contract["data_map"].values()}
    if mapped_classes != set(retention_classes):
        raise SystemExit("E21 retention classes and data map are not closed")
    for name, policy in retention_classes.items():
        if not isinstance(policy["days"], int) or policy["days"] <= 0:
            raise SystemExit(f"{name}: retention period must be finite positive days")
        if not policy["terminal_action"]:
            raise SystemExit(f"{name}: terminal action missing")
    holds = contract["retention"]["holds"]
    if not all([holds["legal_or_contractual_hold_overrides_automatic_deletion"], holds["hold_requires_reason_code"], holds["hold_requires_review_at"], holds["silent_indefinite_hold_forbidden"]]):
        raise SystemExit("E21 hold controls incomplete")

    if contract["repository_and_secrets"]["real_pii_under_repository_root_forbidden"] is not True:
        raise SystemExit("E21 repository PII guard missing")
    if contract["repository_and_secrets"]["credentials_under_repository_root_forbidden"] is not True:
        raise SystemExit("E21 repository secret guard missing")
    if contract["output_guards"]["html_escape_untrusted_text"] is not True or contract["output_guards"]["log_redaction_required"] is not True:
        raise SystemExit("E21 output guards incomplete")
    if contract["web_security"]["https_required_in_production"] is not True:
        raise SystemExit("E21 HTTPS production gate missing")

    headers = contract["web_security"]["headers"]
    guards.validate_security_headers(headers, contract=contract)
    if "default-src 'self'" not in headers["Content-Security-Policy"] or "frame-ancestors 'none'" not in headers["Content-Security-Policy"]:
        raise SystemExit("E21 CSP baseline incomplete")

    expired = guards.retention_decision("LEAD_INQUIRY", "2026-01-01T00:00:00Z", "2026-08-19T00:00:00Z", contract=contract)
    if expired["state"] != "RETENTION_EXPIRED":
        raise SystemExit("E21 retention expiration not deterministic")
    active = guards.retention_decision("LEAD_INQUIRY", "2026-08-01T00:00:00Z", "2026-08-19T00:00:00Z", contract=contract)
    if active["state"] != "RETAIN":
        raise SystemExit("E21 active retention incorrectly expired")

    service_payload = {
        "contact_name": "Synthetic Contact",
        "email": "synthetic@example.invalid",
        "organization_name": "Synthetic Organization",
        "form_id": "project_evaluation",
        "submission_id": "synthetic-submission",
        "privacy_ack": True,
        "message": "Synthetic project description"
    }
    if guards.validate_purpose_payload("service_inquiry", service_payload, contract=contract) != service_payload:
        raise SystemExit("E21 purpose validation mutated payload")

    escaped = guards.escape_public_text("<b>synthetic & safe</b>")
    if escaped != "&lt;b&gt;synthetic &amp; safe&lt;/b&gt;":
        raise SystemExit("E21 HTML escaping drift")
    redacted = guards.redact_sensitive_logs({"email": "synthetic@example.invalid", "nested": {"message": "hello"}, "safe": "ok"}, contract=contract)
    if redacted != {"email": "[REDACTED]", "nested": {"message": "[REDACTED]"}, "safe": "ok"}:
        raise SystemExit("E21 log redaction drift")

    excluded = {ROOT / "eucons" / "security" / "security_guards.py", ROOT / "eucons" / "validation" / "validate_privacy_security.py", ROOT / "eucons" / "validation" / "test_privacy_security_fail_closed.py"}
    paths = [path for path in (ROOT / "eucons").rglob("*") if path.is_file() and path not in excluded]
    findings = guards.scan_secret_like_paths(paths)
    if findings:
        raise SystemExit("E21 secret-like material found: " + ", ".join(findings))

    print(f"EUCONS E21 Privacy/Security: PASS ({len(purpose_ids)} purposes; {len(retention_classes)} retention classes; official sources enforced; production collection disabled)")


if __name__ == "__main__":
    main()
