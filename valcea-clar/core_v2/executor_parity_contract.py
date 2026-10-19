from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "core-v2-executor-parity.v1"
PUBLICATION_AUTHORITY = "NONE"
EXPECTED_STAGE_COUNT = 41
EXPECTED_AUDIT_INPUT_COUNT = 6
EXPECTED_FAIL_CLOSED_REGRESSIONS = 5


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"executor_parity_not_object:{path}")
    return value


def verify(*, cycle: Path, sequence: Path, meta: Path) -> dict[str, Any]:
    cycle_doc = _read(cycle)
    sequence_doc = _read(sequence)
    meta_doc = _read(meta)

    checks = {
        "cycle_status_pass_shadow": cycle_doc.get("status") == "PASS_SHADOW",
        "cycle_failed_stage_null": cycle_doc.get("failed_stage") is None,
        "cycle_stage_count_planned_41": int(cycle_doc.get("stage_count_planned") or -1) == EXPECTED_STAGE_COUNT,
        "cycle_stage_count_completed_41": int(cycle_doc.get("stage_count_completed") or -1) == EXPECTED_STAGE_COUNT,
        "cycle_publication_authority_none": cycle_doc.get("publication_authority") == PUBLICATION_AUTHORITY,
        "cycle_production_write_authority_false": cycle_doc.get("production_write_authority") is False,
        "cycle_site_publish_allowed_false": cycle_doc.get("site_publish_allowed") is False,
        "cycle_social_publish_allowed_false": cycle_doc.get("social_publish_allowed") is False,
        "cycle_acceptance_ready_false": cycle_doc.get("acceptance_ready") is False,
        "sequence_schema_expected": sequence_doc.get("schema_version") == "core-v2-external-evidence-sequence.v1",
        "sequence_mode_shadow_read_only": sequence_doc.get("mode") == "SHADOW_READ_ONLY",
        "sequence_publication_authority_none": sequence_doc.get("publication_authority") == PUBLICATION_AUTHORITY,
        "sequence_production_write_authority_false": sequence_doc.get("production_write_authority") is False,
        "sequence_acceptance_ready_false": sequence_doc.get("acceptance_ready") is False,
        "sequence_external_auditor_inserted_false": sequence_doc.get("external_auditor_inserted") is False,
        "sequence_external_auditor_executed_false": sequence_doc.get("external_auditor_executed") is False,
        "sequence_audit_input_count_6": int(sequence_doc.get("audit_input_count") or -1) == EXPECTED_AUDIT_INPUT_COUNT,
        "sequence_fail_closed_regressions_5": int(sequence_doc.get("fail_closed_regressions_passed") or -1) == EXPECTED_FAIL_CLOSED_REGRESSIONS,
        "sequence_meta_token_present": sequence_doc.get("meta_token_present") is True,
        "meta_publication_authority_none": meta_doc.get("publication_authority") == PUBLICATION_AUTHORITY,
        "meta_token_present": meta_doc.get("token_present") is True,
    }

    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError("executor_parity_contract_failed:" + ",".join(failed))

    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_SHADOW",
        "publication_authority": PUBLICATION_AUTHORITY,
        "acceptance_ready": False,
        "production_write_authority": False,
        "external_auditor_inserted": False,
        "external_auditor_executed": False,
        "workflow_retirement_performed": False,
        "canonical_stage_count": EXPECTED_STAGE_COUNT,
        "audit_input_count": EXPECTED_AUDIT_INPUT_COUNT,
        "fail_closed_regressions_passed": EXPECTED_FAIL_CLOSED_REGRESSIONS,
        "meta_token_present": True,
        "candidate_count": int(meta_doc.get("candidate_count") or 0),
        "facebook_readback_passed": int((meta_doc.get("facebook") or {}).get("passed") or 0),
        "facebook_readback_failed": int((meta_doc.get("facebook") or {}).get("failed") or 0),
        "facebook_readback_blocked": int((meta_doc.get("facebook") or {}).get("blocked") or 0),
        "instagram_readback_passed": int((meta_doc.get("instagram") or {}).get("passed") or 0),
        "instagram_readback_failed": int((meta_doc.get("instagram") or {}).get("failed") or 0),
        "instagram_readback_blocked": int((meta_doc.get("instagram") or {}).get("blocked") or 0),
        "checks_passed": len(checks),
        "checks_failed": 0,
        "truth_rule": (
            "This proof verifies that the single Core v2 executor can receive the existing Meta credentials "
            "for read-only remote readback while preserving zero publication authority. It does not prove "
            "delivery, acceptance readiness, cutover authority, or production readiness."
        ),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Core v2 single-executor read-only parity boundary")
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = verify(
        cycle=Path(args.cycle),
        sequence=Path(args.sequence),
        meta=Path(args.meta),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
