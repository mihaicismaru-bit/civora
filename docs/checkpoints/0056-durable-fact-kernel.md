# CIVORA Checkpoint 0056 — Durable Fact Kernel

## Objective

Move CIVORA from infrastructure-only hardening into the accelerated editorial-engine phase by making the Fact Kernel a durable, revisioned and provenance-aware runtime artifact.

## Implemented

- `FactKernelStore` backed by the canonical `AtomicJsonStore`.
- Deterministic `kernel_id`, `fact_id`, `claim_id` and `evidence_id` identities.
- Durable `story_id → kernel_id` index.
- Semantic-hash idempotence: identical kernels do not create artificial revisions.
- Revision history when the semantic kernel changes.
- Exact-normalized evidence linkage for conservative provenance.
- `grounded` / `unlinked` provenance state per confirmed fact.
- Kernel-level `provenance_coverage`, `independent_source_count` and editorial gate.
- `needs_review` gate when a confirmed statement lacks linked evidence.
- Backup recovery and fail-closed corruption behavior inherited from `AtomicJsonStore`.
- Automatic persistence from `Orchestrator` immediately after story verification and before drafting.

## Design rule

Checkpoint 0056 does not infer semantic equivalence between differently worded claims. Evidence is linked only when the normalized claim exactly matches the normalized fact statement. This intentionally prevents CIVORA from fabricating provenance. Semantic claim/evidence reconciliation is the next editorial-engine stage.

## Runtime flow

`signal → verify_story → durable Fact Kernel → blocked/review OR drafting → packaging`

## Validation coverage added

- grounded provenance with two independent sources;
- unlinked confirmed fact is routed to `needs_review`;
- semantic idempotence;
- revision history;
- backup recovery visibility;
- dangling evidence reference fails closed;
- Orchestrator persists the verified kernel before article generation.

## State

`CODE_COMPLETE_CI_PENDING`

The previous canonical head (checkpoint 0055) is CI validated. Checkpoint 0056 becomes `CLOSED_VALIDATED` only after the GitHub Actions matrix passes for the final head containing code, tests and checkpoint documentation.

## Next canonical action

Implement deterministic claim/evidence reconciliation on top of the durable kernel: support aggregation, contradiction representation, source independence, confidence calculation and explicit disputed/uncertain outcomes without changing source evidence.
