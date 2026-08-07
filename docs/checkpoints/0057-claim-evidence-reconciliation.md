# CIVORA Checkpoint 0057 — Claim / Evidence Reconciliation

## Objective

Build the first deterministic editorial reasoning layer on top of the durable Fact Kernel.

## Implemented

- `ClaimEvidenceReconciler` with explicit, versionable policy thresholds.
- Evidence aggregation by independent source, not raw evidence-count inflation.
- Per-source strongest-confidence selection.
- Deterministic combined support: `1 - Π(1-confidence)`.
- Fact states: `corroborated`, `single_source`, `weakly_supported`, `unsupported`.
- Uncertain-claim states: `candidate_corroborated`, `uncertain`.
- Explicit reconciliation gates: `corroborated`, `review_support_strength`, `needs_review`.
- No fuzzy matching and no mutation of original source evidence.
- `FactReconciliationStore` backed by `AtomicJsonStore`.
- Deterministic report identity from Fact Kernel semantic hash + reconciliation policy.
- Idempotent persistence for the same kernel revision and policy.
- New report generation for semantic Fact Kernel revisions.
- Automatic Orchestrator flow: verified Fact Kernel → durable reconciliation → drafting/review.

## Editorial safety rule

Reconciliation evaluates only evidence references already linked by the Fact Kernel. Different wording is not assumed to be equivalent. Unsupported facts remain visible and route to review; uncertain claims that receive strong corroboration are marked only as `candidate_corroborated`, not silently promoted to confirmed facts.

## Runtime flow

`verify_story → durable Fact Kernel → deterministic evidence reconciliation → editorial gate → draft/review`

## Validation coverage

- two independent sources corroborate a fact;
- multiple evidence items from one source do not create false corroboration;
- missing evidence remains unsupported;
- uncertain claims can become candidate-corroborated without input mutation;
- reconciliation reports are durable and idempotent;
- new Fact Kernel revisions produce new reconciliation reports;
- unlinked facts route to `needs_review`.

## State

`CODE_COMPLETE_CI_PENDING`

## Next canonical action

Introduce explicit claim polarity / contradiction assertions and durable conflict clusters, then compute `disputed` outcomes without using lexical negation heuristics.
