# CIVORA Checkpoint 0073 — Operator Remediation Runbooks

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the operational documentation gap before release review by defining deterministic, evidence-preserving operator procedures for healthy state, prepared crash-window recovery, manual investigation, backup recovery, dead-letter resolution and editorial approval/re-entry.

## Implementation

Added `docs/runbooks/operator-remediation.md` as the canonical v1.0 remediation runbook.

The runbook explicitly reuses existing CIVORA policy and commands. It introduces no new repair mutation path and forbids direct durable-store editing.

The decision tree follows the machine-readable remediation classifications already emitted by CIVORA:

- `no_action` — verify health and continue;
- `automatic_recovery_available` — inspect exact prepared transactions and use existing idempotent startup replay;
- `manual_investigation_required` — fail closed, preserve evidence and require an evidence-backed repair or validated external backup.

Backup recovery distinguishes automatic internal `.bak` recovery through `AtomicJsonStore` from external backup restoration. External restore is deliberately not automated in v1.0 and must first be validated in a separate recovery state directory.

Dead-letter and approval procedures use only the audited CLI transitions already provided by CIVORA.

## Contract validation

Added `tests/test_runbook_contract.py` to prevent release documentation drift from the operator surface. The test asserts that all primary commands referenced by the runbook remain registered and that the documented CLI exit-code contracts remain unchanged.

## Safety properties

- No direct JSON-store editing is authorized.
- No deletion of audit evidence is authorized.
- No synthetic transaction or audit reconstruction is authorized.
- Automatic recovery is limited to existing prepared-transaction replay and validated internal backup recovery.
- Committed or ambiguous divergence remains fail-closed.
- External backup promotion is operator-controlled and requires validation on a separate state directory first.
- Stale editorial approval remains fail-closed.

## Gates

- CANONICAL_OPERATOR_RUNBOOK: PASS_IMPLEMENTATION
- REMEDIATION_DECISION_TREE: PASS_IMPLEMENTATION
- EVIDENCE_PRESERVATION_RULES: PASS_IMPLEMENTATION
- PREPARED_ONLY_AUTOMATIC_RECOVERY: PASS_IMPLEMENTATION
- INTERNAL_BACKUP_RECOVERY_PROCEDURE: PASS_IMPLEMENTATION
- EXTERNAL_BACKUP_VALIDATION_PROCEDURE: PASS_IMPLEMENTATION
- DEAD_LETTER_AUDITED_PROCEDURE: PASS_IMPLEMENTATION
- EDITORIAL_APPROVAL_REENTRY_PROCEDURE: PASS_IMPLEMENTATION
- CLI_DOCUMENTATION_CONTRACT_TEST: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING_CURRENT_CI

## Remaining backlog

1. Production-readiness audit across recovery, persistence, editorial safety, operator UX, packaging, security assumptions and release governance.
2. Remediate release-blocking findings from that audit.
3. Full release-candidate regression/preflight.
4. Version lock, release manifest, changelog and CIVORA v1.0 closure.
5. Evidence-preserving style layer remains deferred until post-v1.0.

## Blockers

Current-head cross-platform CI result is required before checkpoint 0073 can be declared `CLOSED_VALIDATED`.

## Next action

Run checkpoint 0074 Production Readiness Audit. Treat all release-blocking findings as higher priority than new features.
