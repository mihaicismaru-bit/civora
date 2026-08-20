from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from adapters.civora_discovery import CivoraDiscoveryError, promote_discovery_receipt
from adapters.civora_provider import DiscoveryProvider


def run_research_cycle(
    request: Mapping[str, Any],
    provider: DiscoveryProvider,
) -> Dict[str, Any]:
    evidence: Dict[str, Dict[str, Any]] = {}
    accepted_candidates = []
    rejected_candidates = []
    provider_errors = []
    primary_research_queue = []
    unresolved_external_primary = []
    unresolved_external_supporting = []

    for task in request.get("tasks", []) or []:
        requirement_id = str(task.get("requirement_id") or "")
        task_type = task.get("task_type")
        if task_type == "PRIMARY_RESEARCH":
            primary_research_queue.append({
                "requirement_id": requirement_id,
                "construct": task.get("construct"),
                "reason": "profile_requires_primary_research",
                "priority": task.get("priority"),
            })
            continue

        try:
            receipts = list(provider.discover(task))
        except Exception as exc:  # provider boundary: persist error, do not fabricate fallback evidence
            provider_errors.append({
                "requirement_id": requirement_id,
                "error": str(exc),
            })
            receipts = []

        accepted_for_task = 0
        for receipt in receipts:
            try:
                promoted = promote_discovery_receipt(
                    receipt,
                    task,
                    historical_cutoff=request.get("historical_cutoff"),
                )
            except CivoraDiscoveryError as exc:
                rejected_candidates.append({
                    "requirement_id": requirement_id,
                    "candidate_id": receipt.get("candidate_id"),
                    "accepted": False,
                    "failures": str(exc).split(","),
                })
                continue
            ids = []
            for record in promoted["evidence"]:
                evidence[str(record["id"])] = record
                ids.append(str(record["id"]))
            accepted_for_task += 1
            accepted_candidates.append({
                "requirement_id": requirement_id,
                "candidate_id": receipt.get("candidate_id"),
                "accepted": True,
                "evidence_ids": ids,
            })

        if accepted_for_task == 0:
            if task_type == "DISCOVERY_THEN_PRIMARY_IF_GAP":
                primary_research_queue.append({
                    "requirement_id": requirement_id,
                    "construct": task.get("construct"),
                    "reason": "external_discovery_did_not_close_gap",
                    "priority": task.get("priority"),
                })
            elif task.get("priority") == "primary":
                unresolved_external_primary.append({
                    "requirement_id": requirement_id,
                    "construct": task.get("construct"),
                    "reason": "no_accepted_external_evidence",
                })
            else:
                unresolved_external_supporting.append({
                    "requirement_id": requirement_id,
                    "construct": task.get("construct"),
                    "reason": "no_accepted_external_evidence",
                })

    if unresolved_external_primary or provider_errors:
        state = "BLOCKED_DISCOVERY"
    elif primary_research_queue:
        state = "READY_FOR_PRIMARY_RESEARCH"
    else:
        state = "READY_FOR_NEED_DISCOVERY"

    return {
        "schema_version": "nf.research_cycle.v0.1",
        "project_id": request.get("project_id"),
        "request_sha256": request.get("request_sha256"),
        "state": state,
        "evidence": evidence,
        "accepted_candidates": accepted_candidates,
        "rejected_candidates": rejected_candidates,
        "provider_errors": provider_errors,
        "primary_research_queue": primary_research_queue,
        "unresolved_external_primary": unresolved_external_primary,
        "unresolved_external_supporting": unresolved_external_supporting,
        "counts": {
            "evidence_records": len(evidence),
            "accepted_candidates": len(accepted_candidates),
            "rejected_candidates": len(rejected_candidates),
            "provider_errors": len(provider_errors),
            "primary_research_queue": len(primary_research_queue),
            "unresolved_external_primary": len(unresolved_external_primary),
            "unresolved_external_supporting": len(unresolved_external_supporting),
        },
        "policy": {
            "provider_failure_never_fabricates_evidence": True,
            "primary_research_tasks_not_sent_to_external_discovery": True,
            "hybrid_tasks_fall_back_to_primary_research_only_after_discovery_gap": True,
        },
    }
