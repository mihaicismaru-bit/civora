from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence


class ResearchRequirementError(ValueError):
    """Raised when an intake/profile cannot safely define a research agenda."""


def _sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    if not profile.get("profile_id"):
        failures.append({"failure": "missing_profile_id"})
    requirements = list(profile.get("requirements") or [])
    if not requirements:
        failures.append({"failure": "missing_requirements"})
    seen = set()
    for index, req in enumerate(requirements):
        req_id = str(req.get("requirement_id") or "")
        if not req_id:
            failures.append({"failure": "missing_requirement_id", "index": index})
        elif req_id in seen:
            failures.append({"failure": "duplicate_requirement_id", "value": req_id})
        seen.add(req_id)
        if not req.get("construct"):
            failures.append({"failure": "missing_construct", "requirement_id": req_id})
        if not req.get("preferred_scopes"):
            failures.append({"failure": "missing_preferred_scopes", "requirement_id": req_id})
        if not req.get("preferred_source_families"):
            failures.append({"failure": "missing_preferred_source_families", "requirement_id": req_id})
        if req.get("priority") not in {"primary", "supporting"}:
            failures.append({"failure": "invalid_priority", "requirement_id": req_id})
        if not req.get("prohibited_overclaim"):
            failures.append({"failure": "missing_prohibited_overclaim", "requirement_id": req_id})
    return {"valid": not failures, "failures": failures, "requirement_count": len(requirements)}


def build_research_request(
    project_input: Mapping[str, Any],
    call_intelligence: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    historical_cutoff: Optional[str] = None,
) -> Dict[str, Any]:
    profile_validation = validate_profile(profile)
    if not profile_validation["valid"]:
        raise ResearchRequirementError(json.dumps(profile_validation["failures"], ensure_ascii=False, sort_keys=True))
    project_id = project_input.get("project_id") or project_input.get("project_code")
    territory = project_input.get("territory")
    target_group = project_input.get("target_group")
    call_code = call_intelligence.get("call_code")
    if not project_id or not territory or not target_group:
        raise ResearchRequirementError("project input requires project_id/project_code, territory and target_group")
    if not call_code:
        raise ResearchRequirementError("call intelligence requires call_code")

    call_constructs = {str(value) for value in (call_intelligence.get("evidence_constructs") or [])}
    requirements = []
    for req in profile["requirements"]:
        item = dict(req)
        if call_constructs:
            item["call_explicit"] = str(req["construct"]) in call_constructs
        else:
            item["call_explicit"] = None
        item["territory_context"] = territory
        item["target_group_context"] = target_group
        requirements.append(item)

    tasks = []
    for req in requirements:
        if req.get("preferred_source_families") == ["primary_research"]:
            task_type = "PRIMARY_RESEARCH"
        elif "primary_research" in set(req.get("preferred_source_families") or []):
            task_type = "DISCOVERY_THEN_PRIMARY_IF_GAP"
        else:
            task_type = "EXTERNAL_DISCOVERY"
        tasks.append({
            "task_id": f"TASK-{req['requirement_id']}",
            "requirement_id": req["requirement_id"],
            "construct": req["construct"],
            "task_type": task_type,
            "priority": req["priority"],
            "preferred_scopes": list(req["preferred_scopes"]),
            "preferred_source_families": list(req["preferred_source_families"]),
            "direct_local_required": bool(req.get("direct_local_required")),
            "allowed_measure_types": list(req.get("allowed_measure_types") or []),
            "historical_cutoff": historical_cutoff,
            "query_context": {
                "project_id": str(project_id),
                "call_code": str(call_code),
                "territory": territory,
                "target_group": target_group,
                "beneficiary": project_input.get("beneficiary"),
                "partner_school": project_input.get("partner_school"),
                "qualifications": list(project_input.get("qualifications") or []),
            },
            "prohibited_overclaim": req["prohibited_overclaim"],
        })

    request = {
        "schema_version": "nf.research_request.v0.1",
        "project_id": str(project_id),
        "call_code": str(call_code),
        "profile_id": profile["profile_id"],
        "historical_cutoff": historical_cutoff,
        "territory": territory,
        "target_group": target_group,
        "call_intelligence_sha256": _sha256(call_intelligence),
        "profile_sha256": _sha256(profile),
        "requirements": requirements,
        "tasks": tasks,
        "source_policy": dict(profile.get("source_policy") or {}),
    }
    request["request_sha256"] = _sha256(request)
    return request


def task_coverage(
    request: Mapping[str, Any],
    discovery_results: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    covered = set()
    rejected = set()
    for result in discovery_results:
        req_id = str(result.get("requirement_id") or "")
        if result.get("accepted") is True:
            covered.add(req_id)
        elif req_id:
            rejected.add(req_id)
    primary_ids = {str(req["requirement_id"]) for req in request.get("requirements", []) if req.get("priority") == "primary"}
    uncovered = sorted(primary_ids - covered)
    return {
        "schema_version": "nf.research_coverage.v0.1",
        "primary_requirement_count": len(primary_ids),
        "covered_primary_requirements": sorted(primary_ids & covered),
        "uncovered_primary_requirements": uncovered,
        "requirements_with_rejected_candidates": sorted(rejected),
        "external_research_complete": not uncovered,
    }
