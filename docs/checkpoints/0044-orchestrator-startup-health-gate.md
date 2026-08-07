# CIVORA Checkpoint 0044 — Orchestrator Startup Health Gate

Status: CODE_COMPLETE_CI_PENDING

## Objective

Prevent CIVORA from accepting new editorial work when durable runtime state is corrupt or remains degraded after recovery.

## Implemented

- Added `Orchestrator.startup_health_gate()`.
- Startup now performs health inspection before processing new work.
- Corrupt durable state blocks immediately and fail-closed before transaction replay.
- Pending transactions are replayed through the existing idempotent recovery path.
- Runtime health is inspected again after replay.
- New work is accepted only when the final runtime state is `healthy` or `recovered_from_backup`.
- `Orchestrator.run()` now invokes the startup health gate before writing the first story checkpoint.
- Default orchestrator health inspection covers the configured review queue, transaction journal, story checkpoint directory and recovery event ledger; callers may inject a wider `UnifiedHealthInspector` for full-runtime source/signal coverage.

## Validation added

`tests/test_startup_health.py` covers:

1. corrupt initial state blocks before recovery;
2. pending `story_to_review` transaction is replayed and committed before work acceptance;
3. runtime that remains degraded after recovery is blocked;
4. `recovered_from_backup` is explicitly allowed as a recoverable final state.

## Safety properties

- No new story checkpoint is intentionally accepted before startup health authorization.
- Corruption is not masked by replay attempts.
- Recovery is followed by mandatory re-inspection.
- Degraded state is fail-closed after recovery.
- Existing at-least-once transaction replay remains idempotency-dependent.

## Gates

- ORCHESTRATOR_STARTUP_HEALTH_GATE: PASS_IMPLEMENTATION_REVIEW
- FAIL_CLOSED_CORRUPT_STARTUP: PASS_IMPLEMENTATION_REVIEW
- RECOVER_THEN_REINSPECT: PASS_IMPLEMENTATION_REVIEW
- DEGRADED_AFTER_RECOVERY_BLOCK: PASS_IMPLEMENTATION_REVIEW
- RECOVERED_BACKUP_ALLOWED: PASS_IMPLEMENTATION_REVIEW
- AUTOMATED_TEST_EXECUTION: PENDING_CI
- PYTHON_3_11_3_13_MATRIX: PENDING_CI
- WINDOWS_NATIVE: PENDING

## Remaining backlog

1. Bounded transaction recovery retries and durable dead-letter state.
2. End-to-end multiprocess crash/recovery test for `story -> review`.
3. Full-runtime startup inspector wiring for source registry and signal store from a single runtime composition root.
4. Recovery-event deduplication/correlation for repeated health inspections.
5. Windows-native validation.
6. Fact Kernel and claim/evidence reconciliation.
7. Editorial approval state machine.

## Blockers

- CI validation must complete on the final checkpoint head.
- Native Windows behavior remains unvalidated until a Windows runner is available.

## Next action

Implement bounded recovery attempts with a durable dead-letter transaction state so permanently unrecoverable transactions cannot remain indefinitely in the `prepared` state while repeatedly degrading startup health.
