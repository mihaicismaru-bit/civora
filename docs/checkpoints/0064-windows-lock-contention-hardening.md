# CIVORA Checkpoint 0064 — Windows Lock Contention Hardening

Status: CLOSED_VALIDATED

## Objective

Restore cross-platform CI after a Windows-only multiprocess Review Queue failure exposed a platform-specific exclusive lock creation race.

## Root cause

On Windows Server 2025, concurrent `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` can surface `PermissionError: [Errno 13]` while another process owns or is creating the lock file. The lock implementation handled `FileExistsError` as contention but allowed this Windows form to escape, causing one Review Queue writer process to fail even though no data-integrity invariant was violated.

Linux Python 3.11, 3.12 and 3.13 all passed on the failing head; only `windows-native` failed.

## Implementation

`ProcessFileLock.acquire()` treats `PermissionError` as lock contention only when the lock path actually exists. It then follows the same bounded contention path as `FileExistsError`, including conservative abandoned-lock recovery and timeout.

If `PermissionError` occurs and the lock path does not exist, the exception is re-raised. This preserves fail-closed behavior for genuine directory or filesystem permission failures.

The contention wait logic is centralized so FileExists and Windows access-denied handling remain equivalent.

## Validation

Deterministic tests cover:

- PermissionError + existing lock path → bounded contention / LockTimeoutError;
- PermissionError + absent lock path → original PermissionError propagated.

The native multiprocess Review Queue regression also passed.

GitHub Actions run `31210681384` completed with `success` for head `3649493da7440b5b4b229e11c8841f756dc3ad6e`, including Linux Python 3.11/3.12/3.13 and Windows native.

## Gates

- WINDOWS_PERMISSION_RACE_CLASSIFICATION: PASS
- GENUINE_PERMISSION_FAILURE_FAIL_CLOSED: PASS
- BOUNDED_LOCK_CONTENTION: PASS
- MULTIPROCESS_REVIEW_QUEUE_REGRESSION: PASS_CI
- CROSS_PLATFORM_CI: PASS_CI

## Remaining backlog

1. Approval/Review Queue/transaction cross-store consistency inspection and startup wiring.
2. Crash/recovery validation through approved pipeline re-entry.
3. Story Engine constrained to authorized/corroborated facts.
4. Operator runbooks.

## Next action

Implement the editorial cross-store consistency gate so recoverable prepared transactions can be replayed but unrecoverable approval/queue/journal divergence blocks startup.
