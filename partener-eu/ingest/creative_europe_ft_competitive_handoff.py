#!/usr/bin/env python3
"""Bounded live handoff for Creative Europe competitive/cascading calls.

Consumes immutable programme-wide watch evidence, selects at most one useful
OPEN/FORTHCOMING competitive opportunity, performs exact Funding & Tenders
readback, and reconciles it against latest same-identity exact evidence.

If the current healthy programme scan omits a previously observed active type-8
record, a previous same-scope active discovery may be replayed strictly as a
handoff pointer. The exact adapter must then establish current truth itself.
CLOSED/UNKNOWN discoveries are never fanned out merely because they are new.

F&T status labels remain Facet-derived. For competitive ids, the Facet search is
scoped to the parent CREA-* reference that produced the type-8 row; the exact
structured status code is still resolved only from the official Facet payload.

Everything here is evidence-only and non-authorizing. Separate material
admission remains mandatory.
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
import creative_europe_ft_competitive_reconcile as exact_reconcile
from creative_europe_ft_watch import MATERIAL_FLAGS, canonical_json, validate_watch_evidence

HANDOFF_ID = "CREATIVE_EUROPE_FT_COMPETITIVE_HANDOFF_V1"
SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_COMPETITIVE_HANDOFF_EXECUTION_V1"
NO_HANDOFF_STATE = "NO_BOUNDED_COMPETITIVE_HANDOFF_PENDING_NON_AUTHORIZING"
EXECUTED_STATE = "COMPETITIVE_HANDOFF_EXECUTED_NON_AUTHORIZING"
FAILED_STATE = "COMPETITIVE_HANDOFF_FAILED_CLOSED_NON_AUTHORIZING"
MAX_CANDIDATES = 50
ACTIVE_STATES = {
    "OPEN_CANDIDATE_NON_AUTHORIZING",
    "FORTHCOMING_CANDIDATE_NON_AUTHORIZING",
}


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _parse_utc(value: str) -> dt.datetime:
    text = str(value or "")
    if not text:
        raise ValueError("timestamp is required")
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _candidate_priority(candidate: Mapping[str, Any]) -> int:
    return 100 if candidate.get("candidate_observation_state") == "OPEN_CANDIDATE_NON_AUTHORIZING" else 90


def _validate_bounded_candidate(candidate: Mapping[str, Any]) -> None:
    competitive_id = str(candidate.get("competitive_call_id_candidate") or "")
    identity = str(candidate.get("identity_key") or "")
    parent = str(candidate.get("parent_reference") or "").upper()
    exact.validate_competitive_id(competitive_id)
    exact.validate_reference(parent)
    if identity != f"FUNDING_TENDERS_COMPETITIVE_CALL:{competitive_id}":
        raise ValueError("competitive handoff candidate identity/id mismatch")
    if candidate.get("authority_url_candidate") != exact.competitive_url(competitive_id):
        raise ValueError("competitive handoff candidate authority URL mismatch")
    if candidate.get("authority_url_verified") is not False:
        raise ValueError("competitive handoff candidate self-verified authority")
    if candidate.get("opportunity_class") != "COMPETITIVE_CASCADING_CALL":
        raise ValueError("competitive handoff opportunity class drift")
    for key in (
        "requires_separate_competitive_call_adapter",
        "requires_exact_competitive_call_authority_readback",
        "requires_semantic_reconcile",
        "requires_material_admission",
    ):
        if candidate.get(key) is not True:
            raise ValueError(f"competitive handoff candidate skipped gate: {key}")
    if candidate.get("publication_effect") != "NONE" or candidate.get("canonical_corpus_mutation") is not False:
        raise ValueError("competitive handoff candidate crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if candidate.get(key) is not False:
            raise ValueError(f"competitive handoff candidate became authorizing: {key}")
    for key in ("record_sha256", "semantic_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get(key) or "")):
            raise ValueError(f"competitive handoff candidate hash invalid: {key}")


def _bounded_candidates(watch: Mapping[str, Any], *, active_only: bool = False) -> list[dict[str, Any]]:
    validate_watch_evidence(watch)
    if watch.get("source_health") != "HEALTHY":
        return []
    rows = list(watch.get("linked_competitive_discovery") or [])
    if len(rows) > MAX_CANDIDATES:
        raise ValueError("competitive discovery candidate count exceeds bounded handoff limit")
    bounded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        candidate = dict(raw)
        identity = str(candidate.get("identity_key") or "")
        if not identity.startswith("FUNDING_TENDERS_COMPETITIVE_CALL:"):
            continue
        _validate_bounded_candidate(candidate)
        if identity in seen:
            raise ValueError(f"duplicate bounded competitive identity in watch: {identity}")
        seen.add(identity)
        if active_only and candidate.get("candidate_observation_state") not in ACTIVE_STATES:
            continue
        bounded.append(candidate)
    bounded.sort(key=lambda item: (-_candidate_priority(item) if item.get("candidate_observation_state") in ACTIVE_STATES else 0, str(item.get("parent_reference") or ""), str(item.get("identity_key") or "")))
    return bounded


def _history_exact_evidence(history_root: pathlib.Path | None, identity_key: str, *, not_after: dt.datetime | None = None) -> list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]]:
    if history_root is None or not history_root.exists():
        return []
    found: list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]] = []
    for path in history_root.rglob("ft-competitive-exact-evidence.json"):
        try:
            evidence = _load_json(path)
            exact.validate_exact_evidence(evidence)
            if str(evidence.get("identity_key") or "") != identity_key:
                continue
            observed = _parse_utc(str(evidence.get("fetched_at") or ""))
            if not_after is not None and observed > not_after:
                continue
            found.append((observed, path, evidence))
        except Exception:
            continue
    found.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
    return found


def _history_watches(history_root: pathlib.Path | None, current_watch: Mapping[str, Any]) -> list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]]:
    if history_root is None or not history_root.exists():
        return []
    current_time = _parse_utc(str(current_watch.get("fetched_at") or ""))
    found: list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]] = []
    for path in history_root.rglob("ft-programme-watch-evidence.json"):
        try:
            previous = _load_json(path)
            validate_watch_evidence(previous)
            observed = _parse_utc(str(previous.get("fetched_at") or ""))
            if observed >= current_time:
                continue
            if previous.get("search_text") != current_watch.get("search_text") or previous.get("query") != current_watch.get("query"):
                continue
            found.append((observed, path, previous))
        except Exception:
            continue
    found.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
    return found


def select_candidate(watch: Mapping[str, Any], *, history_root: pathlib.Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Select at most one active candidate; replay prior active discovery if needed."""
    validate_watch_evidence(watch)
    if watch.get("source_health") != "HEALTHY":
        return None, None

    active = _bounded_candidates(watch, active_only=True)
    current_identities = {str(c.get("identity_key") or "") for c in _bounded_candidates(watch)}
    active_refresh: list[tuple[dt.datetime, dict[str, Any]]] = []
    for candidate in active:
        identity = str(candidate["identity_key"])
        history = _history_exact_evidence(history_root, identity)
        if not history:
            return candidate, "NEW_ACTIVE_BOUNDED_COMPETITIVE_IDENTITY"
        observed, _path, previous = history[0]
        if previous.get("source_candidate_semantic_fingerprint") != candidate.get("semantic_fingerprint"):
            return candidate, "ACTIVE_DISCOVERY_SEMANTIC_FINGERPRINT_CHANGED"
        active_refresh.append((observed, candidate))

    # A volatile programme-wide search may omit a previously observed active
    # type-8 row. Reuse only the immutable prior candidate as a pointer into an
    # exact current readback; never treat the prior OPEN candidate as current truth.
    for _watch_time, _path, previous_watch in _history_watches(history_root, watch):
        for candidate in _bounded_candidates(previous_watch, active_only=True):
            identity = str(candidate["identity_key"])
            if identity in current_identities:
                continue
            history = _history_exact_evidence(history_root, identity)
            previous_watch_time = _parse_utc(str(previous_watch.get("fetched_at") or ""))
            if any(observed >= previous_watch_time for observed, _p, _e in history):
                continue
            return candidate, "PREVIOUS_ACTIVE_DISCOVERY_PENDING_EXACT_RECHECK"

    if active_refresh:
        active_refresh.sort(key=lambda item: (item[0], str(item[1].get("identity_key") or "")))
        return active_refresh[0][1], "ACTIVE_CANDIDATE_FRESHNESS_REFRESH"
    return None, None


