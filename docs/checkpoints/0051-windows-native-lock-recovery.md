# CIVORA Checkpoint 0051 — Windows-Native Lock Recovery

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the first real Windows-native persistence blocker discovered after adding the Windows GitHub Actions gate.

## Evidence from CI

Workflow run `31172987298` passed the full unit suite on Python 3.11, 3.12 and 3.13 under Linux. The Windows Server 2025 / Python 3.12 job failed only at `ProcessFileLockTests.test_abandoned_same_host_lock_is_recovered`.

The failing path used `os.kill(pid, 0)` as a cross-platform PID liveness probe. On Windows this does not provide the POSIX existence-probe semantics required by CIVORA's abandoned-lock recovery logic, so a non-existent PID could be treated conservatively as alive and an abandoned same-host lock would time out instead of being reclaimed.

## Implementation

`ProcessFileLock._pid_alive()` now dispatches to a Windows-specific Win32 probe when `os.name == "nt"`.

The Windows probe uses:

- `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`;
- `GetExitCodeProcess()` and `STILL_ACTIVE` when a handle is available;
- `ERROR_INVALID_PARAMETER` as evidence that the PID does not exist;
- conservative `alive` treatment for `ERROR_ACCESS_DENIED` and unknown query failures.

This preserves CIVORA's fail-safe rule: only a stale, same-host lock whose owner is positively known to be dead may be broken automatically.

## Tests

`tests/test_locking.py` now explicitly validates that:

1. the current process is reported alive;
2. a deliberately impossible PID is reported dead;
3. the pre-existing abandoned same-host lock recovery test remains the end-to-end acceptance test for stale-lock reclamation.

The multiprocess tests introduced in checkpoint 0050 already passed on the Windows runner; the only Windows failure was the PID liveness probe addressed here.

## Acceptance gates

- LINUX_PYTHON_3_11: PASS_PRE_FIX_HEAD
- LINUX_PYTHON_3_12: PASS_PRE_FIX_HEAD
- LINUX_PYTHON_3_13: PASS_PRE_FIX_HEAD
- WINDOWS_MULTIPROCESS_RECOVERY: PASS_PRE_FIX_HEAD
- WINDOWS_ABANDONED_LOCK_ROOT_CAUSE: CONFIRMED
- WINDOWS_NATIVE_PID_LIVENESS_IMPLEMENTATION: PASS_IMPLEMENTATION_REVIEW
- PORTABLE_PID_LIVENESS_TESTS: ADDED
- WINDOWS_FULL_SUITE_CURRENT_HEAD: PENDING_CURRENT_CI

## Remaining backlog

1. close Windows-native validation once CI passes on the current head;
2. reconcile checkpoint 0050 backlog because Source Registry and Signal Store startup-health wiring is already present and covered by integration tests in the canonical branch;
3. implement the Fact Kernel;
4. implement claim/evidence reconciliation;
5. add production operator tooling for health inspection and dead-letter resolution.

## Blockers

No user credentials or irreversible actions are required. Current validation is waiting only for GitHub Actions to execute against the new head.

## Next canonical action

If Windows CI passes, mark Windows-native persistence/locking validation closed and move immediately to the Fact Kernel: durable canonical fact records with provenance, confidence, temporal validity, and deterministic linkage to source evidence.
