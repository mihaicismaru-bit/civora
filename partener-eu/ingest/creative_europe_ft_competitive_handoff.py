#!/usr/bin/env python3
"""Bounded exact handoff for Creative Europe competitive/cascading calls.

Only active OPEN/FORTHCOMING type-8 discovery candidates are worth exact fan-out.
A previous same-scope active discovery may be replayed only as a pointer into a
new exact readback when the current healthy programme scan omits it. Neither the
current nor previous discovery candidate authorizes a material fact.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import sys
from typing import Any, Callable, Mapping

import creative_europe_ft_competitive_exact as exact
import creative_europe_ft_competitive_reconcile as reconcile_exact
from creative_europe_ft_watch import MATERIAL_FLAGS, canonical_json, validate_watch_evidence

HANDOFF_ID = "CREATIVE_EUROPE_FT_COMPETITIVE_HANDOFF_V1"
SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_COMPETITIVE_HANDOFF_EXECUTION_V1"
NO_HANDOFF_STATE = "NO_BOUNDED_COMPETITIVE_HANDOFF_PENDING_NON_AUTHORIZING"
EXECUTED_STATE = "COMPETITIVE_HANDOFF_EXECUTED_NON_AUTHORIZING"
FAILED_STATE = "COMPETITIVE_HANDOFF_FAILED_CLOSED_NON_AUTHORIZING"
ACTIVE_STATES = {"OPEN_CANDIDATE_NON_AUTHORIZING", "FORTHCOMING_CANDIDATE_NON_AUTHORIZING"}
MAX_CANDIDATES = 50


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_candidate(candidate: Mapping[str, Any]) -> None:
    cid = exact.validate_competitive_id(str(candidate.get("competitive_call_id_candidate") or ""))
    parent = exact.validate_reference(str(candidate.get("parent_reference") or ""))
    if candidate.get("identity_key") != f"FUNDING_TENDERS_COMPETITIVE_CALL:{cid}":
        raise ValueError("competitive candidate identity drift")
    if candidate.get("authority_url_candidate") != exact.competitive_url(cid):
        raise ValueError("competitive candidate authority URL drift")
    if candidate.get("authority_url_verified") is not False or candidate.get("opportunity_class") != "COMPETITIVE_CASCADING_CALL":
        raise ValueError("competitive candidate crossed discovery boundary")
    for key in ("requires_separate_competitive_call_adapter", "requires_exact_competitive_call_authority_readback", "requires_semantic_reconcile", "requires_material_admission"):
        if candidate.get(key) is not True:
            raise ValueError(f"competitive candidate skipped gate: {key}")
    if candidate.get("publication_effect") != "NONE" or candidate.get("canonical_corpus_mutation") is not False:
        raise ValueError("competitive candidate crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if candidate.get(key) is not False:
            raise ValueError(f"competitive candidate became authorizing: {key}")
    for key in ("record_sha256", "semantic_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get(key) or "")):
            raise ValueError(f"competitive candidate hash invalid: {key}")
    if parent != str(candidate.get("parent_reference") or "").upper():
        raise ValueError("competitive candidate parent identity drift")


def _bounded(watch: Mapping[str, Any], *, active_only: bool = False) -> list[dict[str, Any]]:
    validate_watch_evidence(watch)
    if watch.get("source_health") != "HEALTHY":
        return []
    rows = list(watch.get("linked_competitive_discovery") or [])
    if len(rows) > MAX_CANDIDATES:
        raise ValueError("competitive discovery exceeds bounded limit")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        item = dict(raw)
        identity = str(item.get("identity_key") or "")
        if not identity.startswith("FUNDING_TENDERS_COMPETITIVE_CALL:"):
            continue
        _validate_candidate(item)
        if identity in seen:
            raise ValueError(f"duplicate bounded competitive identity: {identity}")
        seen.add(identity)
        if active_only and item.get("candidate_observation_state") not in ACTIVE_STATES:
            continue
        output.append(item)
    output.sort(key=lambda x: (0 if x.get("candidate_observation_state") == "OPEN_CANDIDATE_NON_AUTHORIZING" else 1, str(x.get("identity_key") or "")))
    return output


def _exact_history(root: pathlib.Path | None, identity: str, *, not_after: dt.datetime | None = None) -> list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]]:
    if root is None or not root.exists():
        return []
    found = []
    for path in root.rglob("ft-competitive-exact-evidence.json"):
        try:
            evidence = _load(path)
            exact.validate_exact_evidence(evidence)
            if evidence.get("identity_key") != identity:
                continue
            observed = _time(str(evidence.get("fetched_at") or ""))
            if not_after is not None and observed > not_after:
                continue
            found.append((observed, path, evidence))
        except Exception:
            continue
    return sorted(found, key=lambda x: (x[0], str(x[1])), reverse=True)


def _watch_history(root: pathlib.Path | None, current: Mapping[str, Any]) -> list[dict[str, Any]]:
    if root is None or not root.exists():
        return []
    current_time = _time(str(current.get("fetched_at") or ""))
    found: list[tuple[dt.datetime, dict[str, Any]]] = []
    for path in root.rglob("ft-programme-watch-evidence.json"):
        try:
            previous = _load(path)
            validate_watch_evidence(previous)
            observed = _time(str(previous.get("fetched_at") or ""))
            if observed >= current_time:
                continue
            if previous.get("search_text") != current.get("search_text") or previous.get("query") != current.get("query"):
                continue
            found.append((observed, previous))
        except Exception:
            continue
    return [item for _time_value, item in sorted(found, key=lambda x: x[0], reverse=True)]


def select_candidate(watch: Mapping[str, Any], *, history_root: pathlib.Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    validate_watch_evidence(watch)
    if watch.get("source_health") != "HEALTHY":
        return None, None

    active = _bounded(watch, active_only=True)
    current_ids = {str(x.get("identity_key") or "") for x in _bounded(watch)}
    refresh: list[tuple[dt.datetime, dict[str, Any]]] = []
    for candidate in active:
        identity = str(candidate["identity_key"])
        history = _exact_history(history_root, identity)
        if not history:
            return candidate, "NEW_ACTIVE_BOUNDED_COMPETITIVE_IDENTITY"
        observed, _path, previous = history[0]
        if previous.get("source_candidate_semantic_fingerprint") != candidate.get("semantic_fingerprint"):
            return candidate, "ACTIVE_DISCOVERY_SEMANTIC_FINGERPRINT_CHANGED"
        refresh.append((observed, candidate))

    for previous_watch in _watch_history(history_root, watch):
        previous_time = _time(str(previous_watch.get("fetched_at") or ""))
        for candidate in _bounded(previous_watch, active_only=True):
            identity = str(candidate["identity_key"])
            if identity in current_ids:
                continue
            if any(observed >= previous_time for observed, _p, _e in _exact_history(history_root, identity)):
                continue
            return candidate, "PREVIOUS_ACTIVE_DISCOVERY_PENDING_EXACT_RECHECK"

    if refresh:
        refresh.sort(key=lambda x: (x[0], str(x[1].get("identity_key") or "")))
        return refresh[0][1], "ACTIVE_CANDIDATE_FRESHNESS_REFRESH"
    return None, None


def _facet_scoped_post(parent: str, base_post: Callable[..., tuple[Any, bytes, dict[str, Any]]]):
    parent = exact.validate_reference(parent)

    def post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
        kwargs = {"text": parent if endpoint == exact.ft.FACET_ENDPOINT else text, "page_size": page_size, "page_number": page_number, "parts": parts}
        if max_bytes is not None:
            kwargs["max_bytes"] = max_bytes
        if opener is not None:
            kwargs["opener"] = opener
        return base_post(endpoint, **kwargs)

    return post


def _base(watch: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    summary = {
        "schema": SCHEMA, "handoff_id": HANDOFF_ID, "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE", "authority_class": "EU_COMMISSION_FUNDING_TENDERS_COMPETITIVE_CALL",
        "run_id": run_id, "current_watch_evidence_sha256": _sha(dict(watch)),
        "current_watch_semantic_fingerprint": watch.get("semantic_fingerprint"), "market_intelligence_only": True,
        "requires_material_admission": True, "publication_effect": "NONE", "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        summary[key] = False
    return summary


def execute_handoff(watch: Mapping[str, Any], *, run_id: str, output_dir: pathlib.Path, history_root: pathlib.Path | None = None, post_func=None, readback_func=None) -> dict[str, Any]:
    validate_watch_evidence(watch)
    if not str(run_id or "").strip():
        raise ValueError("run_id is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = _base(watch, run_id)
    candidate, reason = select_candidate(watch, history_root=history_root)
    if candidate is None:
        summary.update({"observation_state": NO_HANDOFF_STATE, "selection_reason": None, "selected_identity_key": None, "selected_parent_reference": None, "selected_competitive_call_id": None, "source_candidate_semantic_fingerprint": None, "exact_evidence_sha256": None, "previous_exact_evidence_sha256": None, "exact_reconciliation_sha256": None, "exact_authority_url": None, "exact_authority_url_verified": False, "exact_candidate_observation_state": None, "exact_status_label": None, "exact_semantic_reconciliation_state": None, "exact_semantic_change_count": 0, "material_admission_ready_for_downstream_review": False, "retry_candidate": False})
        validate_handoff_summary(summary)
        _write(output_dir / "competitive-handoff-summary.json", summary)
        return summary

    _validate_candidate(candidate)
    identity = str(candidate["identity_key"])
    parent = exact.validate_reference(str(candidate["parent_reference"]))
    cid = exact.validate_competitive_id(str(candidate["competitive_call_id_candidate"]))
    selection = {"schema": "PARTENER_EU_CREATIVE_EUROPE_FT_COMPETITIVE_HANDOFF_SELECTION_V1", "handoff_id": HANDOFF_ID, "selection_reason": reason, "identity_key": identity, "parent_reference": parent, "competitive_call_id": cid, "authority_url_candidate": candidate.get("authority_url_candidate"), "authority_url_verified": False, "source_candidate_semantic_fingerprint": candidate.get("semantic_fingerprint"), "current_watch_evidence_sha256": summary["current_watch_evidence_sha256"], "requires_exact_competitive_call_authority_readback": True, "requires_semantic_reconcile": True, "requires_material_admission": True, "publication_effect": "NONE", "canonical_corpus_mutation": False}
    for key in MATERIAL_FLAGS:
        selection[key] = False
    _write(output_dir / "competitive-handoff-selection.json", selection)

    kwargs = {"post_func": _facet_scoped_post(parent, post_func or exact.ft._safe_json_post)}
    if readback_func is not None:
        kwargs["readback_func"] = readback_func
    try:
        current = exact.collect_exact(parent, cid, run_id=run_id, output_dir=output_dir / "current", source_candidate=candidate, **kwargs)
        history = _exact_history(history_root, identity, not_after=_time(str(current.get("fetched_at") or "")))
        previous = history[0][2] if history else None
        if history:
            previous_dir = output_dir / "previous"
            previous_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(history[0][1], previous_dir / "ft-competitive-exact-evidence.json")
        receipt = reconcile_exact.reconcile(current, previous)
        _write(output_dir / "reconciliation" / "ft-competitive-reconciliation.json", receipt)
    except Exception as exc:
        summary.update({"observation_state": FAILED_STATE, "selection_reason": reason, "selected_identity_key": identity, "selected_parent_reference": parent, "selected_competitive_call_id": cid, "source_candidate_semantic_fingerprint": candidate.get("semantic_fingerprint"), "exact_evidence_sha256": None, "previous_exact_evidence_sha256": None, "exact_reconciliation_sha256": None, "exact_authority_url": exact.competitive_url(cid), "exact_authority_url_verified": False, "exact_candidate_observation_state": None, "exact_status_label": None, "exact_semantic_reconciliation_state": None, "exact_semantic_change_count": 0, "material_admission_ready_for_downstream_review": False, "failure_stage": "EXACT_COMPETITIVE_FUNDING_TENDERS_ACQUISITION_OR_RECONCILIATION", "failure_type": type(exc).__name__, "failure_message": str(exc)[:1000], "retry_candidate": True})
        validate_handoff_summary(summary)
        _write(output_dir / "competitive-handoff-summary.json", summary)
        return summary

    summary.update({"observation_state": EXECUTED_STATE, "selection_reason": reason, "selected_identity_key": identity, "selected_parent_reference": parent, "selected_competitive_call_id": cid, "source_candidate_semantic_fingerprint": candidate.get("semantic_fingerprint"), "exact_evidence_sha256": _sha(dict(current)), "previous_exact_evidence_sha256": _sha(dict(previous)) if previous else None, "exact_reconciliation_sha256": _sha(dict(receipt)), "exact_authority_url": current.get("authority_url"), "exact_authority_url_verified": current.get("authority_url_verified"), "exact_candidate_observation_state": current.get("candidate_observation_state"), "exact_status_label": current.get("status_label"), "exact_semantic_reconciliation_state": receipt.get("reconciliation_state"), "exact_semantic_change_count": int(receipt.get("semantic_change_count") or 0), "material_admission_ready_for_downstream_review": bool(receipt.get("material_admission_ready_for_downstream_review")), "retry_candidate": False})
    validate_handoff_summary(summary)
    _write(output_dir / "competitive-handoff-summary.json", summary)
    return summary


def validate_handoff_summary(summary: Mapping[str, Any]) -> None:
    if summary.get("schema") != SCHEMA or summary.get("handoff_id") != HANDOFF_ID:
        raise ValueError("competitive handoff identity drift")
    if summary.get("source_family") != "EU_DIRECT" or summary.get("programme_family") != "CREATIVE_EUROPE":
        raise ValueError("competitive handoff programme boundary drift")
    if summary.get("market_intelligence_only") is not True or summary.get("requires_material_admission") is not True:
        raise ValueError("competitive handoff lost material boundary")
    if summary.get("publication_effect") != "NONE" or summary.get("canonical_corpus_mutation") is not False:
        raise ValueError("competitive handoff crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if summary.get(key) is not False:
            raise ValueError(f"competitive handoff became authorizing: {key}")
    for key in ("current_watch_evidence_sha256", "current_watch_semantic_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get(key) or "")):
            raise ValueError(f"competitive handoff watch hash invalid: {key}")
    state = summary.get("observation_state")
    if state == NO_HANDOFF_STATE:
        if summary.get("selected_identity_key") is not None or summary.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("no-handoff summary crossed downstream boundary")
        return
    cid = exact.validate_competitive_id(str(summary.get("selected_competitive_call_id") or ""))
    if summary.get("selected_identity_key") != f"FUNDING_TENDERS_COMPETITIVE_CALL:{cid}":
        raise ValueError("competitive handoff selected identity drift")
    exact.validate_reference(str(summary.get("selected_parent_reference") or ""))
    if not summary.get("selection_reason") or not re.fullmatch(r"[0-9a-f]{64}", str(summary.get("source_candidate_semantic_fingerprint") or "")):
        raise ValueError("competitive handoff selection evidence incomplete")
    if state == FAILED_STATE:
        if summary.get("exact_authority_url") != exact.competitive_url(cid) or summary.get("exact_authority_url_verified") is not False or summary.get("material_admission_ready_for_downstream_review") is not False or summary.get("retry_candidate") is not True or not summary.get("failure_type"):
            raise ValueError("failed competitive handoff boundary drift")
        return
    if state != EXECUTED_STATE:
        raise ValueError(f"unexpected competitive handoff state: {state}")
    if summary.get("exact_authority_url") != exact.competitive_url(cid) or summary.get("exact_authority_url_verified") is not True:
        raise ValueError("competitive handoff exact authority not verified")
    if summary.get("exact_candidate_observation_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
        raise ValueError("competitive exact candidate state invalid")
    if summary.get("exact_semantic_reconciliation_state") not in {"BASELINE_CAPTURED_NON_AUTHORIZING", "NO_CHANGE", "EXACT_COMPETITIVE_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"}:
        raise ValueError("competitive reconciliation state invalid")
    for key in ("exact_evidence_sha256", "exact_reconciliation_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get(key) or "")):
            raise ValueError(f"competitive handoff hash invalid: {key}")
    previous = summary.get("previous_exact_evidence_sha256")
    if previous is not None and not re.fullmatch(r"[0-9a-f]{64}", str(previous)):
        raise ValueError("competitive previous exact hash invalid")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-watch", type=pathlib.Path, required=True)
    parser.add_argument("--history-root", type=pathlib.Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    summary = execute_handoff(_load(args.current_watch), run_id=args.run_id, output_dir=args.output_dir, history_root=args.history_root)
    print(json.dumps({"observation_state": summary.get("observation_state"), "selection_reason": summary.get("selection_reason"), "selected_identity_key": summary.get("selected_identity_key"), "exact_candidate_observation_state": summary.get("exact_candidate_observation_state"), "exact_status_label": summary.get("exact_status_label"), "exact_semantic_reconciliation_state": summary.get("exact_semantic_reconciliation_state"), "material_admission_ready_for_downstream_review": summary.get("material_admission_ready_for_downstream_review"), "failure_type": summary.get("failure_type"), "failure_message": summary.get("failure_message"), "open_call_authorized": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL Creative Europe competitive handoff: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
