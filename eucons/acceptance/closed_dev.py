#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "acceptance" / "closed_dev_contract.json"


class ClosedDevError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ClosedDevError(f"cannot load module {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_contract(contract: dict[str, Any]) -> None:
    expected = [f"E{i:02d}" for i in range(28)]
    if contract.get("engine_id") != "EUCONS_E28_CLOSED_DEV":
        raise ClosedDevError("E28 engine id drift")
    if contract.get("product") != "EUCONS_COMMERCIAL_OS":
        raise ClosedDevError("E28 product drift")
    if contract.get("target_state") != "BLOCKED_EXTERNAL_ONLY":
        raise ClosedDevError("E28 target state must be BLOCKED_EXTERNAL_ONLY")
    if contract.get("production_side_effects_enabled") is not False:
        raise ClosedDevError("E28 may not enable production side effects")
    if contract.get("required_completed_phases") != expected:
        raise ClosedDevError("E28 prerequisite phase list drift")
    allowed = contract.get("external_handoff", {}).get("allowed_ids") or []
    if allowed != ["domain_and_hosting", "linkedin", "facebook", "commercial_mailbox"]:
        raise ClosedDevError("E28 external handoff scope drift")
    if contract.get("external_handoff", {}).get("owner_development_actions_required") is not False:
        raise ClosedDevError("E28 cannot defer development work to owner")


def receipt_manifest(contract: dict[str, Any]) -> list[dict[str, str]]:
    receipt_dir = EUCONS / "ops" / "receipts"
    manifest = []
    for phase in contract["required_completed_phases"]:
        matches = sorted(receipt_dir.glob(f"{phase}_*.json"))
        if len(matches) != 1:
            raise ClosedDevError(f"E28 requires exactly one receipt for {phase}")
        receipt = load_json(matches[0])
        if receipt.get("phase") != phase or receipt.get("status") != "PASS":
            raise ClosedDevError(f"E28 prerequisite receipt is not PASS: {phase}")
        manifest.append({
            "phase": phase,
            "path": matches[0].relative_to(ROOT).as_posix(),
            "sha256": sha256_json(receipt),
        })
    return manifest


def evidence_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    evidence = load_json(EUCONS / "evidence" / "evidence_registry.json")
    items = {str(row.get("id")): row for row in evidence.get("evidence_items") or []}
    claims = {str(row.get("id")): row for row in evidence.get("claims") or []}
    return items, claims


def verify_claim(claim_id: str, items: dict[str, dict[str, Any]], claims: dict[str, dict[str, Any]], expected_class: str | None = None) -> None:
    claim = claims.get(claim_id)
    if not claim or claim.get("publication_state") != "PUBLISHABLE":
        raise ClosedDevError(f"public claim is missing or not publishable: {claim_id}")
    if expected_class and claim.get("claim_class") != expected_class:
        raise ClosedDevError(f"public claim class mismatch: {claim_id}")
    evidence_ids = claim.get("evidence_ids") or []
    if not evidence_ids:
        raise ClosedDevError(f"public claim has no evidence: {claim_id}")
    for evidence_id in evidence_ids:
        item = items.get(str(evidence_id))
        if not item or item.get("status") != "ACTIVE":
            raise ClosedDevError(f"public claim resolves to inactive evidence: {claim_id}/{evidence_id}")


def verify_public_content(contract: dict[str, Any]) -> dict[str, Any]:
    evidence = load_json(EUCONS / "evidence" / "evidence_registry.json")
    people = load_json(EUCONS / "people" / "people_registry.json")
    cases = load_json(EUCONS / "cases" / "case_study_registry.json")
    items, claims = evidence_indexes()

    services = [
        row for row in evidence.get("claims") or []
        if row.get("claim_class") == "SERVICE_OFFERING" and row.get("publication_state") == "PUBLISHABLE"
    ]
    public_people = [row for row in people.get("people") or [] if row.get("publication_state") == "PUBLISHABLE"]
    public_cases = [row for row in cases.get("cases") or [] if row.get("publication_state") == "PUBLISHABLE"]
    mins = contract["minimum_public_content"]
    if len(services) < int(mins["services"]):
        raise ClosedDevError("E28 service content below terminal minimum")
    if len(public_people) < int(mins["people"]):
        raise ClosedDevError("E28 people content below terminal minimum")
    if len(public_cases) < int(mins["cases"]):
        raise ClosedDevError("E28 case content below terminal minimum")

    for person in public_people:
        required = [person.get("identity_claim_id"), *(person.get("role_claim_ids") or []), *(person.get("competence_claim_ids") or [])]
        if not all(required):
            raise ClosedDevError("publishable person has incomplete claim lineage")
        verify_claim(str(required[0]), items, claims, "EXPERT_IDENTITY")
        for claim_id in person.get("role_claim_ids") or []:
            verify_claim(str(claim_id), items, claims, "EXPERT_ROLE")
        for claim_id in person.get("competence_claim_ids") or []:
            verify_claim(str(claim_id), items, claims, "EXPERT_CREDENTIAL")
        if not str(person.get("display_name") or "").strip() or not str(person.get("public_headline") or "").strip() or not str(person.get("public_bio") or "").strip():
            raise ClosedDevError("publishable person lacks final public copy")
        if (person.get("photo") or {}).get("state") not in {"NONE", "VERIFIED"}:
            raise ClosedDevError("publishable person photo state invalid")

    for case in public_cases:
        claim_ids = list(dict.fromkeys([*(case.get("result_claim_ids") or []), *(case.get("outcome_claim_ids") or [])]))
        if not claim_ids:
            raise ClosedDevError("publishable case lacks result claims")
        for claim_id in claim_ids:
            verify_claim(str(claim_id), items, claims, "PROJECT_RESULT")
        if case.get("client_attribution") != "ANONYMIZED" and not case.get("client_claim_ids"):
            raise ClosedDevError("named case attribution has no client claim")
        if not str(case.get("public_problem") or "").strip() or not str(case.get("public_intervention") or "").strip() or not (case.get("public_outcomes") or []):
            raise ClosedDevError("publishable case lacks final public copy")

    return {"services": len(services), "people": len(public_people), "cases": len(public_cases)}


def verify_artifact_registry(receipts: list[dict[str, str]]) -> dict[str, Any]:
    registry = load_json(EUCONS / "ops" / "artifact_registry.json")
    active_paths = {
        str(row.get("path")) for row in registry.get("artifacts") or []
        if row.get("status") == "ACTIVE" and row.get("path")
    }
    missing = [row["path"] for row in receipts if row["path"] not in active_paths]
    if missing:
        raise ClosedDevError(f"E28 artifact registry misses completed receipts: {missing}")
    broken = [path for path in active_paths if not (ROOT / path).exists()]
    if broken:
        raise ClosedDevError(f"E28 artifact registry contains missing paths: {broken}")
    return {"active_artifacts": len(active_paths), "receipt_manifests": len(receipts)}


def verify_handoff(contract: dict[str, Any]) -> dict[str, Any]:
    handoff = load_json(ROOT / contract["external_handoff"]["manifest"])
    if handoff.get("state") != "EXTERNAL_AUTHORIZATION_ONLY":
        raise ClosedDevError("external handoff state drift")
    if handoff.get("owner_development_actions_required") is not False:
        raise ClosedDevError("external handoff defers development work")
    rows = handoff.get("allowed_external_actions") or []
    ids = [row.get("id") for row in rows]
    if ids != contract["external_handoff"]["allowed_ids"]:
        raise ClosedDevError("external handoff contains missing, extra or reordered actions")
    if not all(row.get("state") == contract["external_handoff"]["required_state"] for row in rows):
        raise ClosedDevError("external handoff action state drift")
    if any(row.get("secrets_in_repository") is not False for row in rows):
        raise ClosedDevError("external handoff permits secrets in repository")
    return {"actions": ids, "owner_development_actions_required": False}


def verify_runtime(contract: dict[str, Any]) -> dict[str, Any]:
    runtime = load_json(ROOT / contract["required_runtime_contract"])
    if runtime.get("production_enabled") is not False or runtime.get("provider_neutral") is not True:
        raise ClosedDevError("runtime activation contract failed closed")
    route = runtime.get("lead_route") or {}
    if route.get("method") != "POST" or route.get("path") != "/api/leads":
        raise ClosedDevError("runtime lead route drift")
    if route.get("failure_semantics") != "FAIL_CLOSED_NO_PARTIAL_COMMIT" or route.get("pii_repository_write") != "FORBIDDEN":
        raise ClosedDevError("runtime persistence/privacy gate drift")
    return {"lead_route": "POST /api/leads", "production_enabled": False, "provider_neutral": True}


def verify_production_build(target: Path, contract: dict[str, Any]) -> dict[str, Any]:
    production = load_module("e28_production_builder", ROOT / contract["production_build"]["builder"])
    result = production.build_site(target)
    build_contract = load_json(ROOT / contract["production_build"]["contract"])
    expected = int(contract["production_build"]["expected_pages"])
    if result.get("pages") != expected or build_contract.get("build", {}).get("expected_total_pages") != expected:
        raise ClosedDevError("production-ready page count drift")
    for rel in contract["production_build"]["required_files"]:
        if not (target / rel).exists():
            raise ClosedDevError(f"production-ready build missing {rel}")
    html_files = sorted(target.rglob("*.html"))
    if len(html_files) != expected:
        raise ClosedDevError("production-ready generated HTML count drift")
    required_meta = f'<meta name="robots" content="{contract["production_build"]["required_robots_meta"]}">'
    forbidden = [str(row).lower() for row in contract["production_build"]["forbidden_public_phrases"]]
    for file in html_files:
        text = file.read_text(encoding="utf-8")
        lower = text.lower()
        if required_meta not in text or "noindex,nofollow" in lower:
            raise ClosedDevError(f"production page not indexable: {file}")
        if '<link rel="canonical" href="https://eucons.ro' not in text:
            raise ClosedDevError(f"production page canonical drift: {file}")
        if any(phrase in lower for phrase in forbidden):
            raise ClosedDevError(f"development placeholder leaked to production page: {file}")

    team = (target / "echipa" / "index.html").read_text(encoding="utf-8")
    people = load_json(EUCONS / "people" / "people_registry.json")
    for person in [row for row in people.get("people") or [] if row.get("publication_state") == "PUBLISHABLE"]:
        for field in ("display_name", "public_headline", "public_bio"):
            if str(person[field]) not in team:
                raise ClosedDevError(f"team page omits verified {field}")

    project_html = (target / "proiecte" / "index.html").read_text(encoding="utf-8")
    cases = load_json(EUCONS / "cases" / "case_study_registry.json")
    for case in [row for row in cases.get("cases") or [] if row.get("publication_state") == "PUBLISHABLE"]:
        if str(case["title"]) not in project_html:
            raise ClosedDevError("projects page omits verified case title")
        for outcome in case.get("public_outcomes") or []:
            if str(outcome) not in project_html:
                raise ClosedDevError("projects page omits verified case outcome")

    privacy = (target / "confidentialitate" / "index.html").read_text(encoding="utf-8")
    terms = (target / "termeni" / "index.html").read_text(encoding="utf-8")
    for token in ["EUROCONSULT SRL", "CUI 14250864", "Marketing separat", "Drepturile tale", "Păstrarea datelor"]:
        if token not in privacy:
            raise ClosedDevError(f"privacy surface incomplete: {token}")
    for token in ["Relația comercială", "Finanțări și surse", "Conținut și proveniență"]:
        if token not in terms:
            raise ClosedDevError(f"terms surface incomplete: {token}")

    for path in ["evaluare-proiect/index.html", "solicita-oferta/index.html", "contact/index.html"]:
        form = (target / path).read_text(encoding="utf-8")
        for token in ['action="/api/leads"', 'name="privacy_ack"', 'name="marketing_consent"', 'name="submission_id"', 'name="submission_age_ms"']:
            if token not in form:
                raise ClosedDevError(f"provider-neutral lead form incomplete: {path}/{token}")

    robots = (target / "robots.txt").read_text(encoding="utf-8")
    sitemap = (target / "sitemap.xml").read_text(encoding="utf-8")
    if "Allow: /" not in robots or f"Sitemap: {CANONICAL_ORIGIN}/sitemap.xml" not in robots:
        raise ClosedDevError("production robots.txt drift")
    if sitemap.count("<url>") != expected or "https://eucons.ro/" not in sitemap:
        raise ClosedDevError("production sitemap drift")

    file_manifest = {
        path.relative_to(target).as_posix(): sha256_file(path)
        for path in sorted(target.rglob("*")) if path.is_file()
    }
    return {
        "pages": expected,
        "people": result["people"],
        "cases": result["cases"],
        "sitemap_entries": result["sitemap_entries"],
        "files": len(file_manifest),
        "artifact_sha256": sha256_json(file_manifest),
        "production_deployed": False,
    }


CANONICAL_ORIGIN = "https://eucons.ro"


def build_closed_dev(target: Path, contract: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    receipts = receipt_manifest(contract)
    content = verify_public_content(contract)
    artifact_registry = verify_artifact_registry(receipts)
    handoff = verify_handoff(contract)
    runtime = verify_runtime(contract)
    production_build = verify_production_build(target, contract)

    full_acceptance = load_module("e28_full_acceptance", EUCONS / "acceptance" / "full_acceptance.py")
    e27_contract = load_json(EUCONS / "acceptance" / "full_acceptance_contract.json")
    e27 = full_acceptance.build_full_acceptance(e27_contract)
    if e27.get("status") != "PASS" or e27.get("production_side_effects_enabled") is not False:
        raise ClosedDevError("E27 replay failed at E28 terminal gate")

    body = {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "engine_id": contract["engine_id"],
        "status": "PASS",
        "target_state": contract["target_state"],
        "prerequisites": receipts,
        "public_content": content,
        "artifact_registry": artifact_registry,
        "production_build": production_build,
        "runtime": runtime,
        "external_handoff": handoff,
        "full_acceptance_replay_sha256": e27["receipt_hash"],
        "production_side_effects_enabled": False,
        "internal_development_blockers": [],
    }
    body["receipt_hash"] = sha256_json(body)
    return body


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ClosedDevError("E28 runtime acceptance output cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_closed_dev(Path(args.build_dir), load_json(Path(args.contract)))
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
