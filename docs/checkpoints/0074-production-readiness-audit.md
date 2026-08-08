# CIVORA Checkpoint 0074 — Production Readiness Audit

Status: AUDIT_COMPLETE_REMEDIATION_REQUIRED

## Scope

Release-closure audit of the canonical CIVORA branch across runtime recovery, editorial safety, operator UX, packaging, CI portability, documentation, security assumptions and release governance.

This checkpoint introduces no product feature. Findings are prioritized by release impact.

## Executive result

Core runtime and editorial-safety architecture are release-candidate quality, but CIVORA is not yet eligible for a v1.0 release because packaging/release metadata and release-governance gates are incomplete.

### Strong areas

- Atomic durable stores with validation, backup recovery and fail-closed corruption handling.
- Cross-process locking and native Windows regression coverage.
- Transaction journal, bounded retry, dead-letter and audited resolution.
- Unified health, recovery ledger and startup health gate.
- Durable Fact Kernel and evidence/provenance binding.
- Claim/evidence reconciliation and explicit contradiction handling.
- Editorial gate, audited approval state machine and restart-safe re-entry.
- Authorized-fact-only story rendering; raw signal prose cannot bypass factual authorization.
- Cross-store editorial consistency and machine-readable remediation guidance.
- Operator CLI and deterministic remediation runbook.

## Release-blocking findings

### R1 — Declared Python lower bound is not validated

Severity: RELEASE_BLOCKER

`pyproject.toml` declares `requires-python = ">=3.10"`, while the Linux CI matrix validates only Python 3.11, 3.12 and 3.13. The release cannot claim Python 3.10 support without validating the lower bound.

Required remediation: add Python 3.10 to the CI matrix or raise the declared lower bound to the oldest validated version.

### R2 — Distribution artifact is not tested

Severity: RELEASE_BLOCKER

CI installs the repository in editable mode (`pip install -e .`) and runs tests. It does not build an sdist/wheel, install the built wheel in a clean environment, or smoke-test the installed console entrypoints.

Required remediation: add a packaging job that builds the distribution, installs the wheel and verifies the `civora` and `civora-remediation` entrypoints.

### R3 — Release metadata is stale

Severity: RELEASE_BLOCKER

`pyproject.toml` and `civora/__init__.py` still declare `0.1.0`. `README.md` still describes the repository as the initial v0.2 import and says newer checkpoints remain to be consolidated, which is no longer true.

Required remediation: refresh README/repository baseline now; version is to be locked only at release-candidate/final release after all release gates pass. Add a version-synchronization contract before final bump.

### R4 — Release governance artifacts are missing

Severity: RELEASE_BLOCKER

The canonical PR remains draft and the branch has not been integrated into `main`. There is no v1.0 release manifest/changelog/release-candidate declaration yet.

Required remediation: after technical gates pass, create RC manifest/changelog, run full final preflight, update version to v1.0.0, then require explicit human approval before irreversible merge/tag/release actions.

## Important warnings

### W1 — Repository visibility is public

Severity: OPERATIONAL_DECISION

The canonical GitHub repository is public. No obvious secret/token/password patterns were identified in the source search performed during this audit, and `.env` is ignored, but public visibility is an explicit operational/security posture and must be accepted before release. No repository visibility change is performed automatically.

### W2 — GitHub Actions are tag-pinned rather than commit-SHA-pinned

Severity: SECURITY_HARDENING

The workflow uses `actions/checkout@v4` and `actions/setup-python@v5`. This is common and functional but weaker against upstream tag movement than immutable SHA pinning.

Recommendation: pin third-party workflow actions to reviewed commit SHAs before or shortly after v1.0, depending on release policy.

### W3 — No dedicated static/security scanner gate

Severity: SECURITY_HARDENING

The release workflow is test-driven and does not currently include a dedicated SAST/dependency/secret-scanning step. Runtime has no declared third-party application dependencies, reducing dependency exposure, but this does not replace a security scan.

Recommendation: add lightweight security/scanning gates in the release or v1.1 hardening cycle.

## Non-blocking observations

- `docs/CANONICAL_IMPORT.md` remains useful as historical provenance, but should clearly identify itself as the initial import record rather than current status.
- The JSON Story Object schema is intentionally minimal and not currently the authoritative validator for the newer durable editorial stores. It should not be represented as a complete v1 API schema.
- Optional headline/style rewriting remains correctly deferred because evidence-preserving release safety has priority.

## Release gate matrix

- DURABLE_PERSISTENCE_RECOVERY: PASS
- CROSS_PROCESS_LOCKING: PASS
- CROSS_PLATFORM_RUNTIME_TESTS: PASS_BASELINE
- TRANSACTION_AND_DEAD_LETTER_AUDIT: PASS
- EDITORIAL_FACTUAL_SAFETY: PASS
- AUTHORIZED_RENDERING_ONLY: PASS
- OPERATOR_REMEDIATION_GUIDANCE: PASS
- OPERATOR_RUNBOOK: CODE_COMPLETE_CI_PENDING_0073
- PYTHON_SUPPORT_BOUNDARY: FAIL_RELEASE_BLOCKER
- BUILT_DISTRIBUTION_VALIDATION: FAIL_RELEASE_BLOCKER
- RELEASE_METADATA_CURRENT: FAIL_RELEASE_BLOCKER
- RELEASE_MANIFEST_CHANGELOG: NOT_YET_CREATED
- FINAL_RC_PREFLIGHT: NOT_YET_RUN
- HUMAN_RELEASE_APPROVAL: REQUIRED_LATER

## Remediation order

1. Validate the declared Python support boundary.
2. Add built-distribution + installed-entrypoint release validation.
3. Refresh README/current baseline and add release metadata/version consistency contracts.
4. Run full RC preflight.
5. Create v1.0 release manifest/changelog and lock version.
6. Request explicit human approval for merge/tag/release.

## Next action

Checkpoint 0075 Release Blocker Remediation: fix R1–R3 without adding product features, then run the expanded CI/release validation. R4 remains intentionally open until final technical validation and human release approval.
