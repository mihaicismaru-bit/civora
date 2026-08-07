# CIVORA Checkpoint 0046 — Audited Dead-Letter Resolution

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the operational gap introduced by bounded recovery: dead-letter transactions must not be silently deleted or manually mutated outside the journal. They require an explicit and durable resolution path.

## Implementation

`TransactionJournal.resolve_dead_letter()` now supports exactly two actions:

- `requeue`: moves `dead_letter -> prepared`, resets `recovery_attempts` to zero and clears the previous automatic recovery error so the transaction receives a fresh bounded retry budget.
- `abort`: moves `dead_letter -> aborted` and persists the operator-provided reason.

Every resolution requires a non-empty `actor` and `reason` and appends a timestamped entry to `resolution_history`. The history is validated as part of the journal payload and is preserved by the same AtomicJsonStore durability, locking, checksum, backup and fail-closed guarantees as the transaction itself.

Resolution is rejected unless the current state is exactly `dead_letter`; unsupported actions and unaudited requests are rejected.

## Validation added

Tests cover:

- dead-letter -> requeue with persistent audit history;
- recovery-attempt reset and successful replay after requeue;
- dead-letter -> abort with persistent reason;
- dead-letter removal from automatic recovery scope after abort;
- rejection of resolution against a non-dead-letter transaction;
- rejection of unsupported actions and missing actor metadata.

## Gates

- EXPLICIT_DEAD_LETTER_RESOLUTION: PASS_IMPLEMENTATION_REVIEW
- DEAD_LETTER_REQUEUE: PASS_IMPLEMENTATION_REVIEW
- DEAD_LETTER_ABORT: PASS_IMPLEMENTATION_REVIEW
- DURABLE_RESOLUTION_HISTORY: PASS_IMPLEMENTATION_REVIEW
- RESOLUTION_ACTOR_REASON_REQUIRED: PASS_IMPLEMENTATION_REVIEW
- SILENT_DELETION_PATH: ABSENT
- PYTHON_3_11_3_13_CI: PENDING_CURRENT_HEAD
- WINDOWS_NATIVE: PENDING

## Remaining risk

The audit trail currently lives inside the transaction journal. The global Recovery Event Ledger does not yet receive a mirrored dead-letter-resolution event. That cross-ledger integration should be added next so operational recovery actions appear in the unified audit surface.

## Next action

Integrate dead-letter resolution with RecoveryEventLedger using an idempotent event key, then add event deduplication and health re-inspection after resolution.
