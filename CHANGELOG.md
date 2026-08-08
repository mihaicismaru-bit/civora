# Changelog

All notable CIVORA Core / Editorial Runtime changes are documented here for release closure.

## [1.0.0] - 2026-08-08

### Added

- Atomic JSON persistence with checksum validation, backup generations and fail-closed recovery.
- Cross-process locking with Windows-native abandoned-lock recovery.
- Durable transaction journal, bounded recovery, dead-letter handling and audited resolution.
- Recovery Event Ledger, unified health inspection and startup health gate.
- Source Registry and Signal Store integration into startup health.
- Operational CLI for health, transactions, dead letters, recovery events and resolution audit.
- Durable Fact Kernel with deterministic fact/evidence identity and provenance coverage.
- Claim/evidence reconciliation with source-independence scoring.
- Explicit contradiction engine and conflict/dispute resolution gate.
- Durable editorial approval state machine with actor/reason audit history.
- Review Queue lifecycle reconciliation and cross-store consistency inspection.
- Restart-safe approved-story re-entry after crash/restart.
- Authorized-fact-only Story Engine projection and operator inspection.
- Evidence-constrained reader-visible rendering and downstream content-pack propagation.
- Machine-readable editorial remediation guidance and operator remediation runbook.
- Cross-platform CI on Linux and Windows.
- Release-closure validation for Python 3.10-3.13 and built wheel/sdist smoke testing.
- Deterministic release-candidate preflight and release checklist.

### Changed

- GitHub is the canonical persistence and version-control layer for CIVORA development.
- Reader-visible rendering no longer falls back to raw signal prose.
- Editorial drafting is blocked by unsupported, unresolved, disputed or contradicted facts.
- README and canonical import documentation distinguish current release state from historical repository bootstrap provenance.

### Safety

- Automatic recovery remains limited to validated backup recovery and exact prepared transaction replay.
- Manual/committed divergence remains fail-closed.
- Human editorial approval cannot override unsupported, unlinked, disputed, contradicted or unresolved factual state.
- Irreversible merge/tag/release remains subject to explicit human approval.

## Historical bootstrap

The repository was bootstrapped on 2026-08-06 from the validated `CIVORA core runtime v0.2` artifact. Subsequent checkpoints were implemented and validated directly in the canonical GitHub branch.
