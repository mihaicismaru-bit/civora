#!/usr/bin/env python3
"""Executable P11 contract for fail-closed opportunity intelligence records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "1.0"
AUTHORITATIVE_TIERS = frozenset({"T1", "T1B"})
MATERIAL_FACT_CLASSES = frozenset(
    {"status", "deadline", "budget", "grant", "eligibility", "scoring", "beneficiaries"}
)
ALLOWED_STATUSES = frozenset(
    {"DISCOVERED", "EXPECTED", "PUBLIC_CONSULTATION", "OPEN", "CLOSED", "SUSPENDED", "CANCELLED"}
)
ACTIONABLE_STATUSES = frozenset({"OPEN"})


class ContractViolation(ValueError):
    """Raised when a P11 record would weaken provenance or fail-closed policy."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractViolation(message)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class EvidenceIndex:
    rows: Mapping[str, Mapping[str, Any]]

    @classmethod
    def build(cls, evidence: Iterable[Mapping[str, Any]]) -> "EvidenceIndex":
        rows: dict[str, Mapping[str, Any]] = {}
        for item in evidence:
            evidence_id = item.get("evidence_id")
            _require(_non_empty_string(evidence_id), "Evidence.evidence_id is required")
            _require(evidence_id not in rows, f"duplicate evidence_id: {evidence_id}")
            _require(item.get("schema_version") == SCHEMA_VERSION, f"unsupported Evidence schema: {evidence_id}")
            _require(item.get("source_tier") in {"T1", "T1B", "T2", "T3"}, f"invalid source tier: {evidence_id}")
            _require(_non_empty_string(item.get("source_url")), f"source_url is required: {evidence_id}")
            _require(_non_empty_string(item.get("observed_at")), f"observed_at is required: {evidence_id}")
            _require(_non_empty_string(item.get("semantic_sha256")), f"semantic_sha256 is required: {evidence_id}")
            _require(item.get("semantic_verdict") in {"VERIFIED", "UNRESOLVED", "REJECTED"}, f"invalid semantic verdict: {evidence_id}")
            rows[evidence_id] = item
        return cls(rows)

    def authoritative_verified(self, evidence_id: str) -> bool:
        item = self.rows.get(evidence_id) or {}
        return (
            item.get("source_tier") in AUTHORITATIVE_TIERS
            and item.get("semantic_verdict") == "VERIFIED"
            and bool(item.get("supports_fact_classes"))
        )

    def supports(self, evidence_id: str, fact_class: str) -> bool:
        item = self.rows.get(evidence_id) or {}
        return self.authoritative_verified(evidence_id) and fact_class in set(item.get("supports_fact_classes") or [])

    def supports_any(self, refs: Iterable[str]) -> bool:
        return any(self.authoritative_verified(ref) for ref in refs)


def validate_opportunity(item: Mapping[str, Any], evidence: EvidenceIndex) -> None:
    opportunity_id = item.get("opportunity_id")
    _require(item.get("schema_version") == SCHEMA_VERSION, f"unsupported Opportunity schema: {opportunity_id}")
    _require(_non_empty_string(opportunity_id), "Opportunity.opportunity_id is required")
    _require(_non_empty_string(item.get("title")), f"title is required: {opportunity_id}")
    _require(item.get("status") in ALLOWED_STATUSES, f"invalid status: {opportunity_id}")
    _require(item.get("publication_state") in {"QUARANTINED", "REVIEW_REQUIRED", "PUBLISHABLE"}, f"invalid publication_state: {opportunity_id}")

    fact_evidence = item.get("fact_evidence") or {}
    _require(isinstance(fact_evidence, Mapping), f"fact_evidence must be an object: {opportunity_id}")
    for fact_class, refs in fact_evidence.items():
        _require(fact_class in MATERIAL_FACT_CLASSES, f"unknown material fact class: {fact_class}")
        _require(isinstance(refs, list) and refs, f"empty evidence refs for {fact_class}: {opportunity_id}")
        _require(any(evidence.supports(ref, fact_class) for ref in refs), f"no authoritative semantic evidence for {fact_class}: {opportunity_id}")

    if item.get("publication_state") == "PUBLISHABLE":
        _require(item.get("automatic_material_fact_update_allowed") is False, f"material auto-update must be false: {opportunity_id}")
        _require(evidence.supports_any(item.get("evidence_refs") or []), f"publishable opportunity lacks verified evidence: {opportunity_id}")

    if item.get("status") in ACTIONABLE_STATUSES:
        _require(any(evidence.supports(ref, "status") for ref in fact_evidence.get("status", [])), f"OPEN lacks authoritative status evidence: {opportunity_id}")
        _require(any(evidence.supports(ref, "deadline") for ref in fact_evidence.get("deadline", [])), f"OPEN lacks authoritative deadline evidence: {opportunity_id}")


