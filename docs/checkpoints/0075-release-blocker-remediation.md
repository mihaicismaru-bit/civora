# CIVORA Checkpoint 0075 — Release Blocker Remediation

Status: CODE_COMPLETE_CI_PENDING

## Objective

Remediate production-readiness audit blockers R1-R3 without adding product features. Irreversible release governance remains intentionally deferred until final validation and explicit human approval.

## Remediation implemented

### R1 — Python support boundary

The Linux CI matrix now validates Python 3.10, 3.11, 3.12 and 3.13. This aligns the declared `requires-python = ">=3.10"` lower bound with actual test coverage instead of silently claiming an unvalidated runtime.

### R2 — Built-distribution validation

Added a `package-smoke` GitHub Actions job that:

1. builds both sdist and wheel via `python -m build`;
2. creates a clean virtual environment;
3. installs the built wheel rather than the source tree;
4. imports CIVORA from that environment;
5. executes installed `civora --help`;
6. executes installed `civora-remediation --help`.

This closes the editable-install-only validation gap.

### R3 — Release metadata/documentation drift

Updated `README.md` to describe the current v1.0 release-closure state and implemented capabilities rather than the initial v0.2 import.

Updated `docs/CANONICAL_IMPORT.md` so it is explicitly historical bootstrap provenance, not current status.

Added `tests/test_release_metadata.py` to enforce:

- runtime `__version__` equals `pyproject.toml` project version;
- the declared Python lower bound remains explicit;
- README does not regress to the obsolete initial-import status language.

The numeric version remains pre-v1 until final RC/preflight passes. This avoids declaring v1.0 before the release gate is actually closed.

## Deferred release-governance blocker

R4 remains open by design:

- PR is still draft/open;
- branch is not merged into `main`;
- final v1.0 version bump is not yet applied;
- release manifest/changelog/tag are not yet finalized;
- explicit human approval is still required before merge/tag/release.

## Gates

- PYTHON_3_10_LOWER_BOUND_CI: PASS_IMPLEMENTATION
- PYTHON_3_11_3_13_CI_PRESERVED: PASS_IMPLEMENTATION
- WINDOWS_NATIVE_CI_PRESERVED: PASS_IMPLEMENTATION
- SDIST_WHEEL_BUILD: PASS_IMPLEMENTATION
- CLEAN_WHEEL_INSTALL: PASS_IMPLEMENTATION
- INSTALLED_CLI_SMOKE: PASS_IMPLEMENTATION
- README_CURRENT_BASELINE: PASS_IMPLEMENTATION
- IMPORT_PROVENANCE_CLARIFIED: PASS_IMPLEMENTATION
- VERSION_METADATA_SYNC_CONTRACT: PASS_IMPLEMENTATION
- CROSS_PLATFORM_AND_PACKAGE_CI: PENDING_CURRENT_CI

## Remaining release backlog

1. Close 0073 and 0075 after current CI validation.
2. Run full release-candidate preflight using the expanded CI gates.
3. Create changelog and release manifest.
4. Lock package/runtime version to `1.0.0` only after preflight succeeds.
5. Re-run final CI on the exact proposed release head.
6. Require explicit human approval before merge/tag/release.

## Next action

Checkpoint 0076 Release Candidate Preflight. If expanded CI exposes a Python 3.10, packaging or wheel-install defect, that defect becomes the immediate release blocker and must be repaired before preflight can close.
