# CIVORA Checkpoint 0037 — SignalStore common persistence migration

Status: `CODE_COMPLETE_VALIDATION_PENDING`

## Objective

Remove the duplicated crash-safe JSON persistence implementation from `SignalStore` and make signals use the same `AtomicJsonStore` primitive already used by Source Registry and Review Queue.

## Changes

- `SignalStore` now delegates checksum generation, schema validation, atomic replacement, backup recovery, fail-closed loading, and process locking to `AtomicJsonStore`.
- Signal-specific validation remains local to `SignalStore`:
  - `signals` and `fingerprints` must be objects;
  - every signal record must reconstruct as a `Signal`;
  - every record key must match the embedded signal id;
  - every fingerprint must point to an existing signal.
- Existing `SignalStore._checksum()` is retained as a compatibility shim over `AtomicJsonStore.checksum()`.
- In-memory rollback on failed persistence is preserved.
- Tests now assert common-store usage and reject mismatched record identifiers.

## Gates

- COMMON_PERSISTENCE_PRIMITIVE: PASS_IMPLEMENTATION_REVIEW
- SIGNAL_REFERENTIAL_INTEGRITY: PASS_IMPLEMENTATION_REVIEW
- SIGNAL_BACKUP_RECOVERY: PRESERVED
- SIGNAL_FAIL_CLOSED: PRESERVED
- CROSS_PROCESS_LOCKING: INHERITED_FROM_ATOMIC_JSON_STORE
- AUTOMATED_TEST_EXECUTION: PENDING_CI

## Risk reduction

This checkpoint eliminates a second independent implementation of checksum, backup, atomic-write and recovery behavior. Future reliability fixes can now be applied once in `AtomicJsonStore` and inherited by Signal Store, Source Registry and Review Queue.

## Next action

Introduce a transaction journal for operations spanning more than one store, starting with coordinated story processing and review-queue persistence. The journal must support prepare/commit/abort markers and deterministic recovery after interruption.
