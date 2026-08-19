#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANON_PATH = ROOT / "canon" / "commercial_canon.json"


def fail(message: str) -> None:
    raise SystemExit(f"EUCONS E01 commercial canon validation failed: {message}")


def unique_ids(items, label):
    ids = [item.get("id") for item in items]
    if any(not item_id or not isinstance(item_id, str) for item_id in ids):
        fail(f"{label} contains missing/invalid id")
    if len(ids) != len(set(ids)):
        fail(f"{label} contains duplicate ids")
    return set(ids)


def main() -> None:
    if not CANON_PATH.exists():
        fail(f"missing {CANON_PATH.relative_to(ROOT)}")

    data = json.loads(CANON_PATH.read_text(encoding="utf-8"))
    if data.get("product") != "EUCONS_COMMERCIAL_OS":
        fail("wrong product identifier")
    if data.get("phase") != "E01":
        fail("phase must be E01")
    if data.get("status") != "CANONICAL":
        fail("status must be CANONICAL")

    audiences = data.get("audiences") or []
    capabilities = data.get("service_capabilities") or []
    ctas = data.get("ctas") or []
    if not audiences or not capabilities or not ctas:
        fail("audiences, service_capabilities and ctas must be non-empty")

    audience_ids = unique_ids(audiences, "audiences")
    capability_ids = unique_ids(capabilities, "service_capabilities")
    cta_ids = unique_ids(ctas, "ctas")

    priority = data.get("priority_audiences") or []
    if len(priority) != len(set(priority)):
        fail("priority_audiences contains duplicates")
    missing_priority = set(priority) - audience_ids
    if missing_priority:
        fail(f"priority audiences missing definitions: {sorted(missing_priority)}")
    extra_audiences = audience_ids - set(priority)
    if extra_audiences:
        fail(f"audiences not declared priority: {sorted(extra_audiences)}")

    all_problem_ids = set()
    referenced_capabilities = set()
    referenced_ctas = set()
    for audience in audiences:
        for required in ("label", "definition", "primary_goal"):
            if not str(audience.get(required, "")).strip():
                fail(f"audience {audience['id']} missing {required}")
        problems = audience.get("problems") or []
        if len(problems) < 3:
            fail(f"audience {audience['id']} must define at least 3 material problems")
        for problem in problems:
            problem_id = problem.get("id")
            if not problem_id or problem_id in all_problem_ids:
                fail(f"duplicate or missing problem id: {problem_id}")
            all_problem_ids.add(problem_id)
            if not str(problem.get("problem", "")).strip():
                fail(f"problem {problem_id} missing human problem statement")

            mapped_capabilities = problem.get("service_capabilities") or []
            mapped_ctas = problem.get("ctas") or []
            if not mapped_capabilities:
                fail(f"problem {problem_id} has no service capability mapping")
            if not mapped_ctas:
                fail(f"problem {problem_id} has no CTA mapping")

            unknown_capabilities = set(mapped_capabilities) - capability_ids
            if unknown_capabilities:
                fail(f"problem {problem_id} references unknown capabilities: {sorted(unknown_capabilities)}")
            unknown_ctas = set(mapped_ctas) - cta_ids
            if unknown_ctas:
                fail(f"problem {problem_id} references unknown CTAs: {sorted(unknown_ctas)}")
            referenced_capabilities.update(mapped_capabilities)
            referenced_ctas.update(mapped_ctas)

    unused_capabilities = capability_ids - referenced_capabilities
    if unused_capabilities:
        fail(f"unmapped service capabilities: {sorted(unused_capabilities)}")
    unused_ctas = cta_ids - referenced_ctas
    if unused_ctas:
        fail(f"unmapped CTAs: {sorted(unused_ctas)}")

    rules = data.get("rules") or {}
    required_true_rules = {
        "public_claims_require_evidence",
        "funding_facts_require_verified_projection",
        "undefined_price_fails_closed",
        "marketing_consent_must_be_explicit",
        "audience_problem_service_cta_mapping_required",
    }
    missing_rules = sorted(rule for rule in required_true_rules if rules.get(rule) is not True)
    if missing_rules:
        fail(f"required fail-closed rules not true: {missing_rules}")

    print(
        "EUCONS E01 commercial canon valid: "
        f"{len(audiences)} audiences, {len(all_problem_ids)} problems, "
        f"{len(capabilities)} capabilities, {len(ctas)} CTAs"
    )


if __name__ == "__main__":
    main()
