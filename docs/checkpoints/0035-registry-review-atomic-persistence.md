# CIVORA Checkpoint 0035 — Registry and Review Atomic Persistence

Status: `CODE_COMPLETE_CI_PENDING`

## Scope

Migrates `SourceRegistry` and `ReviewQueue` from direct JSON writes to the shared `AtomicJsonStore` introduced in checkpoint 0034.

## Implemented

- schema version 2 for both stores;
- SHA-256 checksum validation;
- component-specific structural validators;
- atomic fsync-backed writes;
- previous-generation `.bak` retention;
- automatic recovery from a valid backup;
- fail-closed behavior when both generations are invalid;
- in-memory rollback when persistence fails;
- explicit `SourceRegistryError` and `ReviewQueueError` surfaces;
- persistence and recovery tests for both components.

## Acceptance gates

- `SOURCE_REGISTRY_ATOMIC_PERSISTENCE`: PASS — implementation and tests committed.
- `SOURCE_REGISTRY_BACKUP_RECOVERY`: PASS — test committed.
- `SOURCE_REGISTRY_FAIL_CLOSED`: PASS — test committed.
- `REVIEW_QUEUE_ATOMIC_PERSISTENCE`: PASS — implementation and tests committed.
- `REVIEW_QUEUE_BACKUP_RECOVERY`: PASS — test committed.
- `REVIEW_QUEUE_FAIL_CLOSED`: PASS — test committed.
- `IN_MEMORY_ROLLBACK_ON_SAVE_FAILURE`: PASS — implementation review.
- `GITHUB_CI_MATRIX`: PENDING external workflow execution.

## Remaining risk

`AtomicJsonStore` does not yet provide cross-process locking. Concurrent read-modify-write operations from multiple processes can still overwrite one another. This is the highest-priority next implementation.

## Next action

Add a standard-library cross-process file lock with stale-lock recovery and bounded acquisition timeout, integrate it into `AtomicJsonStore.save`, and add contention and failure-recovery tests.
