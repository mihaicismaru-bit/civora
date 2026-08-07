from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence, TextIO
import sys

from .editorial_approval import EditorialApprovalError, EditorialApprovalStore
from .editorial_gate_store import EditorialGateStore, EditorialGateStoreError
from .editorial_resolution import EditorialResolutionCoordinator, EditorialResolutionError
from .fact_contradictions import FactContradictionStore, FactContradictionStoreError
from .fact_kernel import FactKernelStore, FactKernelStoreError
from .fact_reconciliation import FactReconciliationStore, FactReconciliationStoreError
from .health import UnifiedHealthInspector
from .recovery import RecoveryEventLedger, RecoveryEventLedgerError
from .review import ReviewQueueError
from .transactions import TransactionJournal, TransactionJournalError

EXIT_OK = 0
EXIT_UNHEALTHY = 2
EXIT_ERROR = 3


def _paths(state_dir: Path) -> dict[str, Path]:
    return {
        "sources": state_dir / "sources.json",
        "signals": state_dir / "signals.json",
        "review": state_dir / "review_queue.json",
        "transactions": state_dir / "transactions.json",
        "recovery": state_dir / "recovery_events.json",
        "fact_kernel": state_dir / "fact_kernels.json",
        "fact_reconciliation": state_dir / "fact_reconciliation.json",
        "fact_contradictions": state_dir / "fact_contradictions.json",
        "editorial_gate": state_dir / "editorial_gate.json",
        "editorial_approval": state_dir / "editorial_approval.json",
    }


def _emit(payload: object, output: TextIO) -> None:
    json.dump(payload, output, indent=2, sort_keys=True)
    output.write("\n")


def _health(state_dir: Path, output: TextIO) -> int:
    paths = _paths(state_dir)
    inspector = UnifiedHealthInspector(
        source_registry_path=paths["sources"], signal_store_path=paths["signals"],
        review_queue_path=paths["review"], transaction_journal_path=paths["transactions"],
        checkpoint_dir=state_dir, fact_kernel_path=paths["fact_kernel"],
        fact_reconciliation_path=paths["fact_reconciliation"],
        fact_contradiction_path=paths["fact_contradictions"],
        editorial_gate_path=paths["editorial_gate"],
        editorial_approval_path=paths["editorial_approval"],
        recovery_event_ledger_path=paths["recovery"],
    )
    report = inspector.inspect()
    _emit(report.to_dict(), output)
    return EXIT_OK if report.status in {"healthy", "recovered_from_backup"} else EXIT_UNHEALTHY


def _list_dead_letters(state_dir: Path, output: TextIO) -> int:
    records = TransactionJournal(_paths(state_dir)["transactions"]).dead_letters()
    _emit({"count": len(records), "dead_letters": records}, output)
    return EXIT_OK


def _resolve_dead_letter(state_dir: Path, tx_id: str, action: str, actor: str, reason: str, output: TextIO) -> int:
    paths = _paths(state_dir)
    record = TransactionJournal(paths["transactions"]).resolve_dead_letter(
        tx_id, action, actor=actor, reason=reason, recovery_ledger=RecoveryEventLedger(paths["recovery"])
    )
    _emit({"resolved": record}, output)
    return EXIT_OK


def _recovery_events(state_dir: Path, output: TextIO, *, component: Optional[str] = None,
                     event_type: Optional[str] = None, status: Optional[str] = None,
                     limit: Optional[int] = None) -> int:
    events = RecoveryEventLedger(_paths(state_dir)["recovery"]).all()
    if component is not None:
        events = [event for event in events if event.get("component") == component]
    if event_type is not None:
        events = [event for event in events if event.get("event_type") == event_type]
    if status is not None:
        events = [event for event in events if event.get("status") == status]
    if limit is not None:
        events = events[-limit:]
    _emit({"count": len(events), "events": events}, output)
    return EXIT_OK


def _transaction_detail(state_dir: Path, tx_id: str, output: TextIO) -> int:
    journal = TransactionJournal(_paths(state_dir)["transactions"])
    journal.load()
    record = journal.records.get(tx_id)
    if record is None:
        raise TransactionJournalError(f"unknown transaction: {tx_id}")
    _emit({"transaction": dict(record)}, output)
    return EXIT_OK


def _resolution_audit(state_dir: Path, output: TextIO) -> int:
    paths = _paths(state_dir)
    status = TransactionJournal(paths["transactions"]).resolution_audit_status(
        RecoveryEventLedger(paths["recovery"])
    )
    _emit(status, output)
    return EXIT_OK if status["consistent"] else EXIT_UNHEALTHY


def _editorial_story(state_dir: Path, story_id: str, output: TextIO) -> int:
    paths = _paths(state_dir)
    kernel = FactKernelStore(paths["fact_kernel"]).load_story(story_id)
    reconciliation = FactReconciliationStore(paths["fact_reconciliation"]).load_story(story_id)
    contradictions = FactContradictionStore(paths["fact_contradictions"]).load_story(story_id)
    gate = EditorialGateStore(paths["editorial_gate"]).load_story(story_id)
    approval = EditorialApprovalStore(paths["editorial_approval"]).load_story(story_id)
    if not any(item is not None for item in (kernel, reconciliation, contradictions, gate, approval)):
        raise ValueError(f"unknown editorial story: {story_id}")
    _emit({"story_id": story_id, "fact_kernel": kernel, "reconciliation": reconciliation,
           "contradictions": contradictions, "editorial_gate": gate, "approval_case": approval}, output)
    return EXIT_OK


