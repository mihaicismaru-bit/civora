#!/usr/bin/env python3
"""Bounded exact-topic handoff for Creative Europe programme-watch changes.

Consumes a non-authorizing programme-watch reconciliation, selects at most one
exact CREA-* topic, and runs the existing structured Funding & Tenders exact
adapter plus exact semantic reconciliation. A current exact-acquisition failure
is persisted as explicit fail-closed source evidence instead of being converted
into call truth or silently losing the pending handoff.
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

import creative_europe_ft_exact as exact
import creative_europe_ft_reconcile as exact_reconcile
from creative_europe_ft_watch import MATERIAL_FLAGS, REF_RE, canonical_json
from creative_europe_ft_watch_reconcile import validate_watch_reconciliation

HANDOFF_ID = "CREATIVE_EUROPE_FT_EXACT_HANDOFF_V1"
SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_EXACT_HANDOFF_EXECUTION_V1"
NO_HANDOFF_STATE = "NO_EXACT_HANDOFF_PENDING_NON_AUTHORIZING"
EXECUTED_STATE = "EXACT_HANDOFF_EXECUTED_NON_AUTHORIZING"
FAILED_STATE = "EXACT_HANDOFF_FAILED_CLOSED_NON_AUTHORIZING"
SELECTION_CURRENT = "CURRENT_RECONCILIATION"
SELECTION_PREVIOUS = "PREVIOUS_PENDING_RECONCILIATION"


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


def _history_watch_receipts(history_root: pathlib.Path | None) -> list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]]:
    if history_root is None or not history_root.exists():
        return []
    found: list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]] = []
    for path in history_root.rglob("ft-programme-watch-reconciliation.json"):
        try:
            receipt = _load_json(path)
            validate_watch_reconciliation(receipt)
            found.append((_parse_utc(str(receipt.get("reconciled_at") or "")), path, receipt))
        except Exception:
            continue
    found.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
    return found


def _history_exact_evidence(
    history_root: pathlib.Path | None,
    reference: str,
    *,
    not_after: dt.datetime | None = None,
) -> list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]]:
    if history_root is None or not history_root.exists():
        return []
    reference = exact.validate_reference(reference)
    found: list[tuple[dt.datetime, pathlib.Path, dict[str, Any]]] = []
    for path in history_root.rglob("ft-exact-evidence.json"):
        try:
            evidence = _load_json(path)
            exact.validate_exact_evidence(evidence)
            if str(evidence.get("reference") or "").upper() != reference:
                continue
            observed = _parse_utc(str(evidence.get("fetched_at") or ""))
            if not_after is not None and observed > not_after:
                continue
            found.append((observed, path, evidence))
        except Exception:
            continue
    found.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
    return found


def _queue_item_valid(item: Mapping[str, Any]) -> None:
    reference = str(item.get("reference") or "").upper()
    if not REF_RE.fullmatch(reference):
        raise ValueError(f"invalid Creative Europe exact-handoff reference: {reference!r}")
    if item.get("authority_url_verified") is not False:
        raise ValueError(f"programme-watch handoff self-verified authority: {reference}")
    for key in ("requires_exact_topic_readback", "requires_exact_topic_reconcile", "requires_material_admission"):
        if item.get(key) is not True:
            raise ValueError(f"programme-watch handoff skipped gate {key}: {reference}")
    for key in MATERIAL_FLAGS:
        if item.get(key) is not False:
            raise ValueError(f"programme-watch handoff became authorizing: {reference} {key}")


def _receipt_queue(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    validate_watch_reconciliation(receipt)
    queue = [dict(item) for item in (receipt.get("exact_verification_queue") or [])]
    if len(queue) != int(receipt.get("exact_verification_queue_count") or 0):
        raise ValueError("programme-watch exact queue count drift")
    for item in queue:
        _queue_item_valid(item)
    return queue


def _pending_already_completed(
    history_root: pathlib.Path | None,
    item: Mapping[str, Any],
    source_receipt: Mapping[str, Any],
) -> bool:
    reference = str(item.get("reference") or "").upper()
    source_time = _parse_utc(str(source_receipt.get("current_fetched_at") or ""))
    return any(
        observed >= source_time
        for observed, _path, _evidence in _history_exact_evidence(history_root, reference)
    )


def select_handoff(
    current_receipt: Mapping[str, Any],
    *,
    history_root: pathlib.Path | None = None,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    """Select at most one current or previously pending exact handoff."""
    current_queue = _receipt_queue(current_receipt)
    if str(current_receipt.get("current_source_health") or "") != "HEALTHY":
        if current_queue:
            raise ValueError("degraded current watch unexpectedly emitted exact handoff queue")
        return None, None, None
    if current_queue:
        return current_queue[0], SELECTION_CURRENT, dict(current_receipt)

    current_time = _parse_utc(str(current_receipt.get("reconciled_at") or ""))
    scope = current_receipt.get("source_scope_fingerprint")
    for prior_time, _path, prior in _history_watch_receipts(history_root):
        if prior_time >= current_time or prior.get("source_scope_fingerprint") != scope:
            continue
        if str(prior.get("current_source_health") or "") != "HEALTHY":
            continue
        for item in _receipt_queue(prior):
            if not _pending_already_completed(history_root, item, prior):
                return item, SELECTION_PREVIOUS, prior
    return None, None, None


def _base_summary(current_receipt: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema": SCHEMA,
        "handoff_id": HANDOFF_ID,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "run_id": run_id,
        "current_watch_reconciliation_sha256": _sha256(dict(current_receipt)),
        "market_intelligence_only": True,
        "requires_material_admission": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        summary[key] = False
    return summary


def _selection_payload(
    item: Mapping[str, Any],
    *,
    reference: str,
    selection_source: str,
    source_receipt: Mapping[str, Any],
    current_receipt_sha256: str,
) -> dict[str, Any]:
    selection: dict[str, Any] = {
        "schema": "PARTENER_EU_CREATIVE_EUROPE_FT_EXACT_HANDOFF_SELECTION_V1",
        "handoff_id": HANDOFF_ID,
        "reference": reference,
        "selection_source": selection_source,
        "queue_reason": item.get("reason"),
        "queue_priority": int(item.get("priority") or 0),
        "source_watch_reconciliation_sha256": _sha256(dict(source_receipt)),
        "current_watch_reconciliation_sha256": current_receipt_sha256,
        "authority_url_candidate": item.get("authority_url_candidate"),
        "authority_url_verified": False,
        "requires_exact_topic_readback": True,
        "requires_exact_topic_reconcile": True,
        "requires_material_admission": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        selection[key] = False
    return selection


def _failed_summary(
    summary: dict[str, Any],
    *,
    item: Mapping[str, Any],
    reference: str,
    selection_source: str,
    source_receipt: Mapping[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    summary.update({
        "observation_state": FAILED_STATE,
        "selected_reference": reference,
        "selection_source": selection_source,
        "queue_reason": item.get("reason"),
        "queue_priority": int(item.get("priority") or 0),
        "source_watch_reconciliation_sha256": _sha256(dict(source_receipt)),
        "exact_evidence_sha256": None,
        "previous_exact_evidence_sha256": None,
        "exact_reconciliation_sha256": None,
        "exact_candidate_observation_state": None,
        "exact_status_label": None,
        "exact_authority_url": exact.ft.topic_url(reference),
        "exact_authority_url_verified": False,
        "exact_semantic_reconciliation_state": None,
        "exact_semantic_change_count": 0,
        "material_admission_ready_for_downstream_review": False,
        "failure_stage": "EXACT_FUNDING_TENDERS_ACQUISITION_OR_RECONCILIATION",
        "failure_type": type(exc).__name__,
        "failure_message": str(exc)[:1000],
        "retry_candidate": True,
    })
    validate_handoff_summary(summary)
    return summary


def execute_handoff(
    current_receipt: Mapping[str, Any],
    *,
    run_id: str,
    output_dir: pathlib.Path,
    history_root: pathlib.Path | None = None,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] | None = None,
    topic_func: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validate_watch_reconciliation(current_receipt)
    output_dir.mkdir(parents=True, exist_ok=True)
    item, selection_source, source_receipt = select_handoff(current_receipt, history_root=history_root)
    summary = _base_summary(current_receipt, run_id=run_id)

    if item is None:
        summary.update({
            "observation_state": NO_HANDOFF_STATE,
            "selected_reference": None,
            "selection_source": None,
            "queue_reason": None,
            "queue_priority": None,
            "source_watch_reconciliation_sha256": None,
            "exact_evidence_sha256": None,
            "previous_exact_evidence_sha256": None,
            "exact_reconciliation_sha256": None,
            "exact_candidate_observation_state": None,
            "exact_status_label": None,
            "exact_semantic_reconciliation_state": None,
            "exact_semantic_change_count": 0,
            "material_admission_ready_for_downstream_review": False,
            "retry_candidate": False,
        })
        validate_handoff_summary(summary)
        _write(output_dir / "handoff-summary.json", summary)
        return summary

    assert source_receipt is not None and selection_source is not None
    reference = exact.validate_reference(str(item.get("reference") or ""))
    selection = _selection_payload(
        item,
        reference=reference,
        selection_source=selection_source,
        source_receipt=source_receipt,
        current_receipt_sha256=summary["current_watch_reconciliation_sha256"],
    )
    _write(output_dir / "handoff-selection.json", selection)

    current_dir = output_dir / "current"
    kwargs: dict[str, Any] = {}
    if post_func is not None:
        kwargs["post_func"] = post_func
    if topic_func is not None:
        kwargs["topic_func"] = topic_func
    try:
        current_exact = exact.collect_exact(
            reference,
            run_id=run_id,
            output_dir=current_dir,
            **kwargs,
        )
        current_time = _parse_utc(str(current_exact.get("fetched_at") or ""))
        previous_exact: dict[str, Any] | None = None
        previous_candidates = _history_exact_evidence(history_root, reference, not_after=current_time)
        if previous_candidates:
            _observed, previous_path, previous_exact = previous_candidates[0]
            previous_dir = output_dir / "previous"
            previous_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(previous_path, previous_dir / "ft-exact-evidence.json")
        reconciliation = exact_reconcile.reconcile(current_exact, previous_exact)
        _write(output_dir / "reconciliation" / "ft-reconciliation.json", reconciliation)
    except Exception as exc:
        failed = _failed_summary(
            summary,
            item=item,
            reference=reference,
            selection_source=selection_source,
            source_receipt=source_receipt,
            exc=exc,
        )
        _write(output_dir / "handoff-summary.json", failed)
        return failed

    summary.update({
        "observation_state": EXECUTED_STATE,
        "selected_reference": reference,
        "selection_source": selection_source,
        "queue_reason": item.get("reason"),
        "queue_priority": int(item.get("priority") or 0),
        "source_watch_reconciliation_sha256": _sha256(dict(source_receipt)),
        "exact_evidence_sha256": _sha256(dict(current_exact)),
        "previous_exact_evidence_sha256": _sha256(dict(previous_exact)) if previous_exact is not None else None,
        "exact_reconciliation_sha256": _sha256(dict(reconciliation)),
        "exact_candidate_observation_state": current_exact.get("candidate_observation_state"),
        "exact_status_label": current_exact.get("status_label"),
        "exact_authority_url": current_exact.get("authority_url"),
        "exact_authority_url_verified": current_exact.get("authority_url_verified"),
        "exact_semantic_reconciliation_state": reconciliation.get("reconciliation_state"),
        "exact_semantic_change_count": int(reconciliation.get("semantic_change_count") or 0),
        "material_admission_ready_for_downstream_review": bool(
            reconciliation.get("material_admission_ready_for_downstream_review")
        ),
        "retry_candidate": False,
    })
    validate_handoff_summary(summary)
    _write(output_dir / "handoff-summary.json", summary)
    return summary


def validate_handoff_summary(summary: Mapping[str, Any]) -> None:
    if summary.get("schema") != SCHEMA or summary.get("handoff_id") != HANDOFF_ID:
        raise ValueError("Creative Europe exact handoff identity drift")
    if summary.get("source_family") != "EU_DIRECT" or summary.get("programme_family") != "CREATIVE_EUROPE":
        raise ValueError("Creative Europe exact handoff programme boundary drift")
    if summary.get("market_intelligence_only") is not True or summary.get("requires_material_admission") is not True:
        raise ValueError("Creative Europe exact handoff lost downstream boundary")
    if summary.get("publication_effect") != "NONE" or summary.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe exact handoff crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if summary.get(key) is not False:
            raise ValueError(f"Creative Europe exact handoff became authorizing: {key}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get("current_watch_reconciliation_sha256") or "")):
        raise ValueError("Creative Europe exact handoff current watch binding missing")

    state = summary.get("observation_state")
    if state == NO_HANDOFF_STATE:
        if summary.get("selected_reference") is not None or summary.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("no-handoff summary crossed downstream boundary")
        return

    reference = exact.validate_reference(str(summary.get("selected_reference") or ""))
    if summary.get("selection_source") not in {SELECTION_CURRENT, SELECTION_PREVIOUS}:
        raise ValueError("Creative Europe exact handoff selection source invalid")
    if not summary.get("queue_reason"):
        raise ValueError("Creative Europe exact handoff queue reason missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get("source_watch_reconciliation_sha256") or "")):
        raise ValueError("Creative Europe exact handoff source watch binding missing")

    if state == FAILED_STATE:
        if summary.get("exact_authority_url") != exact.ft.topic_url(reference):
            raise ValueError("failed Creative Europe exact handoff authority URL drift")
        if summary.get("exact_authority_url_verified") is not False:
            raise ValueError("failed Creative Europe exact handoff claims verified authority")
        if summary.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("failed Creative Europe exact handoff claims material readiness")
        if summary.get("retry_candidate") is not True or not summary.get("failure_type") or not summary.get("failure_message"):
            raise ValueError("failed Creative Europe exact handoff lacks failure evidence")
        for key in ("exact_evidence_sha256", "previous_exact_evidence_sha256", "exact_reconciliation_sha256"):
            if summary.get(key) is not None:
                raise ValueError(f"failed Creative Europe exact handoff fabricated hash: {key}")
        return

    if state != EXECUTED_STATE:
        raise ValueError(f"unexpected Creative Europe exact handoff state: {state}")
    if summary.get("exact_authority_url") != exact.ft.topic_url(reference) or summary.get("exact_authority_url_verified") is not True:
        raise ValueError("Creative Europe exact handoff authority verification drift")
    if summary.get("exact_candidate_observation_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
        raise ValueError("Creative Europe exact handoff candidate state invalid")
    if summary.get("exact_semantic_reconciliation_state") not in {
        "BASELINE_CAPTURED_NON_AUTHORIZING",
        "NO_CHANGE",
        "EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
    }:
        raise ValueError("Creative Europe exact handoff reconciliation state invalid")
    for key in ("exact_evidence_sha256", "exact_reconciliation_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(summary.get(key) or "")):
            raise ValueError(f"Creative Europe exact handoff hash invalid: {key}")
    previous_hash = summary.get("previous_exact_evidence_sha256")
    if previous_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", str(previous_hash)):
        raise ValueError("Creative Europe exact handoff previous evidence hash invalid")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-watch-reconciliation", type=pathlib.Path, required=True)
    parser.add_argument("--history-root", type=pathlib.Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    current = _load_json(args.current_watch_reconciliation)
    summary = execute_handoff(
        current,
        run_id=args.run_id,
        output_dir=args.output_dir,
        history_root=args.history_root,
    )
    print(json.dumps({
        "observation_state": summary.get("observation_state"),
        "selected_reference": summary.get("selected_reference"),
        "selection_source": summary.get("selection_source"),
        "exact_candidate_observation_state": summary.get("exact_candidate_observation_state"),
        "exact_status_label": summary.get("exact_status_label"),
        "exact_semantic_reconciliation_state": summary.get("exact_semantic_reconciliation_state"),
        "failure_type": summary.get("failure_type"),
        "failure_message": summary.get("failure_message"),
        "material_admission_ready_for_downstream_review": summary.get("material_admission_ready_for_downstream_review"),
        "open_call_authorized": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL Creative Europe exact handoff: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
