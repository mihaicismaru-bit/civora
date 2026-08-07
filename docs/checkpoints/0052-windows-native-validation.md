# CIVORA Checkpoint 0052 — Windows-Native Validation

Status: CODE_COMPLETE_CI_PENDING

## Objective

Remove the remaining platform-validation gap in CIVORA persistence, process locking, crash recovery and startup health behavior by executing the full automated suite on a native hosted Windows runner.

## Implementation

The canonical GitHub Actions workflow now retains the existing Ubuntu matrix for Python 3.11, 3.12 and 3.13 and adds a dedicated `windows-native` job on `windows-latest` with Python 3.12.

The Windows job performs the same editable package installation and the same complete unittest discovery command as Linux, including cross-process locking and multiprocess crash/recovery coverage.

## Gates

- WINDOWS_NATIVE_WORKFLOW_JOB: PASS_IMPLEMENTATION_REVIEW
- FULL_TEST_SUITE_ON_WINDOWS: PENDING_CI
- PROCESS_LOCKING_ON_WINDOWS: PENDING_CI
- MULTIPROCESS_CRASH_RECOVERY_ON_WINDOWS: PENDING_CI
- PYTHON_3_12_WINDOWS_PACKAGE_INSTALL: PENDING_CI
- LINUX_PYTHON_3_11_3_12_3_13_REGRESSION: PENDING_CURRENT_HEAD

## Remaining backlog

1. Observe and repair any Windows-specific failures exposed by the native runner.
2. Add an operational CLI/command surface for unified health inspection, recovery audit and dead-letter resolution.
3. Begin Fact Kernel claim/evidence aggregation and contradiction reconciliation after platform validation closes.

## Blockers

No user credentials are required. Validation depends only on the hosted GitHub Actions runner completing the current workflow.

## Next canonical action

Inspect the Windows-native and Linux matrix results. If green, close the persistence/recovery platform gate and move to the operational health/dead-letter command surface. If Windows exposes a platform defect, repair that defect before advancing.
