# CIVORA Checkpoint 0069 — Authorized Fact Operator Inspection

Status: CODE_COMPLETE_CI_PENDING

## Objective

Expose the exact factual projection that production drafting is allowed to consume, so an operator can inspect authorized facts, excluded facts, exclusion reasons, authorization mode and immutable editorial/kernel bindings before resume or publication.

## Implementation

The operational CLI now includes:

```bash
civora --state-dir <path> authorized-story <story-id>
```

The command loads the current durable Fact Kernel, reconciliation report, contradiction report, editorial gate decision and approval case, then calls the same `AuthorizedStoryBuilder` used by production drafting. It does not duplicate or weaken authorization policy.

The output is machine-readable JSON and includes:

- authorization mode (`auto_draft` or `human_approved`);
- editorial decision ID;
- Fact Kernel semantic hash;
- authorized fact count and exact authorized facts;
- excluded fact count and exact exclusion reasons;
- authorized uncertain claims;
- the effective authorization policy.

The command is read-only. It cannot approve a case, edit facts, mutate durable reports or bypass editorial alignment. Missing durable components, stale reports, invalid approval binding, contradictions or a projection with no authorized confirmed facts fail closed through `AuthorizedStoryError`.

## Validation added

`tests/test_authorized_cli.py` verifies that the command surfaces authorized and excluded facts with exact reasons and that an incomplete durable editorial chain returns an operational error rather than manufacturing a partial projection.

## Gates

- PRODUCTION_AUTHORIZATION_BUILDER_REUSED: PASS_IMPLEMENTATION
- AUTHORIZED_FACT_VISIBILITY: PASS_IMPLEMENTATION
- EXCLUDED_FACT_VISIBILITY: PASS_IMPLEMENTATION
- EXCLUSION_REASON_VISIBILITY: PASS_IMPLEMENTATION
- AUTHORIZATION_BINDING_VISIBILITY: PASS_IMPLEMENTATION
- MACHINE_READABLE_JSON: PASS_IMPLEMENTATION
- READ_ONLY_OPERATOR_SURFACE: PASS_IMPLEMENTATION
- INCOMPLETE_CHAIN_FAIL_CLOSED: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING_CURRENT_CI

## Remaining backlog

1. Operator remediation and recovery runbooks for editorial consistency failures and authorization failures.
2. Constrain headline, dek and why-it-matters rendering to authorized evidence rather than raw signal prose.
3. Production-readiness review covering crash recovery, health, editorial safety, packaging and operational runbooks.

## Blockers

Current-head cross-platform CI must pass before this checkpoint can be declared `CLOSED_VALIDATED`.

## Next action

If CI is green, close 0069 and implement evidence-constrained rendering so every reader-visible factual surface — not only article body facts — is derived from the authorized projection.