def _approval_cases(state_dir: Path, output: TextIO, *, state: Optional[str] = None) -> int:
    records = EditorialApprovalStore(_paths(state_dir)["editorial_approval"]).list_cases(state=state)
    _emit({"count": len(records), "cases": records}, output)
    return EXIT_OK


def _approval_case(state_dir: Path, case_id: str, output: TextIO) -> int:
    record = EditorialApprovalStore(_paths(state_dir)["editorial_approval"]).load_case(case_id)
    if record is None:
        raise EditorialApprovalError("unknown approval case")
    _emit({"case": record}, output)
    return EXIT_OK


def _decide_approval(state_dir: Path, case_id: str, action: str, actor: str, reason: str, output: TextIO) -> int:
    result = EditorialResolutionCoordinator.from_state_dir(state_dir).decide(
        case_id, action=action, actor=actor, reason=reason
    )
    _emit(result, output)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="civora", description="CIVORA operational control surface")
    parser.add_argument("--state-dir", type=Path, default=Path("state"),
                        help="CIVORA durable state directory (default: ./state)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="inspect durable runtime and editorial health")
    subparsers.add_parser("dead-letters", help="list dead-letter transactions")

    resolve = subparsers.add_parser("resolve-dead-letter", help="explicitly resolve one dead letter")
    resolve.add_argument("transaction_id")
    resolve.add_argument("--action", choices=["requeue", "abort"], required=True)
    resolve.add_argument("--actor", required=True)
    resolve.add_argument("--reason", required=True)

    recovery = subparsers.add_parser("recovery-events", help="inspect durable recovery/audit events")
    recovery.add_argument("--component")
    recovery.add_argument("--event-type", choices=sorted(RecoveryEventLedger.EVENT_TYPES))
    recovery.add_argument("--status")
    recovery.add_argument("--limit", type=int)

    transaction = subparsers.add_parser("transaction", help="inspect one transaction record")
    transaction.add_argument("transaction_id")
    subparsers.add_parser("resolution-audit", help="compare transaction resolution history with global recovery ledger")

    editorial_story = subparsers.add_parser("editorial-story", help="inspect durable editorial evidence and decision chain")
    editorial_story.add_argument("story_id")
    approval_cases = subparsers.add_parser("approval-cases", help="list editorial approval cases")
    approval_cases.add_argument("--state", choices=sorted(EditorialApprovalStore.ALLOWED_STATES))
    approval_case = subparsers.add_parser("approval-case", help="inspect one editorial approval case")
    approval_case.add_argument("case_id")
    decide_approval = subparsers.add_parser("decide-approval", help="transactionally resolve approval and Review Queue")
    decide_approval.add_argument("case_id")
    decide_approval.add_argument("--action", choices=sorted(EditorialApprovalStore.FINAL_STATES), required=True)
    decide_approval.add_argument("--actor", required=True)
    decide_approval.add_argument("--reason", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None, *, output: Optional[TextIO] = None) -> int:
    output = output or sys.stdout
    args = build_parser().parse_args(argv)
    state_dir: Path = args.state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "health": return _health(state_dir, output)
        if args.command == "dead-letters": return _list_dead_letters(state_dir, output)
        if args.command == "resolve-dead-letter":
            return _resolve_dead_letter(state_dir, args.transaction_id, args.action, args.actor, args.reason, output)
        if args.command == "recovery-events":
            if args.limit is not None and args.limit < 1: raise ValueError("--limit must be a positive integer")
            return _recovery_events(state_dir, output, component=args.component, event_type=args.event_type,
                                    status=args.status, limit=args.limit)
        if args.command == "transaction": return _transaction_detail(state_dir, args.transaction_id, output)
        if args.command == "resolution-audit": return _resolution_audit(state_dir, output)
        if args.command == "editorial-story": return _editorial_story(state_dir, args.story_id, output)
        if args.command == "approval-cases": return _approval_cases(state_dir, output, state=args.state)
        if args.command == "approval-case": return _approval_case(state_dir, args.case_id, output)
        if args.command == "decide-approval":
            return _decide_approval(state_dir, args.case_id, args.action, args.actor, args.reason, output)
    except (TransactionJournalError, RecoveryEventLedgerError, FactKernelStoreError,
            FactReconciliationStoreError, FactContradictionStoreError, EditorialGateStoreError,
            EditorialApprovalError, EditorialResolutionError, ReviewQueueError, OSError, ValueError) as exc:
        _emit({"error": str(exc), "command": args.command}, output)
        return EXIT_ERROR
    _emit({"error": f"unsupported command: {args.command}"}, output)
    return EXIT_ERROR


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
