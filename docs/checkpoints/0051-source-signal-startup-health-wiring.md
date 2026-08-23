# CIVORA Checkpoint 0051 — Source & Signal Startup Health Wiring

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the remaining startup-composition gap by making Source Registry and Signal Store part of the default fail-closed runtime health gate created by `Orchestrator`.

## Implementation

`Orchestrator` now defines canonical default paths inside `state_dir`:

- `sources.json` for `SourceRegistry`;
- `signals.json` for `SignalStore`.

Those paths are always passed to the default `UnifiedHealthInspector`, alongside review queue, transaction journal, story checkpoints and recovery ledger.

Deployments that keep source or signal state elsewhere can override the defaults with `source_registry_path=` and `signal_store_path=` without replacing the health inspector.

As a result:

1. unrecoverable Source Registry corruption participates in the initial startup inspection and blocks new work before recovery/replay;
2. Signal Store primary corruption can recover from a valid backup through the normal health probe;
3. that recovery is surfaced through the global `RecoveryEventLedger`;
4. source/signal health is re-inspected after transaction reconciliation/recovery before startup authorization.

## Validation added

`tests/test_startup_health.py` now covers:

- default startup health includes both `source_registry` and `signal_store` components;
- dual-generation Source Registry corruption blocks startup fail-closed;
- Signal Store primary corruption recovers from backup and emits a recovery audit event;
- explicit non-default source and signal paths are respected.

During the first CI execution, two unrelated regressions in the pre-existing test suite were exposed and repaired:

- checkpoint-0049 health-transition test incorrectly indexed the string transaction id as a dict;
- the core end-to-end test counted every JSON runtime artifact instead of explicitly asserting the four editorial checkpoint files, so the durable recovery ledger introduced by later checkpoints caused a false failure.

The repaired core test now validates the exact four checkpoint labels rather than relying on an obsolete global file count.

## Gates

- DEFAULT_SOURCE_REGISTRY_HEALTH_WIRING: PASS_IMPLEMENTATION_REVIEW
- DEFAULT_SIGNAL_STORE_HEALTH_WIRING: PASS_IMPLEMENTATION_REVIEW
- SOURCE_CORRUPTION_FAIL_CLOSED_STARTUP: TEST_ADDED
- SIGNAL_BACKUP_RECOVERY_STARTUP_PARTICIPATION: TEST_ADDED
- SIGNAL_RECOVERY_GLOBAL_AUDIT: TEST_ADDED
- EXPLICIT_SOURCE_SIGNAL_PATH_OVERRIDE: TEST_ADDED
- PREEXISTING_CI_REGRESSION_REPAIR: PASS_IMPLEMENTATION_REVIEW
- PYTHON_3_11_3_12_3_13_CURRENT_HEAD: PENDING_CI
- WINDOWS_NATIVE: PENDING

## Remaining backlog

1. Add native Windows persistence/locking validation.
2. Introduce production operational tooling/CLI for health inspection and dead-letter resolution.
3. Implement Fact Kernel claim/evidence aggregation.
4. Add temporal claim matching and contradiction reconciliation.
5. Add editorial approval state machine after the evidence layer is deterministic.

## Blockers

No user credential or irreversible-action blocker exists for this checkpoint. Native Windows validation remains environment-dependent.

## Next canonical action

Add Windows-native validation to the GitHub Actions matrix if a hosted Windows runner is available without external credentials; otherwise proceed to a stable operational health/dead-letter command surface before beginning Fact Kernel reconciliation.
