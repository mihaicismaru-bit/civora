#!/usr/bin/env python3
"""Validate MySMIS exact-call scout outcomes without weakening fail-closed policy.

The scout is diagnostic/candidate-only. A controlled fail-closed result is a
valid validation outcome when every publication authority remains disabled.
Unexpected execution errors, status/exit mismatches, or any publication
permission still fail the production-validation gate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SAFE_STATUS_BY_EXIT = {
    0: {"PASS_CANDIDATE_ONLY", "SOURCE_UNAVAILABLE_FAIL_CLOSED"},
    2: {"PROVISIONAL_FAIL_CLOSED", "PARSER_SEMANTIC_DRIFT_FAIL_CLOSED"},
}


def validate_payload(payload: dict[str, Any], scout_exit_code: int) -> list[str]:
    errors: list[str] = []
    status = str(payload.get("status") or "")
    allowed = SAFE_STATUS_BY_EXIT.get(scout_exit_code)
    if allowed is None:
        errors.append(f"unexpected scout exit code: {scout_exit_code}")
    elif status not in allowed:
        errors.append(f"status/exit mismatch: status={status!r} exit={scout_exit_code}")

    for key in ("materialFactUse", "publishAuthorized", "openCallAuthorized"):
        if payload.get(key) is not False:
            errors.append(f"fail-closed authority flag must be false: {key}")

    if status == "PASS_CANDIDATE_ONLY":
        inventory = payload.get("candidateInventory") or {}
        if inventory.get("exactIdentityCompleteForVisiblePage") is not True:
            errors.append("candidate PASS lacks exact identity for the visible page")
        if not inventory.get("rows"):
            errors.append("candidate PASS contains no exact-call rows")

    if status == "PROVISIONAL_FAIL_CLOSED":
        inventory = payload.get("candidateInventory") or {}
        if inventory.get("exactIdentityCompleteForVisiblePage") is True:
            errors.append("provisional status is inconsistent with complete visible-page identity")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--scout-exit-code", required=True, type=int)
    args = parser.parse_args()

    path = Path(args.path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": f"candidate evidence unreadable: {type(exc).__name__}: {exc}"}))
        return 2

    errors = validate_payload(payload, args.scout_exit_code)
    result = {
        "status": "PASS_CONTROLLED_FAIL_CLOSED" if not errors else "FAIL",
        "candidateStatus": payload.get("status"),
        "scoutExitCode": args.scout_exit_code,
        "publishAuthorized": payload.get("publishAuthorized"),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
