# CIVORA Checkpoint 0065 — Editorial Cross-Store Consistency Gate

Status: CODE_COMPLETE_CI_PENDING

## Objective

Prevent CIVORA from accepting new work when the authoritative editorial approval state, Review Queue lifecycle, and transaction journal disagree after startup recovery.

## Implementation

Added `EditorialConsistencyInspector` as a read-only cross-store invariant checker over:

- `editorial_approval.json`;
- `review_queue.json`;
- `transactions.json` entries for `editorial_review_resolution`.

Approval remains the authoritative operator decision. When Review Queue is active, every editorial approval case must have a matching queue item in the same lifecycle state.

### Recoverable divergence

A temporary approval/queue mismatch is classified as `pending_transaction` only when an exact prepared editorial-resolution transaction binds:

- the same approval `case_id`;
- the same `story_id`;
- the same terminal `action`.

This represents the supported crash window after the approval-store write but before Review Queue resolution/transaction commit.

### Unrecoverable divergence

The inspector reports `degraded` for states including:

- approval case with missing Review Queue item and no exact prepared repair transaction;
- approval and Review Queue lifecycle state mismatch without an exact prepared repair transaction;
- resolution transaction referencing a missing approval case;
- transaction story/case mismatch;
- committed editorial-resolution transaction whose action is not reflected by both approval and Review Queue.

No store is mutated by the inspector.

## Startup integration

`Orchestrator.startup_health_gate()` now follows:

```text
individual durable-store health
→ resolution-audit reconciliation
→ prepared transaction replay
→ editorial cross-store consistency inspection
→ final unified health
→ accept work
```

Prepared transactions are therefore given their supported recovery opportunity first. After replay, anything other than `healthy` cross-store consistency blocks startup fail-closed.

## Validation added

`tests/test_editorial_consistency.py` covers:

- pending approval + pending queue = healthy;
- exact prepared resolution covering approval/queue divergence = pending_transaction;
- committed resolution with queue divergence = degraded;
- startup replay repairs a prepared resolution and commits it;
- startup rejects a committed cross-store divergence.

## Gates

- APPROVAL_QUEUE_STATE_INVARIANT: PASS_IMPLEMENTATION
- EXACT_PREPARED_TRANSACTION_RECOVERABILITY: PASS_IMPLEMENTATION
- COMMITTED_TRANSACTION_REFLECTION: PASS_IMPLEMENTATION
- READ_ONLY_CONSISTENCY_INSPECTION: PASS_IMPLEMENTATION
- STARTUP_REPLAY_BEFORE_CONSISTENCY_GATE: PASS_IMPLEMENTATION
- POST_RECOVERY_FAIL_CLOSED: PASS_IMPLEMENTATION
- REGRESSION_TESTS: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING_CURRENT_CI

## Remaining backlog

1. Integrate cross-store consistency as an explicit component in unified `civora health` output for operator parity.
2. Expand crash/recovery validation through `approved → resume_after_approval → packaged` re-entry.
3. Build Story Engine constrained to authorized/corroborated facts only.
4. Add operator runbooks and remediation guidance for degraded consistency states.

## Blockers

Current-head cross-platform CI result is required before `CLOSED_VALIDATED` can be declared.

## Next action

If CI is green, close 0065 and add unified-health/CLI visibility for the same cross-store invariant, then exercise crash recovery through approved pipeline re-entry. If CI fails, repair the regression before expanding scope.
