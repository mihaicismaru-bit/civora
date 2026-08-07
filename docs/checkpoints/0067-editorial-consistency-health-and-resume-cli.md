# CIVORA Checkpoint 0067 — Editorial Consistency Health and Resume CLI

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the operator-observability and restart-control gap left after checkpoint 0066. Cross-store editorial consistency must be visible through the same unified health surface used by operators, and an approved story must be resumable after restart through the CLI without retaining Python objects in memory.

## Implementation

### Unified health consistency component

`UnifiedHealthInspector` now emits an `editorial_consistency` component whenever Editorial Approval, Review Queue and Transaction Journal paths are configured.

The component is produced by the production `EditorialConsistencyInspector` and exposes:

- approval case count;
- editorial resolution transaction count;
- unrecoverable mismatch count and details;
- recoverable crash-window mismatch count and details;
- exact durable-store paths involved in the invariant.

Status mapping is conservative:

- `healthy` — stores agree;
- `pending_transaction` — mismatch is exactly covered by a prepared editorial resolution transaction;
- `degraded` — mismatch is not recoverable from an exact prepared transaction;
- durable-store corruption remains fail-closed through the existing health error paths.

Because `pending_transaction` and `degraded` have unhealthy severity, the `civora health` command returns the existing unhealthy exit code until consistency is restored.

### Editorial consistency CLI

Added:

```text
civora --state-dir <path> editorial-consistency
```

The command exposes the same machine-readable consistency report directly and returns a non-zero unhealthy exit code whenever the state is not `healthy`.

### Restart-safe approved resume CLI

Added:

```text
civora --state-dir <path> resume-approved <story-id> [--version N]
```

The command delegates to the existing restart-safe `resume_approved_story()` path. It therefore reloads the durable `editorial_review` checkpoint, reconstructs fresh queue/journal/orchestrator objects, performs startup transaction replay and cross-store validation, verifies the exact approval binding, then resumes drafting/packaging. The command emits the resulting `StoryObject` as JSON.

Invalid versions, unknown/corrupt checkpoints, stale approvals and failed startup invariants return an operational error rather than bypassing the state machine.

## Validation added

`tests/test_editorial_cli_control.py` covers:

- unified health exposes `editorial_consistency` and becomes degraded for an approval case with no Review Queue item;
- `editorial-consistency` emits a machine-readable healthy report for an empty consistent state;
- `resume-approved` recovers a prepared approval-resolution crash window after restart and reaches `PACKAGED` while committing the transaction and synchronizing Review Queue.

Existing restart/recovery and cross-store consistency tests remain active as regression coverage.

## Gates

- CROSS_STORE_CONSISTENCY_IN_UNIFIED_HEALTH: PASS_IMPLEMENTATION
- UNRECOVERABLE_MISMATCH_DEGRADES_HEALTH: PASS_IMPLEMENTATION
- RECOVERABLE_MISMATCH_VISIBLE_AS_PENDING_TRANSACTION: PASS_IMPLEMENTATION
- MACHINE_READABLE_CONSISTENCY_CLI: PASS_IMPLEMENTATION
- RESTART_SAFE_APPROVED_RESUME_CLI: PASS_IMPLEMENTATION
- CLI_REUSES_PRODUCTION_RECOVERY_PATH: PASS_IMPLEMENTATION
- INVALID_RESUME_FAIL_CLOSED: PASS_IMPLEMENTATION
- OPERATOR_JSON_OUTPUT: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING_CURRENT_CI

## Remaining backlog

1. Story Engine constrained strictly to authorized/corroborated facts.
2. Operator remediation and recovery runbooks for consistency failures.
3. Explicit CLI recovery guidance for recoverable vs unrecoverable editorial consistency states.
4. Production packaging/readiness review after Story Engine authorization is enforced.

## Blockers

Current-head cross-platform CI is required before checkpoint 0067 can be declared `CLOSED_VALIDATED`.

## Next action

Validate checkpoint 0067 in CI. If green, begin the authorized Story Engine gate so article generation can consume only facts that are both allowed by the editorial decision path and supported by the durable fact/reconciliation records.
