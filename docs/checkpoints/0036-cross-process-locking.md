# CIVORA Checkpoint 0036 — Cross-process locking

Status: `CODE_COMPLETE_CI_PENDING`

## Scope

Protect every `AtomicJsonStore` load and save critical section from concurrent process access.

## Implemented

- portable exclusive lock-file creation using `O_CREAT | O_EXCL`;
- bounded acquisition timeout and deterministic `LockTimeoutError`;
- ownership token prevents a process from deleting a replacement lock;
- conservative abandoned-lock recovery;
- stale locks are removed only when they belong to the current host and the recorded PID is no longer alive;
- foreign-host and malformed locks fail closed;
- `AtomicJsonStore.load()` and `save()` now execute under the same locking primitive.

## Acceptance evidence

- exclusive acquisition and timeout test;
- same-host abandoned PID recovery test;
- foreign-host fail-closed test;
- ownership-token release safety test;
- persistence critical-section lock observation test.

## Gates

- `CROSS_PROCESS_EXCLUSION`: PASS_IMPLEMENTATION_REVIEW
- `BOUNDED_LOCK_WAIT`: PASS_IMPLEMENTATION_REVIEW
- `ABANDONED_LOCK_RECOVERY`: PASS_IMPLEMENTATION_REVIEW
- `FOREIGN_LOCK_FAIL_CLOSED`: PASS_IMPLEMENTATION_REVIEW
- `LOCK_OWNERSHIP_SAFE_RELEASE`: PASS_IMPLEMENTATION_REVIEW
- `AUTOMATED_TEST_EXECUTION`: PENDING_CI

## Remaining risks

- Windows-native execution has not yet been evidenced on a Windows runner.
- Lock files on shared storage from another host require operator intervention by design.
- Multi-store transactions are not yet atomic; each store is protected independently.

## Next action

Refactor `SignalStore` onto `AtomicJsonStore`, then introduce a coordinated transaction journal for signal, story, and review state transitions.
