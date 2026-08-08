# CIVORA Checkpoint 0071 — Editorial Remediation Control Plane

Status: CODE_COMPLETE_CI_PENDING

## Objective

Turn editorial consistency findings into deterministic operator guidance without introducing unsafe automatic repair. CIVORA must distinguish exact crash-recovery windows from ambiguous or committed durable-state divergence and must remain fail-closed whenever the evidence does not justify automatic replay.

## Implementation

Added `civora/editorial_remediation.py` with `EditorialRemediationPlanner`.

The planner consumes the existing read-only `EditorialConsistencyInspector` report and emits one of three machine-readable classifications:

- `no_action` — durable editorial stores are consistent;
- `automatic_recovery_available` — every mismatch is already covered by an exact `prepared` editorial resolution transaction and may be resolved by the existing idempotent startup replay path;
- `manual_investigation_required` — at least one mismatch is not safely recoverable from an exact prepared transaction. CIVORA must remain fail-closed and no synthetic repair is proposed.

Each action includes mismatch type, relevant story/case/transaction identifiers, whether automation is safe, the permitted operation, and read-only inspection commands.

Added `civora/remediation_cli.py` and the package command:

```text
civora-remediation --state-dir <path>
```

The command emits JSON containing both the raw editorial consistency report and the derived remediation plan. It is deliberately read-only. Healthy state exits 0; any state requiring recovery or investigation exits 2 so automation can distinguish operational action from success without mutating durable state.

## Safety properties

- Automatic recovery guidance is emitted only for mismatches already classified recoverable by `EditorialConsistencyInspector` through an exact prepared transaction.
- Committed divergence is never auto-repaired.
- Missing approval cases, story/transaction mismatch, missing queue items without exact prepared coverage, and approval/queue divergence without exact prepared coverage are manual fail-closed conditions.
- The planner never writes to Approval Store, Review Queue or Transaction Journal.
- Manual remediation guidance instructs inspection rather than synthesis or overwrite of durable state.
- Existing startup replay remains the only automatic mutation path for recoverable editorial resolution transactions.

## Validation added

`tests/test_editorial_remediation.py` covers healthy, prepared-recoverable, committed-divergent and mixed reports.

`tests/test_remediation_cli.py` exercises the real durable stores and verifies JSON/exit-code behavior for healthy state, a prepared crash window and committed divergence.

## Gates

- MACHINE_READABLE_REMEDIATION_CLASSIFICATION: PASS_IMPLEMENTATION
- EXACT_PREPARED_ONLY_AUTO_RECOVERY: PASS_IMPLEMENTATION
- COMMITTED_DIVERGENCE_FAIL_CLOSED: PASS_IMPLEMENTATION
- READ_ONLY_OPERATOR_SURFACE: PASS_IMPLEMENTATION
- IDENTIFIER_BOUND_INSPECTION_GUIDANCE: PASS_IMPLEMENTATION
- OPERATOR_EXIT_CODE_SIGNALING: PASS_IMPLEMENTATION
- REGRESSION_TESTS: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING_CURRENT_CI

## Remaining backlog

1. Integrate remediation summary directly into the primary `civora health`/`civora editorial-consistency` output without duplicating policy.
2. Add operator runbook examples for backup restore and evidence-preserving manual repair procedures.
3. Optional evidence-preserving style layer for more natural reader-visible headlines.
4. Production-readiness review covering crash recovery, durable health, editorial safety, packaging, operations, security assumptions and release gates.

## Blockers

Current-head cross-platform CI result is required before this checkpoint can be declared `CLOSED_VALIDATED`.

## Next action

If CI passes, close 0071 and integrate the same remediation plan into unified health so monitoring systems receive actionable editorial-state guidance from the primary operational endpoint.