def _scoped_structured_post(parent_reference: str, base_post: Callable[..., tuple[Any, bytes, dict[str, Any]]]) -> Callable[..., tuple[Any, bytes, dict[str, Any]]]:
    parent_reference = exact.validate_reference(parent_reference)

    def post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
        scoped_text = parent_reference if endpoint == exact.ft.FACET_ENDPOINT else text
        return base_post(endpoint, text=scoped_text, page_size=page_size, page_number=page_number, parts=parts, max_bytes=max_bytes, opener=opener)

    return post


def _base_summary(watch: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "handoff_id": HANDOFF_ID,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_COMPETITIVE_CALL",
        "run_id": run_id,
        "current_watch_evidence_sha256": _sha256(dict(watch)),
        "current_watch_semantic_fingerprint": watch.get("semantic_fingerprint"),
        "market_intelligence_only": True,
        "requires_material_admission": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        summary[key] = False
    return summary


def execute_handoff(watch: Mapping[str, Any], *, run_id: str, output_dir: pathlib.Path, history_root: pathlib.Path | None = None, post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] | None = None, readback_func: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    validate_watch_evidence(watch)
    if not str(run_id or "").strip():
        raise ValueError("run_id is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = _base_summary(watch, run_id=run_id)
    candidate, reason = select_candidate(watch, history_root=history_root)

    if candidate is None:
        summary.update({
            "observation_state": NO_HANDOFF_STATE, "selection_reason": None,
            "selected_identity_key": None, "selected_parent_reference": None,
            "selected_competitive_call_id": None, "source_candidate_semantic_fingerprint": None,
            "exact_evidence_sha256": None, "previous_exact_evidence_sha256": None,
            "exact_reconciliation_sha256": None, "exact_authority_url": None,
            "exact_authority_url_verified": False, "exact_candidate_observation_state": None,
            "exact_status_label": None, "exact_semantic_reconciliation_state": None,
            "exact_semantic_change_count": 0, "material_admission_ready_for_downstream_review": False,
            "retry_candidate": False,
        })
        validate_handoff_summary(summary)
        _write(output_dir / "competitive-handoff-summary.json", summary)
        return summary

    _validate_bounded_candidate(candidate)
    identity = str(candidate["identity_key"])
    parent = exact.validate_reference(str(candidate["parent_reference"]))
    competitive_id = exact.validate_competitive_id(str(candidate["competitive_call_id_candidate"]))
    selection: dict[str, Any] = {
        "schema": "PARTENER_EU_CREATIVE_EUROPE_FT_COMPETITIVE_HANDOFF_SELECTION_V1",
        "handoff_id": HANDOFF_ID,
        "selection_reason": reason,
        "identity_key": identity,
        "parent_reference": parent,
        "competitive_call_id": competitive_id,
        "authority_url_candidate": candidate.get("authority_url_candidate"),
        "authority_url_verified": False,
        "source_candidate_semantic_fingerprint": candidate.get("semantic_fingerprint"),
        "current_watch_evidence_sha256": summary["current_watch_evidence_sha256"],
        "requires_exact_competitive_call_authority_readback": True,
        "requires_semantic_reconcile": True,
        "requires_material_admission": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        selection[key] = False
    _write(output_dir / "competitive-handoff-selection.json", selection)

    base_post = post_func or exact.ft._safe_json_post
    kwargs: dict[str, Any] = {"post_func": _scoped_structured_post(parent, base_post)}
    if readback_func is not None:
        kwargs["readback_func"] = readback_func

    current_exact: dict[str, Any] | None = None
    previous_exact: dict[str, Any] | None = None
    reconciliation: dict[str, Any] | None = None
    try:
        current_exact = exact.collect_exact(parent, competitive_id, run_id=run_id, output_dir=output_dir / "current", source_candidate=candidate, **kwargs)
        current_time = _parse_utc(str(current_exact.get("fetched_at") or ""))
        history = _history_exact_evidence(history_root, identity, not_after=current_time)
        if history:
            _observed, previous_path, previous_exact = history[0]
            previous_dir = output_dir / "previous"
            previous_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(previous_path, previous_dir / "ft-competitive-exact-evidence.json")
        reconciliation = exact_reconcile.reconcile(current_exact, previous_exact)
        _write(output_dir / "reconciliation" / "ft-competitive-reconciliation.json", reconciliation)
    except Exception as exc:
        summary.update({
            "observation_state": FAILED_STATE, "selection_reason": reason,
            "selected_identity_key": identity, "selected_parent_reference": parent,
            "selected_competitive_call_id": competitive_id,
            "source_candidate_semantic_fingerprint": candidate.get("semantic_fingerprint"),
            "exact_evidence_sha256": None, "previous_exact_evidence_sha256": None,
            "exact_reconciliation_sha256": None, "exact_authority_url": exact.competitive_url(competitive_id),
            "exact_authority_url_verified": False, "exact_candidate_observation_state": None,
            "exact_status_label": None, "exact_semantic_reconciliation_state": None,
            "exact_semantic_change_count": 0, "material_admission_ready_for_downstream_review": False,
            "failure_stage": "EXACT_COMPETITIVE_FUNDING_TENDERS_ACQUISITION_OR_RECONCILIATION",
            "failure_type": type(exc).__name__, "failure_message": str(exc)[:1000], "retry_candidate": True,
        })
        validate_handoff_summary(summary)
        _write(output_dir / "competitive-handoff-summary.json", summary)
        return summary

    assert current_exact is not None and reconciliation is not None
    summary.update({
        "observation_state": EXECUTED_STATE, "selection_reason": reason,
        "selected_identity_key": identity, "selected_parent_reference": parent,
        "selected_competitive_call_id": competitive_id,
        "source_candidate_semantic_fingerprint": candidate.get("semantic_fingerprint"),
        "exact_evidence_sha256": _sha256(dict(current_exact)),
        "previous_exact_evidence_sha256": _sha256(dict(previous_exact)) if previous_exact is not None else None,
        "exact_reconciliation_sha256": _sha256(dict(reconciliation)),
        "exact_authority_url": current_exact.get("authority_url"),
        "exact_authority_url_verified": current_exact.get("authority_url_verified"),
        "exact_candidate_observation_state": current_exact.get("candidate_observation_state"),
        "exact_status_label": current_exact.get("status_label"),
        "exact_semantic_reconciliation_state": reconciliation.get("reconciliation_state"),
        "exact_semantic_change_count": int(reconciliation.get("semantic_change_count") or 0),
        "material_admission_ready_for_downstream_review": bool(reconciliation.get("material_admission_ready_for_downstream_review")),
        "retry_candidate": False,
    })
    validate_handoff_summary(summary)
    _write(output_dir / "competitive-handoff-summary.json", summary)
    return summary


def validate_handoff_summary(summary: Mapping[str, Any]) -> None:
    if summary.get("schema") != SCHEMA or summary.get("handoff_id") != HANDOFF_ID:
        raise ValueError("Creative Europe competitive handoff identity drift")
    if summary.get("source_family") != "EU_DIRECT" or summary.get("programme_family") != "CREATIVE_EUROPE":
        raise ValueError("Creative Europe competitive handoff programme boundary drift")
    if summary.get("market_intelligence_only") is not True or summary.get("requires_material_admission") is not True:
        raise ValueError("Creative Europe competitive handoff lost downstream boundary")
    if summary.get("publication_effect") != "NONE" or summary.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe competitive handoff crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if summary.get(key) is not False:
            raise ValueError(f"Creative Europe competitive handoff became authorizing: {key}")
    for key in ("current_watch_evidence_sha256", "current_watch_semantic_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get(key) or "")):
            raise ValueError(f"Creative Europe competitive handoff watch binding invalid: {key}")

    state = summary.get("observation_state")
    if state == NO_HANDOFF_STATE:
        if summary.get("selected_identity_key") is not None or summary.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("no-handoff competitive summary crossed downstream boundary")
        return

    competitive_id = exact.validate_competitive_id(str(summary.get("selected_competitive_call_id") or ""))
    if summary.get("selected_identity_key") != f"FUNDING_TENDERS_COMPETITIVE_CALL:{competitive_id}":
        raise ValueError("competitive handoff selected identity drift")
    exact.validate_reference(str(summary.get("selected_parent_reference") or ""))
    if not summary.get("selection_reason"):
        raise ValueError("competitive handoff selection reason missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get("source_candidate_semantic_fingerprint") or "")):
        raise ValueError("competitive handoff source-candidate binding invalid")

    if state == FAILED_STATE:
        if summary.get("exact_authority_url") != exact.competitive_url(competitive_id) or summary.get("exact_authority_url_verified") is not False:
            raise ValueError("failed competitive handoff authority boundary drift")
        if summary.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("failed competitive handoff claims material readiness")
        if summary.get("retry_candidate") is not True or not summary.get("failure_type") or not summary.get("failure_message"):
            raise ValueError("failed competitive handoff lacks durable failure evidence")
        return

    if state != EXECUTED_STATE:
        raise ValueError(f"unexpected Creative Europe competitive handoff state: {state}")
    if summary.get("exact_authority_url") != exact.competitive_url(competitive_id) or summary.get("exact_authority_url_verified") is not True:
        raise ValueError("competitive handoff exact authority verification drift")
    if summary.get("exact_candidate_observation_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
        raise ValueError("competitive handoff exact candidate state invalid")
    if summary.get("exact_semantic_reconciliation_state") not in {"BASELINE_CAPTURED_NON_AUTHORIZING", "NO_CHANGE", "EXACT_COMPETITIVE_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"}:
        raise ValueError("competitive handoff semantic reconciliation state invalid")
    for key in ("exact_evidence_sha256", "exact_reconciliation_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get(key) or "")):
            raise ValueError(f"competitive handoff hash invalid: {key}")
    previous = summary.get("previous_exact_evidence_sha256")
    if previous is not None and not re.fullmatch(r"[0-9a-f]{64}", str(previous)):
        raise ValueError("competitive handoff previous exact hash invalid")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-watch", type=pathlib.Path, required=True)
    parser.add_argument("--history-root", type=pathlib.Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    watch = _load_json(args.current_watch)
    summary = execute_handoff(watch, run_id=args.run_id, output_dir=args.output_dir, history_root=args.history_root)
    print(json.dumps({
        "observation_state": summary.get("observation_state"),
        "selection_reason": summary.get("selection_reason"),
        "selected_identity_key": summary.get("selected_identity_key"),
        "selected_parent_reference": summary.get("selected_parent_reference"),
        "exact_candidate_observation_state": summary.get("exact_candidate_observation_state"),
        "exact_status_label": summary.get("exact_status_label"),
        "exact_semantic_reconciliation_state": summary.get("exact_semantic_reconciliation_state"),
        "material_admission_ready_for_downstream_review": summary.get("material_admission_ready_for_downstream_review"),
        "failure_type": summary.get("failure_type"),
        "failure_message": summary.get("failure_message"),
        "open_call_authorized": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL Creative Europe competitive handoff: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
