# CIVORA Checkpoint 0068 — Authorized Story Engine Gate

Status: CLOSED_VALIDATED

## Objective

Ensure article drafting consumes only facts that are explicitly allowed by the durable editorial evidence chain. Passing the editorial gate is no longer sufficient by itself: the drafting payload must be projected from the exact current Fact Kernel, reconciliation report, contradiction report and editorial authorization record.

## Implementation

### Authorized fact projection

Added `civora/authorized_story.py` with `AuthorizedStoryBuilder`.

The builder validates immutable alignment across story ID, Fact Kernel ID/revision/semantic hash, reconciliation report, contradiction report, editorial decision and — for reviewed stories — the exact approved editorial case.

Automatic drafting remains deliberately strict: a confirmed fact must be grounded in durable provenance, `corroborated` by reconciliation and `uncontested` by contradiction analysis.

Human-approved re-entry has a separate controlled policy. A human approval may authorize a grounded and uncontested fact whose support is below the automatic threshold (`single_source` or `weakly_supported`), because that is the purpose of the editorial review path. It may not authorize `unsupported`/unlinked facts and may not override `disputed`, `contradicted` or `unresolved` contradiction states. Human approval therefore lowers the automation threshold only where an audited operator decision exists; it does not bypass provenance or conflict controls.

Candidate uncertain claims may be surfaced only when explicitly `candidate_corroborated`, evidenced and `uncontested`; raw uncertain claims are not passed through.

### Pipeline enforcement

`generate_article()` requires an explicit authorization projection. There is no fallback to `story.fact_kernel.confirmed_facts` or raw uncertain claims.

The generated article records an authorization audit with Fact Kernel identity/revision/hash, editorial decision ID, authorization mode and exact authorized fact IDs. Content-pack audit also carries the editorial decision ID and semantic hash.

### Orchestrator integration

Both production drafting paths use the same `AuthorizedStoryBuilder`: automatic drafting after `auto_draft`, and restart-safe re-entry after an exact approved review case. Approval re-entry reloads the current durable reconciliation and contradiction reports before constructing the projection. Stale or missing records fail closed.

## Validation

`tests/test_authorized_story.py` covers safe projection, exact approval binding, non-promotion of a disputed fact and stale-record failure. `tests/test_authorized_pipeline.py` proves raw Fact Kernel statements cannot be drafted without authorization. Existing approval/restart tests remain active; the approved-reentry fixture is aligned to a grounded, uncontested review fact rather than treating human approval as an override of an explicit contradiction.

GitHub Actions run `31226519940` passed the final checkpoint head `cc4d5f46fcc8f40f893f63d656aaefba56dbd061` across Linux Python 3.11, 3.12 and 3.13 plus Windows native.

## Gates

- RAW_FACT_KERNEL_DRAFTING_FALLBACK: ABSENT_VALIDATED
- DURABLE_REPORT_ALIGNMENT: PASS_VALIDATED
- GROUNDED_PROVENANCE_REQUIRED: PASS_VALIDATED
- AUTO_DRAFT_REQUIRES_CORROBORATION: PASS_VALIDATED
- HUMAN_REVIEW_MAY_AUTHORIZE_SUB_AUTO_SUPPORT: PASS_VALIDATED
- UNSUPPORTED_FACT_HUMAN_OVERRIDE: ABSENT_VALIDATED
- CONTRADICTION_HUMAN_OVERRIDE: ABSENT_VALIDATED
- UNCONTESTED_FACT_REQUIRED: PASS_VALIDATED
- STALE_APPROVAL_FAIL_CLOSED: PASS_VALIDATED
- STALE_REPORT_FAIL_CLOSED: PASS_VALIDATED
- AUTO_DRAFT_AUTHORIZATION_INTEGRATION: PASS_VALIDATED
- APPROVED_REENTRY_AUTHORIZATION_INTEGRATION: PASS_VALIDATED
- ARTICLE_AUTHORIZATION_AUDIT: PASS_VALIDATED
- CROSS_PLATFORM_CI: PASS

## Remaining backlog

1. Operator remediation and recovery runbooks for editorial consistency failures.
2. CLI inspection of authorized/excluded facts for a story before resume or publication.
3. Story rendering improvements that constrain headline/dek/why-it-matters language to authorized evidence rather than raw signal prose.
4. Production-readiness review and packaging once authorization controls are validated.

## Blockers

None for checkpoint 0068.

## Next action

Expose the authorized fact projection through operator tooling, preserving the same fail-closed authorization rules used by production drafting.
