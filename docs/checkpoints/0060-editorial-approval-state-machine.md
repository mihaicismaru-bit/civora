# CIVORA Checkpoint 0060 — Editorial Approval State Machine

Status: CODE_COMPLETE_CI_PENDING

## Objective

Add a durable, auditable operator decision layer for stories blocked by the conflict/dispute editorial gate, and permit pipeline re-entry only after an exact approval tied to the current editorial decision and Fact Kernel.

## Implementation

Added `EditorialApprovalStore` with deterministic approval-case identity bound to:

- story ID;
- exact editorial gate `decision_id`;
- Fact Kernel `kernel_semantic_hash`.

A review gate decision creates one idempotent approval case in state `pending`.

Allowed terminal transitions are:

```text
pending -> approved
pending -> rejected
pending -> revision_required
```

Every operator transition requires non-empty `actor` and `reason`, records UTC time, previous state, target state, actor and reason, and is persisted through `AtomicJsonStore`.

Resolved cases are immutable. A revised story must produce a new Fact Kernel/gate decision and therefore a new approval case. This prevents stale approvals from authorizing changed evidence or facts.

## Orchestrator integration

When checkpoint 0059 returns `review`, the Orchestrator now creates/loads the matching pending approval case before blocking the story.

Added `resume_after_approval(story)`. Re-entry is allowed only if all of the following hold:

- story is currently `BLOCKED`;
- current durable editorial gate decision is `review`;
- approval case for the exact gate `decision_id` exists and is `approved`;
- approval story ID matches;
- current durable Fact Kernel semantic hash matches the approval;
- current editorial decision semantic hash matches the approval.

If any invariant fails, re-entry fails closed.

On successful re-entry the Orchestrator saves an `editorial_approved` checkpoint, then drafts and packages the story using the existing pipeline.

## Validation added

`tests/test_editorial_approval.py` covers:

- idempotent pending-case creation;
- audited approval with actor/reason;
- immutable terminal decisions;
- mandatory actor and reason;
- automatic pending-case creation for a disputed story;
- controlled pipeline re-entry after approval;
- rejection of re-entry while approval remains pending.

## Gates

- DURABLE_APPROVAL_CASE: PASS_IMPLEMENTATION
- EXACT_GATE_DECISION_BINDING: PASS_IMPLEMENTATION
- FACT_KERNEL_HASH_BINDING: PASS_IMPLEMENTATION
- AUDITED_OPERATOR_TRANSITION: PASS_IMPLEMENTATION
- TERMINAL_DECISION_IMMUTABILITY: PASS_IMPLEMENTATION
- STALE_APPROVAL_FAIL_CLOSED: PASS_IMPLEMENTATION
- ORCHESTRATOR_PENDING_CASE_CREATION: PASS_IMPLEMENTATION
- APPROVED_PIPELINE_REENTRY: PASS_IMPLEMENTATION
- UNAPPROVED_REENTRY_BLOCKED: PASS_IMPLEMENTATION
- CROSS_PLATFORM_TEST_MATRIX: PENDING_CURRENT_HEAD_CI

## Remaining backlog

1. Unified startup/health wiring for Fact Kernel, reconciliation, contradiction, editorial gate, and editorial approval stores.
2. Operator CLI for listing approval cases and applying approve/reject/revision-required actions.
3. Story Engine generation exclusively from approved/corroborated facts.
4. Review Queue lifecycle reconciliation after an approval/rejection decision.
5. End-to-end crash/recovery tests across approval transitions and pipeline re-entry.

## Blockers

Current-head cross-platform CI is required before checkpoint 0060 can be declared CLOSED_VALIDATED.

## Next action

If current-head CI passes, implement unified health wiring for all editorial durable stores so corruption or recovery of editorial truth participates in fail-closed startup authorization before adding Story Engine generation.
