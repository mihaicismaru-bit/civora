# CIVORA Checkpoint 0064 — Windows Lock Contention Hardening

Status: CODE_COMPLETE_CI_PENDING

## Objective

Restore cross-platform CI after a Windows-only multiprocess Review Queue failure exposed a platform-specific exclusive lock creation race.

## Root cause

On Windows Server 2025, concurrent `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` can surface `PermissionError: [Errno 13]` while another process owns or is creating the lock file. The lock implementation handled `FileExistsError` as contention but allowed this Windows form to escape, causing one Review Queue writer process to fail even though no data-integrity invariant was violated.

Linux Python 3.11, 3.12 and 3.13 all passed on the failing head; only `windows-native` failed.

## Implementation

`ProcessFileLock.acquire()` now treats `PermissionError` as lock contention only when the lock path actually exists. It then follows the same bounded contention path as `FileExistsError`, including conservative abandoned-lock recovery and timeout.

If `PermissionError` occurs and the lock path does not exist, the exception is re-raised. This preserves fail-closed behavior for genuine directory or filesystem permission failures.

The contention wait logic is centralized in `_wait_for_contention()` to keep FileExists and Windows access-denied handling behavior identical.

## Validation added

`tests/test_locking.py` adds deterministic coverage for:

- PermissionError + existing lock path → bounded contention / LockTimeoutError;
- PermissionError + absent lock path → original PermissionError propagated.

The pre-existing native multiprocess test remains the production-level regression test:

- `test_independent_review_queue_writers_do_not_lose_updates`.

## Gates

- WINDOWS_PERMISSION_RACE_CLASSIFICATION: PASS_IMPLEMENTATION
- GENUINE_PERMISSION_FAILURE_FAIL_CLOSED: PASS_IMPLEMENTATION
- BOUNDED_LOCK_CONTENTION: PASS_IMPLEMENTATION
- MULTIPROCESS_REVIEW_QUEUE_REGRESSION: CI_PENDING
- LINUX_TEST_MATRIX: CI_PENDING_CURRENT_HEAD
- WINDOWS_NATIVE: CI_PENDING_CURRENT_HEAD

## Remaining backlog

1. Confirm cross-platform CI on the repaired head.
2. Resume approval/Review Queue/transaction consistency inspection and health wiring.
3. Validate crash/recovery through approved pipeline re-entry.
4. Build Story Engine constrained to authorized/corroborated facts.
5. Expand operator runbooks.

## Next action

If current-head CI is green, close 0064 and immediately resume the editorial consistency-health checkpoint. If Windows still fails, inspect the exact native failure and keep cross-platform locking as priority 1.
