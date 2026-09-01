#!/usr/bin/env python3
"""Fail-closed semantic reconciliation for Creative Europe programme-wide F&T watch evidence.

This layer compares two immutable programme-watch snapshots produced by
``CREATIVE_EUROPE_FT_PROGRAMME_WATCH_V1``. It detects bounded discovery changes
and emits a prioritized queue for exact-topic verification, but it never treats
programme discovery as call truth and never authorizes material facts,
publication, distribution, or alerts.

A degraded current structured source is handled as source-health evidence only:
previous healthy evidence may be referenced as LKG provenance, but it is never
used to infer current OPEN/status/deadline/budget/eligibility facts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any, Mapping

from creative_europe_ft_watch import (
    MATERIAL_FLAGS,
    REF_RE,
    canonical_json,
    validate_watch_evidence,
)

RECONCILER_ID = "CREATIVE_EUROPE_FT_WATCH_RECONCILE_V1"
SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_WATCH_RECONCILIATION_V1"
MAX_EXACT_HANDOFFS = 20
PRIORITY_THRESHOLD = 90
CANDIDATE_SEMANTIC_FIELDS = (
    "reference",
    "status_code",
    "status_label_candidate",
    "candidate_observation_state",
    "programme_candidate",
    "call_identifier_candidate",
    "deadline_candidate",
    "authority_url_candidate",
)
ALLOWED_STATES = {
    "BASELINE_CAPTURED_NON_AUTHORIZING",
    "NO_CHANGE",
    "PROGRAMME_WATCH_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
    "CURRENT_SOURCE_DEGRADED_LKG_REFERENCED_NON_AUTHORIZING",
    "CURRENT_SOURCE_DEGRADED_NO_LKG_NON_AUTHORIZING",
    "SOURCE_RECOVERED_BASELINE_REESTABLISHED_NON_AUTHORIZING",
}


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _parse_utc(value: str) -> dt.datetime:
    text = str(value or "")
    if not text:
        raise ValueError("fetched_at is required")
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _candidate_semantic(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {field: candidate.get(field) for field in CANDIDATE_SEMANTIC_FIELDS}


def _watch_semantic_basis(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "references": [
            {
                "reference": candidate.get("reference"),
                "status_code": candidate.get("status_code"),
                "status_label_candidate": candidate.get("status_label_candidate"),
                "candidate_observation_state": candidate.get("candidate_observation_state"),
                "semantic_fingerprint": candidate.get("semantic_fingerprint"),
            }
            for candidate in (evidence.get("candidates") or [])
        ],
        "conflict_references": [
            conflict.get("reference") for conflict in (evidence.get("conflicts") or [])
        ],
    }


def _scope_payload(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "watch_id": evidence.get("watch_id"),
        "source_family": evidence.get("source_family"),
        "programme_family": evidence.get("programme_family"),
        "authority_class": evidence.get("authority_class"),
        "search_text": evidence.get("search_text"),
        "query": evidence.get("query"),
    }


def _validate_immutable_watch(evidence: Mapping[str, Any], *, label: str) -> str:
    validate_watch_evidence(evidence)
    for candidate in evidence.get("candidates") or []:
        expected = _sha256(_candidate_semantic(candidate))
        if candidate.get("semantic_fingerprint") != expected:
            raise ValueError(f"{label}: candidate semantic fingerprint does not bind evidence: {candidate.get('reference')}")
    expected_watch = _sha256(_watch_semantic_basis(evidence))
    if evidence.get("semantic_fingerprint") != expected_watch:
        raise ValueError(f"{label}: programme-watch semantic fingerprint does not bind evidence")
    return _sha256(dict(evidence))


def _candidate_map(evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(candidate.get("reference") or "").upper(): candidate
        for candidate in (evidence.get("candidates") or [])
    }


def _conflict_refs(evidence: Mapping[str, Any]) -> set[str]:
    return {
        str(conflict.get("reference") or "").upper()
        for conflict in (evidence.get("conflicts") or [])
        if conflict.get("reference")
    }


def _queue_entry(
    reference: str,
    *,
    reason: str,
    current: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = current or previous or {}
    entry: dict[str, Any] = {
        "reference": reference,
        "reason": reason,
        "priority": int(source.get("priority") or 0),
        "current_candidate_observation_state": current.get("candidate_observation_state") if current else None,
        "previous_candidate_observation_state": previous.get("candidate_observation_state") if previous else None,
        "authority_url_candidate": source.get("authority_url_candidate"),
        "authority_url_verified": False,
        "requires_exact_topic_readback": True,
        "requires_exact_topic_reconcile": True,
        "requires_material_admission": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        entry[key] = False
    return entry


def _priority_queue(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    state: str,
    added: list[str],
    removed: list[str],
    changed: list[str],
) -> list[dict[str, Any]]:
    current_map = _candidate_map(current)
    previous_map = _candidate_map(previous or {})
    queue: list[dict[str, Any]] = []

    if state in {"BASELINE_CAPTURED_NON_AUTHORIZING", "SOURCE_RECOVERED_BASELINE_REESTABLISHED_NON_AUTHORIZING"}:
        for ref, candidate in current_map.items():
            if int(candidate.get("priority") or 0) >= PRIORITY_THRESHOLD:
                queue.append(_queue_entry(ref, reason="PRIORITY_BASELINE_OR_RECOVERY", current=candidate, previous=None))
    elif state == "PROGRAMME_WATCH_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING":
        for ref in changed:
            queue.append(_queue_entry(
                ref,
                reason="REFERENCE_SEMANTIC_CHANGED",
                current=current_map.get(ref),
                previous=previous_map.get(ref),
            ))
        for ref in added:
            candidate = current_map.get(ref)
            if candidate and int(candidate.get("priority") or 0) >= PRIORITY_THRESHOLD:
                queue.append(_queue_entry(
                    ref,
                    reason="NEW_PRIORITY_REFERENCE",
                    current=candidate,
                    previous=None,
                ))
        for ref in removed:
            candidate = previous_map.get(ref)
            if candidate and int(candidate.get("priority") or 0) >= PRIORITY_THRESHOLD:
                queue.append(_queue_entry(
                    ref,
                    reason="PRIORITY_REFERENCE_DISAPPEARED",
                    current=None,
                    previous=candidate,
                ))

    dedup: dict[str, dict[str, Any]] = {}
    reason_rank = {
        "REFERENCE_SEMANTIC_CHANGED": 3,
        "PRIORITY_REFERENCE_DISAPPEARED": 2,
        "NEW_PRIORITY_REFERENCE": 1,
        "PRIORITY_BASELINE_OR_RECOVERY": 0,
    }
    for item in queue:
        ref = item["reference"]
        existing = dedup.get(ref)
        if existing is None or reason_rank.get(item["reason"], 0) > reason_rank.get(existing["reason"], 0):
            dedup[ref] = item
    ordered = sorted(
        dedup.values(),
        key=lambda item: (-int(item.get("priority") or 0), -reason_rank.get(str(item.get("reason")), 0), item["reference"]),
    )
    return ordered[:MAX_EXACT_HANDOFFS]


def reconcile_watch(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
    *,
    reconciled_at: str | None = None,
) -> dict[str, Any]:
    current_sha = _validate_immutable_watch(current, label="current")
    current_time = _parse_utc(str(current.get("fetched_at") or ""))
    current_scope = _scope_payload(current)
    scope_fingerprint = _sha256(current_scope)

    previous_sha: str | None = None
    if previous is not None:
        previous_sha = _validate_immutable_watch(previous, label="previous")
        previous_time = _parse_utc(str(previous.get("fetched_at") or ""))
        if previous_time > current_time:
            raise ValueError("previous Creative Europe programme-watch evidence is newer than current evidence")
        if _scope_payload(previous) != current_scope:
            raise ValueError("Creative Europe programme-watch scope changed; capture a new baseline instead of reconciling")

    if reconciled_at:
        reconciled_time = _parse_utc(reconciled_at)
    else:
        reconciled_time = dt.datetime.now(dt.timezone.utc)
    if reconciled_time < current_time:
        raise ValueError("reconciled_at predates current Creative Europe programme-watch evidence")

    current_health = str(current.get("source_health") or "")
    previous_health = str(previous.get("source_health") or "") if previous is not None else None
    current_map = _candidate_map(current)
    previous_map = _candidate_map(previous or {})
    current_conflicts = _conflict_refs(current)
    previous_conflicts = _conflict_refs(previous or {})

    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    conflict_added: list[str] = []
    conflict_resolved: list[str] = []
    changes: list[dict[str, Any]] = []

    lkg_reference_available = False
    lkg_evidence_sha256: str | None = None
    source_health_watch_candidate = False
    programme_watch_candidate = False
    conflict_watch_candidate = False

    if current_health != "HEALTHY":
        if previous is not None and previous_health == "HEALTHY":
            state = "CURRENT_SOURCE_DEGRADED_LKG_REFERENCED_NON_AUTHORIZING"
            lkg_reference_available = True
            lkg_evidence_sha256 = previous_sha
        else:
            state = "CURRENT_SOURCE_DEGRADED_NO_LKG_NON_AUTHORIZING"
        source_health_watch_candidate = True
    elif previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    elif previous_health != "HEALTHY":
        state = "SOURCE_RECOVERED_BASELINE_REESTABLISHED_NON_AUTHORIZING"
        source_health_watch_candidate = True
    else:
        added = sorted(set(current_map) - set(previous_map))
        removed = sorted(set(previous_map) - set(current_map))
        changed = sorted(
            ref for ref in (set(current_map) & set(previous_map))
            if current_map[ref].get("semantic_fingerprint") != previous_map[ref].get("semantic_fingerprint")
        )
        conflict_added = sorted(current_conflicts - previous_conflicts)
        conflict_resolved = sorted(previous_conflicts - current_conflicts)

        for ref in added:
            changes.append({"change_type": "REFERENCE_ADDED", "reference": ref})
        for ref in removed:
            changes.append({"change_type": "REFERENCE_REMOVED", "reference": ref})
        for ref in changed:
            before = previous_map[ref]
            after = current_map[ref]
            changed_fields = [
                field for field in CANDIDATE_SEMANTIC_FIELDS
                if before.get(field) != after.get(field)
            ]
            changes.append({
                "change_type": "REFERENCE_SEMANTIC_CHANGED",
                "reference": ref,
                "changed_fields": changed_fields,
                "previous_semantic_fingerprint": before.get("semantic_fingerprint"),
                "current_semantic_fingerprint": after.get("semantic_fingerprint"),
            })
        for ref in conflict_added:
            changes.append({"change_type": "CONFLICT_ADDED", "reference": ref})
        for ref in conflict_resolved:
            changes.append({"change_type": "CONFLICT_RESOLVED", "reference": ref})

        programme_watch_candidate = bool(added or removed or changed)
        conflict_watch_candidate = bool(conflict_added or conflict_resolved)
        source_health_watch_candidate = conflict_watch_candidate
        state = (
            "PROGRAMME_WATCH_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            if changes else "NO_CHANGE"
        )

    exact_queue = _priority_queue(
        current,
        previous,
        state=state,
        added=added,
        removed=removed,
        changed=changed,
    )

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "adapter_id": RECONCILER_ID,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_STRUCTURED",
        "observation_state": "PROGRAMME_WIDE_SEMANTIC_RECONCILIATION_NON_AUTHORIZING",
        "source_scope_fingerprint": scope_fingerprint,
        "current_run_id": current.get("run_id"),
        "current_fetched_at": current.get("fetched_at"),
        "current_source_health": current_health,
        "current_evidence_sha256": current_sha,
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "previous_run_id": previous.get("run_id") if previous is not None else None,
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "previous_source_health": previous_health,
        "previous_evidence_sha256": previous_sha,
        "previous_semantic_fingerprint": previous.get("semantic_fingerprint") if previous is not None else None,
        "reconciled_at": reconciled_time.isoformat().replace("+00:00", "Z"),
        "reconciliation_state": state,
        "semantic_reconciliation_passed": True,
        "semantic_change_count": len(changes),
        "semantic_changed": bool(changes),
        "changes": changes,
        "added_references": added,
        "removed_references": removed,
        "changed_references": changed,
        "conflict_references_added": conflict_added,
        "conflict_references_resolved": conflict_resolved,
        "programme_watch_candidate": programme_watch_candidate,
        "source_health_watch_candidate": source_health_watch_candidate,
        "conflict_watch_candidate": conflict_watch_candidate,
        "lkg_reference_available": lkg_reference_available,
        "lkg_evidence_sha256": lkg_evidence_sha256,
        "lkg_material_fact_use": False,
        "exact_verification_queue": exact_queue,
        "exact_verification_queue_count": len(exact_queue),
        "exact_verification_queue_limit": MAX_EXACT_HANDOFFS,
        "market_intelligence_only": True,
        "requires_exact_topic_handoff": True,
        "requires_material_admission": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False

    receipt["reconciliation_fingerprint"] = _sha256({
        "source_scope_fingerprint": scope_fingerprint,
        "current_evidence_sha256": current_sha,
        "previous_evidence_sha256": previous_sha,
        "reconciliation_state": state,
        "changes": changes,
        "exact_verification_queue": [
            {"reference": item["reference"], "reason": item["reason"], "priority": item["priority"]}
            for item in exact_queue
        ],
        "lkg_evidence_sha256": lkg_evidence_sha256,
    })
    validate_watch_reconciliation(receipt)
    return receipt


def validate_watch_reconciliation(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("adapter_id") != RECONCILER_ID:
        raise ValueError("Creative Europe programme-watch reconciliation identity drift")
    if receipt.get("source_family") != "EU_DIRECT" or receipt.get("programme_family") != "CREATIVE_EUROPE":
        raise ValueError("Creative Europe programme-watch reconciliation family drift")
    if receipt.get("observation_state") != "PROGRAMME_WIDE_SEMANTIC_RECONCILIATION_NON_AUTHORIZING":
        raise ValueError("Creative Europe programme-watch reconciliation observation-state drift")
    if receipt.get("reconciliation_state") not in ALLOWED_STATES:
        raise ValueError("Creative Europe programme-watch reconciliation state drift")
    if receipt.get("semantic_reconciliation_passed") is not True:
        raise ValueError("Creative Europe programme-watch semantic reconciliation did not pass")
    if receipt.get("market_intelligence_only") is not True:
        raise ValueError("Creative Europe programme-watch reconciliation lost market-intelligence boundary")
    if receipt.get("requires_exact_topic_handoff") is not True or receipt.get("requires_material_admission") is not True:
        raise ValueError("Creative Europe programme-watch reconciliation lost downstream verification boundary")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe programme-watch reconciliation crossed publication boundary")
    if receipt.get("lkg_material_fact_use") is not False:
        raise ValueError("Creative Europe programme-watch LKG became material truth")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"Creative Europe programme-watch reconciliation became authorizing: {key}")
    for key in ("source_scope_fingerprint", "current_evidence_sha256", "current_semantic_fingerprint", "reconciliation_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(key) or "")):
            raise ValueError(f"Creative Europe programme-watch reconciliation hash invalid: {key}")
    if receipt.get("previous_run_id") is not None:
        for key in ("previous_evidence_sha256", "previous_semantic_fingerprint"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(key) or "")):
                raise ValueError(f"Creative Europe previous programme-watch hash invalid: {key}")
    if receipt.get("lkg_reference_available") is True:
        if receipt.get("reconciliation_state") != "CURRENT_SOURCE_DEGRADED_LKG_REFERENCED_NON_AUTHORIZING":
            raise ValueError("Creative Europe programme-watch LKG reference escaped degraded-source state")
        if receipt.get("lkg_evidence_sha256") != receipt.get("previous_evidence_sha256"):
            raise ValueError("Creative Europe programme-watch LKG does not bind previous evidence")
    elif receipt.get("lkg_evidence_sha256") is not None:
        raise ValueError("Creative Europe programme-watch unexpected LKG hash")

    changes = list(receipt.get("changes") or [])
    if int(receipt.get("semantic_change_count") or 0) != len(changes):
        raise ValueError("Creative Europe programme-watch semantic change count drift")
    if bool(receipt.get("semantic_changed")) != bool(changes):
        raise ValueError("Creative Europe programme-watch semantic changed flag drift")

    queue = list(receipt.get("exact_verification_queue") or [])
    if len(queue) != int(receipt.get("exact_verification_queue_count") or 0):
        raise ValueError("Creative Europe exact verification queue count drift")
    if len(queue) > int(receipt.get("exact_verification_queue_limit") or 0):
        raise ValueError("Creative Europe exact verification queue exceeded bounded limit")
    seen: set[str] = set()
    for item in queue:
        ref = str(item.get("reference") or "").upper()
        if not REF_RE.fullmatch(ref) or ref in seen:
            raise ValueError(f"Creative Europe exact verification queue reference invalid/duplicate: {ref}")
        seen.add(ref)
        if item.get("authority_url_verified") is not False:
            raise ValueError(f"Creative Europe exact verification queue self-verified authority: {ref}")
        if item.get("requires_exact_topic_readback") is not True or item.get("requires_exact_topic_reconcile") is not True:
            raise ValueError(f"Creative Europe exact verification queue lost exact-topic boundary: {ref}")
        if item.get("requires_material_admission") is not True:
            raise ValueError(f"Creative Europe exact verification queue skipped material admission: {ref}")
        if item.get("publication_effect") != "NONE" or item.get("canonical_corpus_mutation") is not False:
            raise ValueError(f"Creative Europe exact verification queue crossed publication boundary: {ref}")
        for key in MATERIAL_FLAGS:
            if item.get(key) is not False:
                raise ValueError(f"Creative Europe exact verification queue became authorizing: {ref} {key}")

    if str(receipt.get("current_source_health") or "") != "HEALTHY":
        if queue:
            raise ValueError("degraded Creative Europe programme watch emitted exact verification queue")
        if receipt.get("programme_watch_candidate") is not False:
            raise ValueError("degraded Creative Europe programme watch emitted programme change candidate")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", type=pathlib.Path, required=True)
    parser.add_argument("--previous", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    receipt = reconcile_watch(current, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "exact_verification_queue_count": receipt["exact_verification_queue_count"],
        "programme_watch_candidate": receipt["programme_watch_candidate"],
        "open_call_authorized": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