def validate_changeset(item: Mapping[str, Any], evidence: EvidenceIndex) -> None:
    changeset_id = item.get("changeset_id")
    _require(item.get("schema_version") == SCHEMA_VERSION, f"unsupported ChangeSet schema: {changeset_id}")
    _require(_non_empty_string(changeset_id), "ChangeSet.changeset_id is required")
    _require(_non_empty_string(item.get("opportunity_id")), f"opportunity_id is required: {changeset_id}")
    _require(item.get("automatic_publish_allowed") is False, f"automatic_publish_allowed must be false: {changeset_id}")
    changes = item.get("changes") or []
    _require(isinstance(changes, list) and changes, f"changes are required: {changeset_id}")
    for change in changes:
        fact_class = change.get("fact_class")
        _require(fact_class in MATERIAL_FACT_CLASSES, f"unknown ChangeSet fact class: {fact_class}")
        _require("before" in change and "after" in change, f"before/after required for {fact_class}: {changeset_id}")
        refs = change.get("evidence_refs") or []
        _require(any(evidence.supports(ref, fact_class) for ref in refs), f"unresolved material change {fact_class}: {changeset_id}")
    _require(item.get("resolution_state") in {"PENDING", "VERIFIED", "REJECTED"}, f"invalid resolution_state: {changeset_id}")


def validate_resolution_task(item: Mapping[str, Any]) -> None:
    task_id = item.get("resolution_task_id")
    _require(item.get("schema_version") == SCHEMA_VERSION, f"unsupported ResolutionTask schema: {task_id}")
    _require(_non_empty_string(task_id), "ResolutionTask.resolution_task_id is required")
    _require(_non_empty_string(item.get("opportunity_id")), f"opportunity_id is required: {task_id}")
    _require(item.get("automatic_material_fact_update_allowed") is False, f"material auto-update must be false: {task_id}")
    blocked = set(item.get("blocked_fact_classes") or [])
    _require(blocked and blocked <= MATERIAL_FACT_CLASSES, f"invalid blocked_fact_classes: {task_id}")
    _require(item.get("status") in {"OPEN", "IN_REVIEW", "RESOLVED", "REJECTED"}, f"invalid task status: {task_id}")


def validate_bundle(bundle: Mapping[str, Any]) -> dict[str, int]:
    _require(bundle.get("schema_version") == SCHEMA_VERSION, "unsupported P11 bundle schema")
    evidence_rows = bundle.get("evidence") or []
    evidence = EvidenceIndex.build(evidence_rows)
    opportunities = bundle.get("opportunities") or []
    changesets = bundle.get("changesets") or []
    tasks = bundle.get("resolution_tasks") or []
    ids: set[str] = set()
    for item in opportunities:
        validate_opportunity(item, evidence)
        opportunity_id = item["opportunity_id"]
        _require(opportunity_id not in ids, f"duplicate opportunity_id: {opportunity_id}")
        ids.add(opportunity_id)
    for item in changesets:
        validate_changeset(item, evidence)
        _require(item["opportunity_id"] in ids, f"orphan ChangeSet: {item.get('changeset_id')}")
    for item in tasks:
        validate_resolution_task(item)
        _require(item["opportunity_id"] in ids, f"orphan ResolutionTask: {item.get('resolution_task_id')}")
    return {
        "opportunities": len(opportunities),
        "evidence": len(evidence_rows),
        "changesets": len(changesets),
        "resolution_tasks": len(tasks),
    }
