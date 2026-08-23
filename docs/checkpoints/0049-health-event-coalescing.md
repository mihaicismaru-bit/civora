# CIVORA Checkpoint 0049 — Health Event Coalescing

Status: CODE_COMPLETE_CI_PENDING

## Objective

Prevent repeated startup and runtime health inspections from growing `RecoveryEventLedger` indefinitely when a component remains in the same state, while preserving every materially distinct state transition for audit and recovery analysis.

## Implementation

`RecoveryEventLedger` now exposes `observe_health()` as a state-oriented companion to the existing append-only `append()` API.

Health observations are reconciled atomically inside `AtomicJsonStore.update()`:

1. locate the latest health event for the component;
2. suppress a new write when event type, status, and details are unchanged;
3. keep initial healthy state silent;
4. persist a `health_transition` event when a previously observed problem returns to healthy;
5. allow the same prior problem to be recorded again after that healthy transition;
6. keep materially changed details as a distinct event even when the status string is unchanged.

This design preserves append-only audit semantics: existing events are never edited or removed. Coalescing is decided under the same durable store lock used for persistence, preventing concurrent inspectors from creating duplicate observations.

`UnifiedHealthInspector._record_events()` now routes component observations through `observe_health()` rather than appending every non-healthy report directly.

## Validation added

`tests/test_recovery.py` covers:

- repeated identical observations are coalesced;
- initial healthy observations remain silent;
- problem -> healthy -> same problem produces three auditable transitions;
- same status with materially different details remains distinct.

`tests/test_health.py` covers integration through `UnifiedHealthInspector`:

- repeated inspection of one pending transaction produces only one ledger event;
- clearing the pending transaction records a healthy transition;
- a later new pending transaction is recorded again;
- a fully healthy initial runtime does not create health noise.

## Gates

- HEALTH_EVENT_ATOMIC_COALESCING: PASS_IMPLEMENTATION_REVIEW
- REPEATED_STARTUP_LEDGER_GROWTH_BOUND: PASS_IMPLEMENTATION_REVIEW
- HEALTHY_TRANSITION_AUDIT: PASS_IMPLEMENTATION_REVIEW
- FAULT_RECURRENCE_VISIBILITY: PASS_IMPLEMENTATION_REVIEW
- MATERIAL_DETAIL_CHANGE_VISIBILITY: PASS_IMPLEMENTATION_REVIEW
- CONCURRENT_COALESCING_DESIGN: PASS_IMPLEMENTATION_REVIEW
- PYTHON_3_11_3_12_3_13: CI_PENDING
- WINDOWS_NATIVE: PENDING

## Remaining backlog

1. add multiprocess end-to-end crash/recovery tests for `story -> review`, health coalescing, and transaction reconciliation;
2. wire Source Registry and Signal Store paths into default orchestrator health composition;
3. add Windows-native validation;
4. begin Fact Kernel / claim-evidence reconciliation after persistence/recovery gates are closed.

## Blockers

No credential or irreversible-action blocker. Current checkpoint closure depends only on validation of the latest branch head in GitHub Actions.

## Next canonical action

Add multiprocess end-to-end crash/recovery tests that exercise the durable transaction, review queue, recovery ledger, and health gate through real competing processes rather than only independent in-process store instances.
