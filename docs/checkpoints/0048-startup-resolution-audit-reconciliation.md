# CIVORA Checkpoint 0048 — Startup Resolution Audit Reconciliation

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the crash-recovery gap left after checkpoint 0047 by making dead-letter resolution audit reconciliation an automatic startup responsibility rather than an operator-invoked repair step.

## Implementation

`Orchestrator` now owns a `RecoveryEventLedger` and exposes `reconcile_resolution_audit()`.

The startup sequence is now:

1. inspect durable runtime state;
2. fail closed immediately on corruption;
3. reconcile durable transaction `resolution_history` into the global recovery event ledger;
4. replay pending transactions;
5. inspect runtime state again;
6. authorize new work only when the final state is `healthy` or `recovered_from_backup`.

The reconciliation delegates to `TransactionJournal.mirror_resolution_events()`, preserving the deterministic event identity introduced in checkpoint 0047. Repeated startup reconciliation is therefore idempotent.

If reconciliation itself fails, startup raises `OrchestratorError` and no new editorial work is accepted.

## Validation added

`tests/test_startup_health.py` now includes an end-to-end crash-gap regression:

- a transaction is dead-lettered;
- it is explicitly aborted without mirroring to the global ledger, simulating a crash after journal persistence;
- a new orchestrator starts;
- startup repairs the missing global resolution event;
- a second startup does not create a duplicate event.

## Gates

- STARTUP_RESOLUTION_AUDIT_RECONCILIATION: PASS_IMPLEMENTATION_REVIEW
- CRASH_GAP_AUDIT_REPAIR: TEST_ADDED
- RECONCILIATION_IDEMPOTENCE: TEST_ADDED
- RECONCILIATION_FAIL_CLOSED: PASS_IMPLEMENTATION_REVIEW
- PRE_WORK_STARTUP_ORDERING: PASS_IMPLEMENTATION_REVIEW
- PYTHON_3_11_3_12_3_13: CI_PENDING
- WINDOWS_NATIVE: PENDING

## Remaining backlog

1. deduplicate repetitive health observations in `RecoveryEventLedger` while preserving materially distinct state transitions;
2. add multiprocess end-to-end crash/recovery tests for `story -> review` and transaction reconciliation;
3. wire Source Registry and Signal Store paths into default orchestrator health composition;
4. add Windows-native validation;
5. begin Fact Kernel / claim-evidence reconciliation after persistence/recovery gates are closed.

## Blockers

No credential or irreversible-action blocker for this checkpoint. Current validation depends only on the GitHub Actions run for the latest branch head.

## Next canonical action

Implement deterministic deduplication/coalescing of repetitive health observations so repeated startup inspections do not grow the recovery ledger indefinitely while true state transitions remain auditable.
