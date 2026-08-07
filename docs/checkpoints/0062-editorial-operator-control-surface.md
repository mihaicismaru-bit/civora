# CIVORA Checkpoint 0062 — Editorial Operator Control Surface

Status: CODE_COMPLETE_CI_PENDING

## Objective

Expose the durable editorial decision chain and approval state machine through auditable CLI commands so operators do not need to edit persistence files directly.

## Implementation

Added read-only commands:

- `civora --state-dir <path> editorial-story <story-id>`
- `civora --state-dir <path> approval-cases [--state pending|approved|rejected|revision_required]`
- `civora --state-dir <path> approval-case <case-id>`

`editorial-story` returns the current Fact Kernel, reconciliation report, contradiction report, editorial gate decision and approval case for a story in one machine-readable JSON object.

Added audited mutation:

- `civora --state-dir <path> decide-approval <case-id> --action approved|rejected|revision_required --actor <actor> --reason <reason>`

The command delegates to `EditorialApprovalStore.decide`; it does not bypass state-machine validation. Resolved cases remain terminal and cannot be silently overwritten.

`EditorialApprovalStore.list_cases()` provides deterministic case listing with optional state filtering.

## Validation added

`tests/test_cli.py` covers:

- pending approval listing/filtering;
- approval case inspection;
- approval decision with actor/reason audit;
- terminal-case protection against a second decision;
- aggregated editorial story inspection;
- unknown editorial story fail-closed behavior.

## Gates

- CHECKPOINT_0061_CROSS_PLATFORM_CI: PASS
- EDITORIAL_STORY_INSPECTION: PASS_IMPLEMENTATION
- APPROVAL_CASE_LISTING: PASS_IMPLEMENTATION
- APPROVAL_STATE_FILTERING: PASS_IMPLEMENTATION
- APPROVAL_CASE_DETAIL: PASS_IMPLEMENTATION
- AUDITED_APPROVAL_DECISION: PASS_IMPLEMENTATION
- TERMINAL_CASE_IMMUTABILITY: PASS_IMPLEMENTATION
- DIRECT_DURABLE_FILE_EDIT_REQUIRED: ABSENT
- MACHINE_READABLE_OUTPUT: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING

## Remaining backlog

1. Validate checkpoint 0062 in the cross-platform CI matrix.
2. Reconcile Review Queue lifecycle after approved/rejected/revision-required outcomes.
3. Add crash/recovery tests across approval transition and approved pipeline re-entry.
4. Build the Story Engine constrained to authorized/corroborated facts.
5. Add operator runbooks after lifecycle commands stabilize.

## Blockers

Current-head CI is required before `CLOSED_VALIDATED` can be declared.

## Next action

If CI is green, implement Review Queue lifecycle reconciliation so approval state and queue state cannot diverge. If CI fails, repair the regression before feature expansion.
