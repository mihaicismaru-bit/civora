# CIVORA Checkpoint 0068 — Authorized Story Engine Gate

Status: CODE_COMPLETE_CI_PENDING

## Objective

Ensure article drafting consumes only facts that are explicitly allowed by the durable editorial evidence chain. Passing the editorial gate is no longer sufficient by itself: the drafting payload must be projected from the exact current Fact Kernel, reconciliation report, contradiction report and editorial authorization record.

## Implementation

### Authorized fact projection

Added `civora/authorized_story.py` with `AuthorizedStoryBuilder`.

The builder validates immutable alignment across:

- story ID;
- Fact Kernel ID;
- Fact Kernel revision;
- Fact Kernel semantic hash;
- reconciliation report ID;
- contradiction report ID;
- editorial decision ID;
- approved editorial case binding when the gate decision is `review`.

A confirmed fact is eligible for drafting only when it is:

- grounded in durable provenance with evidence references;
- `corroborated` by the reconciliation engine;
- `uncontested` by contradiction analysis.

Human approval authorizes the story decision but deliberately does not convert weak, unsupported, disputed or contradicted facts into confirmed facts. Unsafe facts are excluded from the drafting projection. If no safe confirmed fact remains, authorization fails closed.

Candidate uncertain claims may be surfaced only when they are explicitly `candidate_corroborated`, have evidence and are `uncontested`; raw uncertain claims are not passed through.

### Pipeline enforcement

`generate_article()` now requires an explicit authorization projection. There is no fallback to `story.fact_kernel.confirmed_facts` or raw uncertain claims.

The generated article records an authorization audit containing:

- Fact Kernel identity and revision;
- semantic hash;
- editorial decision ID;
- authorization mode;
- exact authorized fact IDs.

Content-pack audit now carries the editorial decision ID and Fact Kernel semantic hash.

### Orchestrator integration

Both production drafting paths use the same `AuthorizedStoryBuilder`:

1. automatic drafting after an `auto_draft` editorial decision;
2. restart-safe re-entry after an exact approved editorial review case.

Approval re-entry reloads the current durable reconciliation and contradiction reports before constructing the authorization projection. Stale or missing reports fail closed.

## Validation added

`tests/test_authorized_story.py` covers:

- projection of only grounded/corroborated/uncontested facts;
- exact human approval binding;
- human approval cannot promote weak/disputed facts;
- stale reports and stale approvals fail closed.

`tests/test_authorized_pipeline.py` covers:

- drafting cannot be invoked without an authorization projection;
- raw Fact Kernel confirmed/uncertain statements are not consumed;
- story/projection mismatch fails closed;
- article authorization audit is emitted.

Existing end-to-end Orchestrator, approval, restart and packaging tests remain active as regression gates.

## Gates

- RAW_FACT_KERNEL_DRAFTING_FALLBACK: ABSENT
- DURABLE_REPORT_ALIGNMENT: PASS_IMPLEMENTATION
- GROUNDED_PROVENANCE_REQUIRED: PASS_IMPLEMENTATION
- CORROBORATED_FACT_REQUIRED: PASS_IMPLEMENTATION
- UNCONTESTED_FACT_REQUIRED: PASS_IMPLEMENTATION
- HUMAN_APPROVAL_DOES_NOT_PROMOTE_UNSAFE_FACTS: PASS_IMPLEMENTATION
- STALE_APPROVAL_FAIL_CLOSED: PASS_IMPLEMENTATION
- STALE_REPORT_FAIL_CLOSED: PASS_IMPLEMENTATION
- AUTO_DRAFT_AUTHORIZATION_INTEGRATION: PASS_IMPLEMENTATION
- APPROVED_REENTRY_AUTHORIZATION_INTEGRATION: PASS_IMPLEMENTATION
- ARTICLE_AUTHORIZATION_AUDIT: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING_CURRENT_CI

## Remaining backlog

1. Operator remediation and recovery runbooks for editorial consistency failures.
2. CLI inspection of authorized/excluded facts for a story before resume or publication.
3. Story rendering improvements that also constrain headline/dek/why-it-matters language to authorized evidence rather than raw signal prose.
4. Production-readiness review and packaging once authorization controls are validated.

## Blockers

Current-head cross-platform CI result is required before `CLOSED_VALIDATED` can be declared.

## Next action

Validate checkpoint 0068 in CI. If green, expose the authorized fact projection through operator tooling and add remediation/runbook guidance; if CI finds an obsolete raw-drafting contract, update that contract rather than restoring the unsafe fallback.
