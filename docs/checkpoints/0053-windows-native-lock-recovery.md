# CIVORA Checkpoint 0053 — Windows-Native Lock Recovery

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the first concrete Windows-native persistence defect exposed by checkpoint 0052 validation.

## CI evidence and root cause

Workflow run `31172987298` passed the complete Linux matrix on Python 3.11, 3.12 and 3.13. The Windows Server 2025 / Python 3.12 job failed only at `ProcessFileLockTests.test_abandoned_same_host_lock_is_recovered`.

The failed path used `os.kill(pid, 0)` as a cross-platform PID-liveness probe. On Windows this does not provide the POSIX existence-test semantics required by CIVORA's abandoned-lock recovery rule, so a deliberately non-existent PID could be treated conservatively as alive and a stale same-host lock would time out instead of being reclaimed.

## Implementation

`ProcessFileLock._pid_alive()` now dispatches to a Windows-specific Win32 probe when `os.name == "nt"`.

The Win32 probe uses:

- `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`;
- `GetExitCodeProcess()` and `STILL_ACTIVE` when a process handle is available;
- `ERROR_INVALID_PARAMETER` as positive evidence that the PID does not exist;
- conservative `alive` treatment for `ERROR_ACCESS_DENIED` and unknown query failures.

This preserves the fail-safe rule that CIVORA may break only a stale, same-host lock whose owner is positively known to be dead.

## Tests

`tests/test_locking.py` now explicitly validates:

1. the current process is reported alive;
2. a deliberately impossible PID is reported dead;
3. the existing stale same-host lock recovery scenario remains the end-to-end acceptance test.

The checkpoint-0050 multiprocess crash/recovery and concurrent writer tests already passed on the Windows runner in run `31172987298`; the only Windows failure was the PID-liveness defect addressed here.

## Acceptance gates

- LINUX_PYTHON_3_11_PRE_FIX_HEAD: PASS
- LINUX_PYTHON_3_12_PRE_FIX_HEAD: PASS
- LINUX_PYTHON_3_13_PRE_FIX_HEAD: PASS
- WINDOWS_PACKAGE_INSTALL_PRE_FIX_HEAD: PASS
- WINDOWS_MULTIPROCESS_RECOVERY_PRE_FIX_HEAD: PASS
- WINDOWS_ABANDONED_LOCK_ROOT_CAUSE: CONFIRMED
- WINDOWS_NATIVE_PID_LIVENESS_IMPLEMENTATION: PASS_IMPLEMENTATION_REVIEW
- PORTABLE_PID_LIVENESS_TESTS: ADDED
- WINDOWS_FULL_SUITE_CURRENT_HEAD: PENDING_CURRENT_CI
- LINUX_MATRIX_CURRENT_HEAD: PENDING_CURRENT_CI

## Remaining backlog

1. close Windows-native persistence/locking validation after current-head CI passes;
2. operational CLI/command surface for unified health inspection, recovery audit and dead-letter resolution;
3. durable Fact Kernel with source/evidence provenance and temporal validity;
4. claim/evidence reconciliation and contradiction handling;
5. editorial approval state machine over verified fact sets.

## Blockers

No user credentials or irreversible external actions are required. Validation now depends only on GitHub Actions executing the current head.

## Next canonical action

If current-head CI is green, close the platform persistence/recovery gate and implement the operational health/dead-letter command surface before beginning Fact Kernel work. If another Windows-specific defect appears, repair it before advancing.
