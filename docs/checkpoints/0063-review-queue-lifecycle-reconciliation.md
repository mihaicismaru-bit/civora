# CIVORA Checkpoint 0063 — Review Queue Lifecycle Reconciliation

Status: CODE_COMPLETE_CI_PENDING

## Objective

Prevent durable divergence between Editorial Approval state and Review Queue state after approved, rejected, or revision-required operator decisions.

## Implementation

Added `EditorialResolutionCoordinator`, a crash-recoverable coordinator backed by the existing `TransactionJournal`.

Resolution sequence:

1. validate approval case and queue participation;
2. prepare `editorial_review_resolution` transaction;
3. persist authoritative approval decision;
4. idempotently reconcile Review Queue terminal status;
5. commit transaction.

If a process crashes after the approval write but before Review Queue resolution, the prepared transaction is replayed by Orchestrator recovery. Approval replay is idempotent for the same action and Review Queue resolution is idempotent for the same terminal state.

Review Queue now supports `approved`, `rejected`, and `revision_required`, with actor/reason audit history. Existing schema-version-2 queues remain readable; history is an optional backward-compatible field.

The CLI `decide-approval` command now routes through the coordinator instead of mutating the approval store directly.

Queue participation is recorded explicitly in each transaction. When Review Queue was active for the case, a missing queue item fails closed. Installations where Review Queue was genuinely disabled can still resolve approval cases without manufacturing queue state.

`resume_after_approval()` additionally requires an `approved` Review Queue item whenever the Orchestrator is configured with Review Queue.

## Validation added

`tests/test_editorial_resolution.py` covers:

- normal approval + queue synchronization;
- `revision_required` synchronization;
- simulated crash after approval persistence and before queue persistence;
- startup/recovery replay to completion;
- conflicting terminal queue state fail-closed behavior;
- approval-only operation when Review Queue is disabled;
- backward-compatible reading of schema-2 queues without history.

## Gates

- CHECKPOINT_0062_CROSS_PLATFORM_CI: PASS
- TRANSACTIONAL_EDITORIAL_RESOLUTION: PASS_IMPLEMENTATION
- REVIEW_QUEUE_TERMINAL_LIFECYCLE: PASS_IMPLEMENTATION
- APPROVAL_QUEUE_AUDIT_PARITY: PASS_IMPLEMENTATION
- CRASH_RECOVERY_REPLAY: PASS_IMPLEMENTATION
- IDEMPOTENT_QUEUE_REPLAY: PASS_IMPLEMENTATION
- CONFLICTING_TERMINAL_STATE_FAIL_CLOSED: PASS_IMPLEMENTATION
- REVIEW_QUEUE_SCHEMA_COMPATIBILITY: PASS_IMPLEMENTATION
- CLI_COORDINATOR_ROUTING: PASS_IMPLEMENTATION
- APPROVED_REENTRY_QUEUE_GUARD: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING

## Remaining backlog

1. Validate checkpoint 0063 in the cross-platform CI matrix.
2. Add explicit lifecycle consistency inspection/health between approval store and Review Queue.
3. Extend crash/recovery testing through approved pipeline re-entry.
4. Build Story Engine constrained to authorized/corroborated facts.
5. Add operator runbooks after lifecycle commands stabilize.

## Blockers

Current-head cross-platform CI is required before `CLOSED_VALIDATED` can be declared.

## Next action

If CI passes, implement approval/Review Queue consistency inspection and fail-closed health wiring; otherwise repair the regression before feature expansion.
