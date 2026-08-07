# CIVORA Checkpoint 0061 — Editorial Durable-Store Health Wiring

Status: CODE_COMPLETE_CI_PENDING

## Objective

Bring every durable editorial store into the same fail-closed health boundary already protecting source ingestion, review queue, transactions, story checkpoints and the recovery ledger.

## Implementation

`UnifiedHealthInspector` now probes:

- Fact Kernel store;
- Fact Reconciliation store;
- Fact Contradiction store;
- Editorial Gate store;
- Editorial Approval store.

The Orchestrator wires the exact production paths of those stores into its default startup inspector. A corrupt, unrecoverable editorial store therefore blocks startup before new work is accepted.

The operational `civora health` command now uses the same editorial store paths, preventing divergence between operator-visible health and startup authorization.

Editorial work-state is intentionally separated from runtime integrity. Pending approval cases, review-required reconciliation reports and contradiction review counts remain visible in component details but do not degrade runtime health merely because work is awaiting editorial action.

Story checkpoint health discovery now recognizes the `editorial_review` and `editorial_approved` checkpoint labels introduced by the approval workflow.

## Recovery semantics

Editorial stores continue to use `AtomicJsonStore`. If a valid backup exists, health inspection may recover the primary generation and emits a recovery transition through the existing Recovery Event Ledger. If both primary and backup are invalid, the component is `corrupt` and startup fails closed.

## Validation added

`tests/test_editorial_health.py` covers:

- all five editorial stores are present in default Orchestrator startup health;
- `civora health` reports the same editorial components;
- empty editorial stores are healthy;
- unrecoverable Fact Kernel corruption blocks startup;
- Fact Kernel backup recovery is visible and audited;
- a pending approval remains healthy runtime state.

## Gates

- PRIOR_CHECKPOINT_0059_CI: PASS
- PRIOR_CHECKPOINT_0060_CI: PASS
- FACT_KERNEL_HEALTH_WIRING: PASS_IMPLEMENTATION
- RECONCILIATION_HEALTH_WIRING: PASS_IMPLEMENTATION
- CONTRADICTION_HEALTH_WIRING: PASS_IMPLEMENTATION
- EDITORIAL_GATE_HEALTH_WIRING: PASS_IMPLEMENTATION
- APPROVAL_HEALTH_WIRING: PASS_IMPLEMENTATION
- ORCHESTRATOR_STARTUP_FAIL_CLOSED: PASS_IMPLEMENTATION
- CLI_HEALTH_PARITY: PASS_IMPLEMENTATION
- EDITORIAL_CHECKPOINT_DISCOVERY: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING

## Remaining backlog

1. Validate checkpoint 0061 in the cross-platform CI matrix.
2. Add operator CLI for editorial cases, decisions, evidence and conflicts.
3. Reconcile Review Queue lifecycle after approve/reject/revision-required outcomes.
4. Add crash/recovery tests across approval transitions and approved re-entry.
5. Begin the Story Engine using only authorized/corroborated Fact Kernel material.

## Next action

If CI is green, implement the editorial operator control surface so approval and investigation can be performed through auditable commands without direct file manipulation.
