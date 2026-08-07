from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence, TextIO
import sys

from .health import UnifiedHealthInspector
from .recovery import RecoveryEventLedger, RecoveryEventLedgerError
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
    }


def _emit(payload: object, output: TextIO) -> None:
    json.dump(payload, output, indent=2, sort_keys=True)
    output.write("\n")


def _health(state_dir: Path, output: TextIO) -> int:
    paths = _paths(state_dir)
    inspector = UnifiedHealthInspector(
        source_registry_path=paths["sources"],
        signal_store_path=paths["signals"],
        review_queue_path=paths["review"],
        transaction_journal_path=paths["transactions"],
        checkpoint_dir=state_dir,
        recovery_event_ledger_path=paths["recovery"],
    )
    report = inspector.inspect()
    _emit(report.to_dict(), output)
    return EXIT_OK if report.status in {"healthy", "recovered_from_backup"} else EXIT_UNHEALTHY


def _list_dead_letters(state_dir: Path, output: TextIO) -> int:
    journal = TransactionJournal(_paths(state_dir)["transactions"])
    records = journal.dead_letters()
    _emit({"count": len(records), "dead_letters": records}, output)
    return EXIT_OK


def _resolve_dead_letter(
    state_dir: Path,
    tx_id: str,
    action: str,
    actor: str,
    reason: str,
    output: TextIO,
) -> int:
    paths = _paths(state_dir)
    journal = TransactionJournal(paths["transactions"])
    ledger = RecoveryEventLedger(paths["recovery"])
    record = journal.resolve_dead_letter(
        tx_id,
        action,
        actor=actor,
        reason=reason,
        recovery_ledger=ledger,
    )
    _emit({"resolved": record}, output)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="civora", description="CIVORA operational control surface")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("state"),
        help="CIVORA durable state directory (default: ./state)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="inspect durable runtime health")
    subparsers.add_parser("dead-letters", help="list dead-letter transactions")

    resolve = subparsers.add_parser("resolve-dead-letter", help="explicitly resolve one dead letter")
    resolve.add_argument("transaction_id")
    resolve.add_argument("--action", choices=["requeue", "abort"], required=True)
    resolve.add_argument("--actor", required=True)
    resolve.add_argument("--reason", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None, *, output: Optional[TextIO] = None) -> int:
    output = output or sys.stdout
    args = build_parser().parse_args(argv)
    state_dir: Path = args.state_dir
    state_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.command == "health":
            return _health(state_dir, output)
        if args.command == "dead-letters":
            return _list_dead_letters(state_dir, output)
        if args.command == "resolve-dead-letter":
            return _resolve_dead_letter(
                state_dir,
                args.transaction_id,
                args.action,
                args.actor,
                args.reason,
                output,
            )
    except (TransactionJournalError, RecoveryEventLedgerError, OSError, ValueError) as exc:
        _emit({"error": str(exc), "command": args.command}, output)
        return EXIT_ERROR

    _emit({"error": f"unsupported command: {args.command}"}, output)
    return EXIT_ERROR


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
