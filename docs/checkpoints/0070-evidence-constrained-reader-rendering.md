# CIVORA Checkpoint 0070 — Evidence-Constrained Reader Rendering

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the remaining raw-prose leak between verified editorial state and reader-visible output. Headline, dek, why-it-matters and downstream social/newsletter surfaces must no longer consume `Signal.title`, `Signal.summary`, or unverified `FactKernel.next_expected_event` text.

## Implementation

Added `civora/evidence_rendering.py` with `EvidenceConstrainedRenderer`.

The renderer receives only the current authorized projection produced by `AuthorizedStoryBuilder`. It composes reader-visible factual prose verbatim from authorized fact statements and deliberately performs no paraphrase, causal inference, summarization from raw signals, or unsupported synthesis.

`generate_article()` now uses this renderer for:

- `headline`;
- `dek`;
- `why_it_matters`;
- `next` (disabled by default unless a future explicitly authorized projection is enabled).

The article keeps a `rendering` audit object containing the rendering source and authorized fact/claim IDs. `generate_content_pack()` continues to derive Facebook, Instagram, short-video and newsletter surfaces only from the article headline/dek, and its audit records `rendering_source`.

Raw `Signal.title`, `Signal.summary`, raw `FactKernel.confirmed_facts`, raw uncertainties and raw `next_expected_event` therefore have no direct reader-visible path through drafting or packaging.

## Safety properties

- Rendering input is the same authorized projection already bound to current Fact Kernel, reconciliation, contradiction and editorial decision state.
- Missing or malformed authorized statements fail closed.
- The renderer does not invent causal language or editorial claims.
- Raw signal prose is not used as a fallback.
- Raw next-event prose is suppressed instead of being published without authorization.
- Downstream content-pack surfaces inherit the same evidence-constrained headline/dek.

## Validation added

`tests/test_authorized_pipeline.py` now verifies:

- raw signal title and summary do not leak into article output;
- raw Fact Kernel facts, uncertainties and next-event prose do not leak;
- headline/dek/why-it-matters are deterministic authorized-fact compositions;
- packaging reuses only evidence-constrained surfaces;
- malformed or empty authorized projections fail closed.

## Gates

- RAW_SIGNAL_HEADLINE_FALLBACK_ABSENT: PASS_IMPLEMENTATION
- RAW_SIGNAL_DEK_FALLBACK_ABSENT: PASS_IMPLEMENTATION
- RAW_SIGNAL_WHY_IT_MATTERS_FALLBACK_ABSENT: PASS_IMPLEMENTATION
- RAW_NEXT_EVENT_PUBLICATION_ABSENT: PASS_IMPLEMENTATION
- AUTHORIZED_RENDERER_INTEGRATION: PASS_IMPLEMENTATION
- CONTENT_PACK_PROPAGATION: PASS_IMPLEMENTATION
- RENDERING_AUDIT_BINDING: PASS_IMPLEMENTATION
- MALFORMED_PROJECTION_FAIL_CLOSED: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING_CURRENT_CI

## Remaining backlog

1. Operator remediation and recovery runbooks for editorial consistency, approval and authorization failures.
2. Evidence-preserving style/rewrite layer if CIVORA needs more natural headlines without weakening factual guarantees.
3. Production-readiness review covering crash recovery, durable health, editorial safety, packaging, operator workflows and release gates.

## Blockers

Current-head cross-platform CI result is required before this checkpoint can be declared `CLOSED_VALIDATED`.

## Next action

If CI passes, close 0070 and implement operator remediation/recovery runbooks plus machine-readable remediation guidance for degraded editorial states.
