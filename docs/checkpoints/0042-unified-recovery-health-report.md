# CIVORA Checkpoint 0042 — Unified Recovery & Health Report

Status: CODE_COMPLETE_CI_PENDING

## Objective

Create one runtime-level health view across CIVORA durable state so recovery, corruption, and pending transactional work are observable without inspecting each store independently.

## Implemented

- Added `civora.health.UnifiedHealthInspector`.
- Added structured `RuntimeHealthReport` and `ComponentHealth` records.
- Aggregates optional probes for Source Registry, Signal Store, Review Queue, Transaction Journal, and Story Checkpoints.
- Surfaces component states: `healthy`, `recovered_from_backup`, `pending_transaction`, `degraded`, and `corrupt`.
- Computes an overall runtime state from the worst component severity.
- Health probes use production store validation and therefore preserve fail-closed behavior.
- A valid backup may repair a primary generation during inspection; the recovery is explicitly surfaced rather than hidden.
- Prepared transactions make the runtime `degraded` until replay/commit completes.
- Unexpected operational probe failures (for example lock contention/timeouts) are reported as `degraded` rather than crashing the inspector.
- Story checkpoint inspection covers the canonical labels `signal`, `verified`, `drafted`, and `packaged` and reports corrupt checkpoint generations.

## Validation added

`tests/test_health.py` covers:

- empty inspector configuration;
- healthy configured stores;
- degradation caused by a prepared transaction;
- visible backup recovery;
- unrecoverable corruption;
- plain-dict serialization of the report.

## Gates

- UNIFIED_RUNTIME_HEALTH_VIEW: PASS_IMPLEMENTATION_REVIEW
- COMPONENT_HEALTH_CLASSIFICATION: PASS_IMPLEMENTATION_REVIEW
- RECOVERY_VISIBILITY: PASS_IMPLEMENTATION_REVIEW
- PENDING_TRANSACTION_DEGRADATION: PASS_IMPLEMENTATION_REVIEW
- FAIL_CLOSED_CORRUPTION_REPORTING: PASS_IMPLEMENTATION_REVIEW
- HEALTH_REPORT_SERIALIZATION: PASS_IMPLEMENTATION_REVIEW
- AUTOMATED_TEST_EXECUTION: PENDING_CI
- WINDOWS_NATIVE_VALIDATION: PENDING

## Remaining priority backlog

1. Persist append-only recovery/health events for audit and trend analysis.
2. Integrate the health inspector into the orchestrator startup path and expose a stable CLI/report command.
3. Add stale-writer/multiprocess integration tests around the complete story-to-review transaction.
4. Add bounded transaction retry policy and dead-letter/escalation state.
5. Introduce Fact Kernel / claim evidence aggregation and contradiction reconciliation.
6. Add editorial approval state machine and publication adapters only after runtime recovery gates are closed.

## Blockers

- Native Windows behavior still requires a Windows runner.
- Current checkpoint remains CI-pending until the Python 3.11–3.13 workflow completes for the latest head.

## Next action

Add a durable append-only recovery event ledger and wire `UnifiedHealthInspector` into orchestrator startup so every recovery and degraded state becomes auditable and operationally actionable.
