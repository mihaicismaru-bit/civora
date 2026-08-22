# CIVORA Checkpoint 0054 — Operational Control Surface

Status: CODE_COMPLETE_CI_PENDING

## Objective

Expose safe operator-facing commands for runtime health inspection and explicit dead-letter management without requiring direct edits to durable state files.

## Implemented

- Added `civora` console entry point.
- Added `civora health` for unified durable-state health inspection.
- Added `civora dead-letters` for listing unresolved dead-letter transactions.
- Added `civora resolve-dead-letter <id> --action requeue|abort --actor ... --reason ...`.
- Dead-letter resolution uses the existing audited transaction-resolution path and mirrors the resolution into the global recovery ledger.
- Health command uses deterministic exit codes: `0` healthy/recovered, `2` degraded/corrupt, `3` operational error.
- Added CLI integration tests covering healthy inspection, unhealthy exit status, dead-letter listing, audited requeue, and invalid transaction handling.

## Prior gate closure

Checkpoint 0053 Windows-native PID liveness recovery is validated by GitHub Actions run 31173385030, conclusion `success`. This closes the cross-platform persistence/recovery validation gate for the current runtime baseline.

## Gates

- WINDOWS_NATIVE_LOCK_RECOVERY: PASS
- CROSS_PLATFORM_PERSISTENCE_RECOVERY: PASS
- OPERATOR_HEALTH_COMMAND: PASS_IMPLEMENTATION_REVIEW
- OPERATOR_DEAD_LETTER_LIST: PASS_IMPLEMENTATION_REVIEW
- AUDITED_DEAD_LETTER_RESOLUTION_COMMAND: PASS_IMPLEMENTATION_REVIEW
- MACHINE_READABLE_JSON_OUTPUT: PASS_IMPLEMENTATION_REVIEW
- HEALTH_EXIT_CODE_CONTRACT: PASS_IMPLEMENTATION_REVIEW
- CURRENT_HEAD_CI: PENDING

## Remaining backlog

1. Validate checkpoint 0054 across Linux Python 3.11/3.12/3.13 and Windows-native CI.
2. Add recovery-event inspection and transaction-detail commands to the operational surface.
3. Add a bounded operator command for startup reconciliation/recovery dry-run.
4. Implement durable Fact Kernel.
5. Implement claim/evidence reconciliation.
6. Implement editorial approval state machine.

## Blockers

No credential or irreversible external-action blocker. Current closure depends only on CI validation of the new command surface.

## Next action

If CI is green, extend the operational surface with recovery-audit inspection and safe startup-reconciliation tooling, then begin the durable Fact Kernel. If CI fails, repair the failing platform/test before adding functional scope.
