# CIVORA Checkpoint 0078 — Windows errno-only contention remediation + release rebind

Status: RELEASE_METADATA_CLOSURE_CI_PENDING

## Objective

Resolve the Windows-native multiprocess Review Queue lock acquisition failure observed after checkpoint 0077, validate the fix across the complete CI matrix, and rebind v1.0 release metadata to the corrected runtime head without performing any irreversible release action.

## Defect

GitHub Actions run `31247609116` failed only in `windows-native` while Linux Python 3.10–3.13, package smoke and deterministic release preflight passed. The failing test was `test_independent_review_queue_writers_do_not_lose_updates`.

The subprocess failed in `ProcessFileLock.acquire()` when Windows returned `PermissionError: [Errno 13] Permission denied` for exclusive lock-file creation. In this race the exception contained no usable `winerror`, so the existing Win32 contention classifier treated the transient collision as a permanent permission failure.

## Implementation

- Added `_is_ambiguous_windows_eacces()` for the Windows-only errno=13/no-winerror shape.
- Added a strict maximum of two ambiguous EACCES retries.
- Kept explicit Win32 contention handling unchanged.
- Preserved fail-fast behavior for persistent and unknown permission failures.
- Added regression tests for successful transient retry and bounded persistent failure.

Runtime fix commits:
- `48e565d2c6a2df0480a999618297b8d3af279154` — bounded Windows errno-only contention retry.
- `f65daa29b3ac4255653d39dd36f016c7ed2bda3b` — regression coverage.

## Validation

Complete GitHub Actions workflow run `31256476768` on runtime head `f65daa29b3ac4255653d39dd36f016c7ed2bda3b`: SUCCESS.

Validated jobs:
- Linux Python 3.10: PASS
- Linux Python 3.11: PASS
- Linux Python 3.12: PASS
- Linux Python 3.13: PASS
- Windows native Python 3.12 full suite: PASS
- package-smoke: PASS
- deterministic release-preflight: PASS

## Completed gates

- WINDOWS_ERRNO_ONLY_EACCES_CLASSIFICATION: PASS
- WINDOWS_TRANSIENT_CONTENTION_BOUNDED_RETRY: PASS
- PERSISTENT_PERMISSION_FAIL_FAST: PASS
- WINDOWS_MULTIPROCESS_REVIEW_QUEUE: PASS
- CROSS_PLATFORM_FULL_SUITE: PASS
- PACKAGE_SMOKE: PASS
- RELEASE_PREFLIGHT: PASS
- RELEASE_RUNTIME_REBIND: PASS
- IRREVERSIBLE_RELEASE_ACTIONS: NOT_PERFORMED

## Release metadata

`docs/release/v1.0-release-manifest.json` and `docs/release/v1.0-release-checklist.md` now bind the release payload to remediated runtime head `f65daa29b3ac4255653d39dd36f016c7ed2bda3b`, workflow run `31256476768`.

This checkpoint and associated release-document changes are metadata-only after the validated runtime head. Per the non-self-referential closure policy, the final metadata closure head must pass the unchanged complete workflow. If it does, CIVORA becomes `RELEASE_READY_TECHNICAL` without another repository mutation.

## Backlog snapshot

P0 OPEN — metadata-only closure head complete CI validation.
GOVERNANCE BLOCKED_BY_POLICY — explicit human approval before PR ready-state, merge, tag, GitHub Release or deployment.
OPTIONAL — immutable SHA pinning for GitHub Actions.
OPTIONAL — dedicated static/secret/security scanning gate.

## Blockers

Technical blocker: NONE after runtime workflow `31256476768`.
Current closure gate: CI_PENDING on metadata-only closure head.
Human release approval: REQUIRED before irreversible release operations.

## Next action

Run/observe the complete workflow on the final metadata-only closure head. If all jobs pass, classify checkpoint 0078 as `RELEASE_READY_TECHNICAL` by the documented closure rule and stop before any merge, tag, release or deployment without explicit human approval.
