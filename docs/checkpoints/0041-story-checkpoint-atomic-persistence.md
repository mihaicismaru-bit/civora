# Checkpoint 0041 — Story checkpoint atomic persistence

Status: CODE_COMPLETE_CI_PENDING

## Objective

Remove direct `Path.write_text()` persistence from editorial story checkpoints and move them onto the canonical durable persistence primitive.

## Changes

- Added `StoryCheckpointStore` in `civora/checkpoints.py`.
- Story checkpoints now use `AtomicJsonStore` with schema versioning and SHA-256 checksum validation.
- Checkpoint writes inherit atomic temporary-file replacement, `fsync`, cross-process locking, previous-generation backup, backup recovery and fail-closed behavior.
- `Orchestrator` now delegates all checkpoint writes to `StoryCheckpointStore`.
- Added tests for checksum protection, recovery from a corrupt primary generation and fail-closed behavior when both generations are invalid.

## Acceptance gates

- DIRECT_CHECKPOINT_WRITE_REMOVED: PASS_IMPLEMENTATION_REVIEW
- CHECKPOINT_CHECKSUM: PASS_IMPLEMENTATION_REVIEW
- CHECKPOINT_ATOMIC_REPLACEMENT: PASS_IMPLEMENTATION_REVIEW
- CHECKPOINT_CROSS_PROCESS_LOCKING: PASS_IMPLEMENTATION_REVIEW
- CHECKPOINT_BACKUP_RECOVERY: PASS_IMPLEMENTATION_REVIEW
- CHECKPOINT_FAIL_CLOSED: PASS_IMPLEMENTATION_REVIEW
- AUTOMATED_TEST_MATRIX: PENDING_CI
- WINDOWS_NATIVE_VALIDATION: PENDING

## Remaining risk

The checkpoint files are individually durable, but system health is still fragmented across stores. Operators cannot yet obtain one canonical recovery/health view covering source, signal, review, transaction and editorial checkpoint persistence.

## Next action

Implement a unified recovery and health report that inspects all durable stores, reports backup recovery and corruption states, and exposes pending/failed transaction recovery as one deterministic runtime health snapshot.
