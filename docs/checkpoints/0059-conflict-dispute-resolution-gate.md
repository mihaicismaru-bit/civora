# CIVORA Checkpoint 0059 — Conflict/Dispute Resolution Gate

Status: CODE_COMPLETE_CI_PENDING

## Objective

Make editorial reasoning enforceable. Reconciliation and contradiction reports must now determine whether a story may be drafted automatically or must be routed to review.

## Implementation

Added `ConflictResolutionGate`, which validates that reconciliation and contradiction reports refer to the same story, Fact Kernel, revision, and semantic hash. Misaligned reports fail closed.

Production policy is conservative: automatic drafting is allowed only when confirmed facts are corroborated and contradiction analysis is clear. Any disputed, contradicted, unresolved, unsupported, or insufficiently corroborated state returns a deterministic `review` decision with stable reason codes.

Added `EditorialGateStore`, which persists decisions atomically and idempotently. Decision identity is bound to the Fact Kernel semantic hash, exact reconciliation/contradiction report IDs, and editorial gate policy.

The Orchestrator now executes:

```text
verify
→ Fact Kernel
→ reconciliation
→ contradiction analysis
→ editorial gate
→ auto draft OR review queue
```

If the gate returns `review`, CIVORA sets the story to `BLOCKED`, saves an `editorial_review` checkpoint, and routes it to the existing transactional review queue before any article is generated.

## Validation added

`tests/test_editorial_gate.py` covers:

- corroborated + conflict-free input allows auto drafting;
- conflict blocks drafting;
- insufficient support blocks under production policy;
- report misalignment fails closed;
- explicit dispute is routed by the full Orchestrator to review with no article generated.

The existing end-to-end fixture was strengthened so its confirmed fact is independently corroborated by two explicit evidence records and therefore legitimately passes the new production gate.

## Gates

- REPORT_ALIGNMENT_FAIL_CLOSED: PASS_IMPLEMENTATION
- CORROBORATION_REQUIRED_FOR_AUTO_DRAFT: PASS_IMPLEMENTATION
- CONFLICT_BLOCKS_AUTO_DRAFT: PASS_IMPLEMENTATION
- DISPUTED_BLOCKS_AUTO_DRAFT: PASS_IMPLEMENTATION
- CONTRADICTED_BLOCKS_AUTO_DRAFT: PASS_IMPLEMENTATION
- UNRESOLVED_BLOCKS_AUTO_DRAFT: PASS_IMPLEMENTATION
- DURABLE_EDITORIAL_DECISION: PASS_IMPLEMENTATION
- ORCHESTRATOR_PRE_DRAFT_ENFORCEMENT: PASS_IMPLEMENTATION
- TRANSACTIONAL_REVIEW_ROUTING: PASS_IMPLEMENTATION
- CROSS_PLATFORM_TEST_MATRIX: PENDING_CURRENT_HEAD_CI

## Remaining backlog

1. Editorial approval state machine for human/operator resolution and re-entry into the pipeline.
2. Unified health wiring for Fact Kernel, reconciliation, contradiction, and editorial gate stores.
3. Story Engine generation exclusively from approved/corroborated facts.
4. Operator CLI for inspecting facts, evidence, conflicts, and editorial decisions.
5. End-to-end editorial recovery tests across approval/rejection transitions.

## Blockers

Current-head CI must pass before checkpoint 0059 can be declared CLOSED_VALIDATED.

## Next action

If CI is green, implement checkpoint 0060: durable Editorial Approval State Machine with explicit pending/approved/rejected/revision-required transitions and auditable operator decisions.
