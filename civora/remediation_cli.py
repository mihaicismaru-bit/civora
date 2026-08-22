from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence, TextIO
import sys

from .editorial_consistency import EditorialConsistencyInspector
from .editorial_remediation import EditorialRemediationPlanner

EXIT_OK = 0
EXIT_ACTION_REQUIRED = 2
EXIT_ERROR = 3


def inspect_remediation(state_dir: Path) -> dict:
    report = EditorialConsistencyInspector(
        state_dir / "editorial_approval.json",
        state_dir / "review_queue.json",
        state_dir / "transactions.json",
    ).inspect()
    return {
        "editorial_consistency": report,
        "remediation": EditorialRemediationPlanner().plan(report),
    }


def main(argv: Optional[Sequence[str]] = None, *, output: Optional[TextIO] = None) -> int:
    output = output or sys.stdout
    parser = argparse.ArgumentParser(
        prog="civora-remediation",
        description="Read-only CIVORA editorial consistency remediation guidance",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("state"),
        help="CIVORA durable state directory (default: ./state)",
    )
    args = parser.parse_args(argv)
    try:
        payload = inspect_remediation(args.state_dir)
        json.dump(payload, output, indent=2, sort_keys=True)
        output.write("\n")
        return EXIT_OK if payload["remediation"]["classification"] == "no_action" else EXIT_ACTION_REQUIRED
    except (OSError, RuntimeError, ValueError) as exc:
        json.dump({"error": str(exc)}, output, indent=2, sort_keys=True)
        output.write("\n")
        return EXIT_ERROR


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
