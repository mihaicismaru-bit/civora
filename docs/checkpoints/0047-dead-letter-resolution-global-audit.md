# CIVORA Checkpoint 0047 — Dead-letter resolution global audit reconciliation

Status: `CODE_COMPLETE_CI_PENDING`

## Objective

Mirror explicit transaction dead-letter resolutions into the global Recovery Event Ledger without allowing duplicate audit events or leaving an unrecoverable crash gap between the transaction journal and the independent audit store.

## Implemented

- `RecoveryEventLedger.append()` accepts an optional stable `event_id`.
- Re-appending an event with the same identity and identical content is idempotent.
- Reusing an event identity with different content fails closed.
- Recovery ledger supports the `resolution` event type.
- Every new dead-letter resolution receives a deterministic `event_id` derived from transaction id, resolution timestamp, and action.
- `TransactionJournal.resolve_dead_letter(..., recovery_ledger=...)` mirrors the resolution into the global recovery audit when a ledger is supplied.
- `TransactionJournal.mirror_resolution_events()` reconciles all durable `resolution_history` entries into the Recovery Event Ledger.
- Reconciliation repairs the crash window where the journal mutation committed but the independent audit append did not.
- Reconciliation is idempotent and can be run repeatedly after restart.
- Checkpoint-0046 resolution histories without a stored `event_id` remain compatible; the deterministic identity is reconstructed during reconciliation.

## Validation added

- stable event identity produces one event across repeated appends;
- conflicting content under the same identity is rejected;
- dead-letter `requeue` is mirrored with actor, reason, transaction, and operation metadata;
- simulated crash between journal resolution and global ledger append is repaired after restart;
- repeated reconciliation produces no duplicate event;
- legacy resolution history without `event_id` can be reconciled.

## Gates

- `GLOBAL_RESOLUTION_AUDIT_WIRING`: PASS_IMPLEMENTATION_REVIEW
- `IDEMPOTENT_AUDIT_EVENT_IDENTITY`: PASS_IMPLEMENTATION_REVIEW
- `AUDIT_ID_COLLISION_FAIL_CLOSED`: PASS_IMPLEMENTATION_REVIEW
- `CROSS_STORE_CRASH_GAP_RECONCILIATION`: PASS_IMPLEMENTATION_REVIEW
- `LEGACY_RESOLUTION_HISTORY_COMPATIBILITY`: PASS_IMPLEMENTATION_REVIEW
- `PYTHON_3_11_3_13_CI`: PENDING_CURRENT_CI
- `WINDOWS_NATIVE`: PENDING

## Remaining risk

The reconciliation primitive exists but is not yet automatically invoked by the orchestrator startup health gate. Until that integration is added, recovery of a missed mirror requires an explicit reconciliation call.

## Next canonical action

Run resolution-audit reconciliation automatically during orchestrator startup, then re-inspect health and deduplicate repetitive health/recovery observations using stable event identities.
