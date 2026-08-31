#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
BINDING_PATH = HERE / "PUBLIC_RESEARCH_SURFACE_SECURITY_BINDING_DRAFT.json"

RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
EXPECTED_ROUTES = [
    "https://eucons.ro/cercetare/ai4work-step/",
    "https://eucons.ro/cercetare/ai4work-step/adulti/",
    "https://eucons.ro/cercetare/ai4work-step/angajatori/",
]
EXPECTED_API_ROUTE = "https://api.eucons.ro/research/ai4work/v1/submit"

REQUIRED_CSP_DIRECTIVES: dict[str, set[str]] = {
    "default-src": {"'self'"},
    "script-src": {"'self'"},
    "style-src": {"'self'"},
    "img-src": {"'self'"},
    "connect-src": {"https://api.eucons.ro"},
    "form-action": {"'none'"},
    "base-uri": {"'none'"},
    "object-src": {"'none'"},
    "frame-ancestors": {"'none'"},
    "frame-src": {"'none'"},
    "worker-src": {"'none'"},
    "manifest-src": {"'none'"},
    "media-src": {"'none'"},
}
FORBIDDEN_CSP_TOKENS = {
    "*",
    "'unsafe-inline'",
    "'unsafe-eval'",
    "data:",
    "blob:",
    "http:",
    "google-analytics",
    "googletagmanager",
    "facebook.com",
    "connect.facebook.net",
    "hotjar",
    "clarity.ms",
    "segment.com",
    "mixpanel",
}
REQUIRED_PERMISSION_TOKENS = {"camera=()", "microphone=()", "geolocation=()"}
REQUIRED_CACHE_TOKENS = {"no-store"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PublicSurfaceSecurityError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PublicSurfaceSecurityError(f"JSON object required: {path}")
    return data


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_csp(value: str) -> dict[str, set[str]]:
    directives: dict[str, set[str]] = {}
    for segment in value.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        parts = segment.split()
        name = parts[0].lower()
        if name in directives:
            raise PublicSurfaceSecurityError(f"duplicate CSP directive: {name}")
        directives[name] = set(parts[1:])
    return directives


def validate_header_set(headers: dict[str, Any]) -> None:
    normalized = {str(k).strip().lower(): str(v).strip() for k, v in headers.items()}
    required_names = {
        "content-security-policy",
        "referrer-policy",
        "x-content-type-options",
        "permissions-policy",
        "cache-control",
    }
    missing = required_names - set(normalized)
    if missing:
        raise PublicSurfaceSecurityError("missing required response headers: " + ",".join(sorted(missing)))

    csp_value = normalized["content-security-policy"]
    csp_lower = csp_value.lower()
    for token in FORBIDDEN_CSP_TOKENS:
        if token.lower() in csp_lower:
            raise PublicSurfaceSecurityError(f"forbidden CSP token: {token}")
    csp = _parse_csp(csp_value)
    for directive, required_tokens in REQUIRED_CSP_DIRECTIVES.items():
        actual = csp.get(directive)
        if actual is None:
            raise PublicSurfaceSecurityError(f"missing CSP directive: {directive}")
        if not required_tokens.issubset(actual):
            raise PublicSurfaceSecurityError(
                f"CSP directive {directive} missing tokens: {sorted(required_tokens - actual)}"
            )

    if normalized["referrer-policy"].lower() != "no-referrer":
        raise PublicSurfaceSecurityError("Referrer-Policy must be no-referrer")
    if normalized["x-content-type-options"].lower() != "nosniff":
        raise PublicSurfaceSecurityError("X-Content-Type-Options must be nosniff")

    permission_tokens = {part.strip().lower() for part in normalized["permissions-policy"].split(",") if part.strip()}
    if not REQUIRED_PERMISSION_TOKENS.issubset(permission_tokens):
        raise PublicSurfaceSecurityError(
            "Permissions-Policy missing required tokens: "
            + ",".join(sorted(REQUIRED_PERMISSION_TOKENS - permission_tokens))
        )
    cache_tokens = {part.strip().lower() for part in normalized["cache-control"].split(",") if part.strip()}
    if not REQUIRED_CACHE_TOKENS.issubset(cache_tokens):
        raise PublicSurfaceSecurityError("Cache-Control must include no-store")


def _validate_binding_definition(binding: dict[str, Any]) -> None:
    if binding.get("schema_version") != "eucons.ai4work_public_surface_security_binding.v0.1":
        raise PublicSurfaceSecurityError("binding schema_version mismatch")
    if binding.get("research_id") != RESEARCH_ID:
        raise PublicSurfaceSecurityError("binding research_id mismatch")
    if binding.get("evidence_class") != "CONTROL_ARTIFACT_NOT_EVIDENCE":
        raise PublicSurfaceSecurityError("binding evidence_class mismatch")
    if binding.get("synthetic") is not False:
        raise PublicSurfaceSecurityError("binding control artifact must be non-synthetic")

    scope = binding.get("scope")
    if not isinstance(scope, dict):
        raise PublicSurfaceSecurityError("binding scope missing")
    if scope.get("public_routes") != EXPECTED_ROUTES:
        raise PublicSurfaceSecurityError("public research route scope drift")
    if scope.get("api_route") != EXPECTED_API_ROUTE:
        raise PublicSurfaceSecurityError("research API route scope drift")

    twin = binding.get("test_twin")
    if not isinstance(twin, dict):
        raise PublicSurfaceSecurityError("TEST TWIN boundary missing")
    if twin.get("classification") != "TEST_TWIN_NON_EVIDENCE":
        raise PublicSurfaceSecurityError("TEST TWIN classification drift")
    if twin.get("synthetic_only") is not True:
        raise PublicSurfaceSecurityError("TEST TWIN must remain synthetic-only")
    if twin.get("can_satisfy_live_readback") is not False:
        raise PublicSurfaceSecurityError("TEST TWIN cannot satisfy live provider readback")
    if twin.get("prod_promotion_eligible") is not False:
        raise PublicSurfaceSecurityError("TEST TWIN cannot be promotable to PROD evidence")

    policy = binding.get("required_public_response_headers")
    if not isinstance(policy, dict):
        raise PublicSurfaceSecurityError("response-header policy missing")
    csp_policy = policy.get("content-security-policy")
    if not isinstance(csp_policy, dict):
        raise PublicSurfaceSecurityError("CSP policy missing")
    required_directives = csp_policy.get("required_directives")
    if not isinstance(required_directives, dict):
        raise PublicSurfaceSecurityError("CSP required directives missing")
    for directive, expected in REQUIRED_CSP_DIRECTIVES.items():
        actual = required_directives.get(directive)
        if not isinstance(actual, list) or set(map(str, actual)) != expected:
            raise PublicSurfaceSecurityError(f"binding CSP policy drift: {directive}")
    forbidden = csp_policy.get("forbidden_tokens")
    if not isinstance(forbidden, list) or not FORBIDDEN_CSP_TOKENS.issubset(set(map(str, forbidden))):
        raise PublicSurfaceSecurityError("binding CSP forbidden-token policy weakened")
    if str(policy.get("referrer-policy", "")).lower() != "no-referrer":
        raise PublicSurfaceSecurityError("binding Referrer-Policy drift")
    if str(policy.get("x-content-type-options", "")).lower() != "nosniff":
        raise PublicSurfaceSecurityError("binding X-Content-Type-Options drift")
    if set(map(str.lower, map(str, policy.get("permissions-policy_required_tokens") or []))) != REQUIRED_PERMISSION_TOKENS:
        raise PublicSurfaceSecurityError("binding Permissions-Policy drift")
    if not REQUIRED_CACHE_TOKENS.issubset(
        set(map(str.lower, map(str, policy.get("cache-control_required_tokens") or [])))
    ):
        raise PublicSurfaceSecurityError("binding Cache-Control drift")


def _placeholder(value: Any) -> bool:
    text = str(value or "").strip()
    return (
        not text
        or text.startswith(("OPEN_", "TO_BE_", "UNRESOLVED_", "DRAFT_"))
        or "TEST-TWIN" in text.upper()
    )


def _validate_live_readback(binding: dict[str, Any]) -> None:
    readback = binding.get("live_provider_readback")
    if not isinstance(readback, dict):
        raise PublicSurfaceSecurityError("live provider readback missing")
    if readback.get("readback_classification") != "LIVE_PROVIDER_READBACK":
        raise PublicSurfaceSecurityError("live provider readback classification invalid")
    if readback.get("verified") is not True:
        raise PublicSurfaceSecurityError("live provider readback not verified")
    for key in ("provider_account", "verified_at_utc", "verified_by"):
        if _placeholder(readback.get(key)):
            raise PublicSurfaceSecurityError(f"live provider readback {key} missing")
    routes = readback.get("routes")
    if not isinstance(routes, list) or len(routes) != len(EXPECTED_ROUTES):
        raise PublicSurfaceSecurityError("live provider route readback incomplete")
    by_url: dict[str, dict[str, Any]] = {}
    for item in routes:
        if not isinstance(item, dict):
            raise PublicSurfaceSecurityError("live route readback item invalid")
        url = str(item.get("url") or "")
        if url in by_url:
            raise PublicSurfaceSecurityError("duplicate live route readback")
        by_url[url] = item
    if set(by_url) != set(EXPECTED_ROUTES):
        raise PublicSurfaceSecurityError("live provider route set mismatch")
    for url in EXPECTED_ROUTES:
        item = by_url[url]
        if item.get("status_code") != 200:
            raise PublicSurfaceSecurityError(f"live route not HTTP 200: {url}")
        headers = item.get("headers")
        if not isinstance(headers, dict):
            raise PublicSurfaceSecurityError(f"live route headers missing: {url}")
        validate_header_set(headers)

    expected_hash = _canonical_sha256(routes)
    supplied_hash = str(readback.get("readback_sha256") or "")
    if not SHA256_RE.fullmatch(supplied_hash):
        raise PublicSurfaceSecurityError("live readback SHA-256 missing/invalid")
    if supplied_hash != expected_hash:
        raise PublicSurfaceSecurityError("live readback SHA-256 mismatch")


def evaluate(
    *,
    contract_path: Path = CONTRACT_PATH,
    binding_path: Path = BINDING_PATH,
) -> dict[str, Any]:
    contract = _load(contract_path)
    binding = _load(binding_path)
    if contract.get("research_id") != RESEARCH_ID:
        raise PublicSurfaceSecurityError("form contract research_id mismatch")
    _validate_binding_definition(binding)

    production_enabled = contract.get("production_enabled") is True
    if not production_enabled:
        if binding.get("approved_for_prod") is not False:
            raise PublicSurfaceSecurityError("draft binding must not be approved while production is disabled")
        if binding.get("collection_enabled") is not False:
            raise PublicSurfaceSecurityError("draft binding must not enable collection")
        readback = binding.get("live_provider_readback") or {}
        if readback.get("verified") is not False:
            raise PublicSurfaceSecurityError("unbound draft must not claim live provider verification")
        if readback.get("routes") not in ([], None):
            raise PublicSurfaceSecurityError("unbound draft must not carry purported live route readback")
        return {
            "status": "PASS",
            "state": "DRAFT_FAIL_CLOSED",
            "classification": "CONTROL_ONLY_NOT_EVIDENCE",
            "research_id": RESEARCH_ID,
            "production_enabled": False,
            "live_provider_readback_verified": False,
            "test_twin_evidence_eligible": False,
        }

    if binding.get("status") != "APPROVED_FOR_PROD":
        raise PublicSurfaceSecurityError("production contract requires approved security binding")
    if binding.get("approved_for_prod") is not True or binding.get("collection_enabled") is not True:
        raise PublicSurfaceSecurityError("production security binding not enabled")
    _validate_live_readback(binding)
    return {
        "status": "PASS",
        "state": "PROD_PROVIDER_BOUND",
        "classification": "CONTROL_ONLY_NOT_EVIDENCE",
        "research_id": RESEARCH_ID,
        "production_enabled": True,
        "live_provider_readback_verified": True,
        "test_twin_evidence_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = evaluate()
    except (OSError, json.JSONDecodeError, PublicSurfaceSecurityError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
