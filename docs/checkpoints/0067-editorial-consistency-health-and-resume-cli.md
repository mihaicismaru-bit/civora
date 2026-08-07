# CIVORA Checkpoint 0067 — Editorial Consistency Health and Resume CLI

Status: CLOSED_VALIDATED

## Objective

Close the operator-observability and restart-control gap left after checkpoint 0066. Cross-store editorial consistency must be visible through the same unified health surface used by operators, and an approved story must be resumable after restart through the CLI without retaining Python objects in memory.

## Implementation

### Unified health consistency component

`UnifiedHealthInspector` emits an `editorial_consistency` component whenever Editorial Approval, Review Queue and Transaction Journal paths are configured. The production `EditorialConsistencyInspector` exposes approval cases, editorial resolution transactions, recoverable crash windows and unrecoverable mismatches.

Status mapping is conservative: `healthy` for agreement, `pending_transaction` for an exact prepared-transaction crash window, and `degraded` for mismatches that cannot be repaired from durable transaction evidence. Durable-store corruption remains fail-closed.

### Editorial consistency CLI

`civora --state-dir <path> editorial-consistency` exposes the same machine-readable report directly and returns a non-zero unhealthy exit code whenever the state is not healthy.

### Restart-safe approved resume CLI

`civora --state-dir <path> resume-approved <story-id> [--version N]` delegates to the production restart-safe recovery path: durable checkpoint rehydration, fresh queue/journal/orchestrator objects, transaction replay, consistency validation, exact approval binding and resume to drafting/packaging.

## Validation

`tests/test_editorial_cli_control.py`, restart/recovery tests and cross-store consistency tests remain active. GitHub Actions workflow run `31222108679` completed successfully for head `71ce34c3d7c5051bf4245f37a2a1ad2d38b06b06`.

## Gates

- CROSS_STORE_CONSISTENCY_IN_UNIFIED_HEALTH: PASS_VALIDATED
- UNRECOVERABLE_MISMATCH_DEGRADES_HEALTH: PASS_VALIDATED
- RECOVERABLE_MISMATCH_VISIBLE_AS_PENDING_TRANSACTION: PASS_VALIDATED
- MACHINE_READABLE_CONSISTENCY_CLI: PASS_VALIDATED
- RESTART_SAFE_APPROVED_RESUME_CLI: PASS_VALIDATED
- CLI_REUSES_PRODUCTION_RECOVERY_PATH: PASS_VALIDATED
- INVALID_RESUME_FAIL_CLOSED: PASS_VALIDATED
- OPERATOR_JSON_OUTPUT: PASS_VALIDATED
- CROSS_PLATFORM_CI: PASS_VALIDATED

## Remaining backlog

1. Story Engine constrained strictly to authorized/corroborated facts.
2. Operator remediation and recovery runbooks for consistency failures.
3. Explicit recovery guidance for recoverable vs unrecoverable editorial consistency states.
4. Production packaging/readiness review after Story Engine authorization is enforced.

## Blockers

None.

## Next action

Implement the authorized Story Engine gate so article generation consumes only facts that are grounded, corroborated, uncontested and bound to the current editorial authorization path.
