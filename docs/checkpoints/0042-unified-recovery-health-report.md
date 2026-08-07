# CIVORA Checkpoint 0042 — Unified Recovery & Health Report

Status: CLOSED_VALIDATED

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

GitHub Actions run `31140192038` completed successfully for the implementation/evidence head across Python 3.11, 3.12 and 3.13. Package installation and the full unit-test command passed in every matrix job.

## Gates

- UNIFIED_RUNTIME_HEALTH_VIEW: PASS
- COMPONENT_HEALTH_CLASSIFICATION: PASS
- RECOVERY_VISIBILITY: PASS
- PENDING_TRANSACTION_DEGRADATION: PASS
- FAIL_CLOSED_CORRUPTION_REPORTING: PASS
- HEALTH_REPORT_SERIALIZATION: PASS
- AUTOMATED_TEST_EXECUTION_PYTHON_3_11: PASS
- AUTOMATED_TEST_EXECUTION_PYTHON_3_12: PASS
- AUTOMATED_TEST_EXECUTION_PYTHON_3_13: PASS
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

## Next action

Add a durable append-only recovery event ledger and wire `UnifiedHealthInspector` into orchestrator startup so every recovery and degraded state becomes auditable and operationally actionable.
