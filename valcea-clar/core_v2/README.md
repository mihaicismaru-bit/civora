# CIVORA Local News Core v2 — shadow rebuild

Status: **LEGACY / NOT_PRODUCTION_READY** for the current VÂLCEA CLAR execution architecture. Core v2 is **shadow-only** and has `publication_authority=NONE` until an explicit owner-approved cutover.

## Golden path

`SOURCE -> SIGNAL -> FACT_KERNEL -> EDITORIAL_DECISION -> ARTICLE -> PHOTO -> SITE -> FB/IG -> RECEIPT -> AUDIT`

The unit of truth is a single `StoryTransaction`. A workflow exit code, preview, outbox entry or internal state file is never enough to claim delivery.

## Canonical contracts

- `StoryState`: `DISCOVERED -> VERIFIED -> WRITTEN -> VISUAL_READY -> SITE_PUBLISHED -> FB_DELIVERED / IG_DELIVERED -> AUDITED`, plus `NO_STORY`, `BLOCKED`, `FAILED`.
- `FactKernel`: requires `what`, `who`, `where`, `when`, `why_it_matters`, `source`, source URL and at least one supported claim.
- `Visual`: social delivery accepts only a real photograph with explicit rights basis, sufficient semantic relevance and editor approval. Synthetic-as-photo and text-card substitution are rejected.
- `PublicationReceipt`: site delivery requires canonical public URL + external readback. Facebook/Instagram delivery requires remote ID + receipt ID + readback.
- `AuditResult`: acceptance requires external truth evidence and zero duplicates, fabricated claims, manual intervention and unresolved material signals.

## Safety / isolation

Core v2 currently performs no network writes. `orchestrator.py` is an evidence-replay/shadow evaluator only. It never publishes to site or social. Site publication and social distribution remain separate state transitions; a social failure never rolls back a truthful site publication.

## Legacy findings that motivated rebuild

Fresh main inspection on 2026-09-18 confirms the live newsroom still has its own schedule/push/workflow-run triggers and writes generated state directly to `main`. The social engine independently schedules distribution, enables Facebook text fallback and an Instagram fact-card fallback, and persists platform state back to `main`. This creates multiple independent owners of publication state and permits internal success to diverge from the external product.

Core v2 therefore keeps useful parsers, fact evidence, story archive, rights-cleared media metadata and Meta access, while replacing orchestration and delivery truth semantics.

## Pilot sources

The first bounded pilot is limited to eight source families: IPJ Vâlcea, ISU Vâlcea, APAVIL, Primăria Râmnicu Vâlcea, Consiliul Județean Vâlcea, ETA, ISJ Vâlcea and one cultural source. A signal with no material fact ends `NO_STORY`.

## Acceptance sequence

1. Shadow contract and replay tests.
2. Bind the selected source adapters into one sequential orchestrator.
3. Add independent, non-destructive external readback adapters.
4. Prepare 10-story acceptance in shadow.
5. Only after explicit owner approval: cut over, require 10 consecutive truthful end-to-end stories, then start a new 48h soak.
6. Retire legacy workflows by category only after equivalent Core v2 behavior is proven.

The old soak clock and old production-ready claims are not reused.
