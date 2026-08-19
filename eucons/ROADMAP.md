# EUCONS Autonomous Development Roadmap

Canonical status is machine-readable in `ops/checkpoint.json`. This roadmap defines ordered acceptance phases; phases may be implemented in grouped PRs, but no phase closes without its exit gate.

| Phase | Scope | Exit gate |
|---|---|---|
| E00 | Bootstrap, canon, architecture, autonomy, state, quality gate | Required contracts exist; bootstrap validator green |
| E01 | Commercial canon and audience/problem/service mapping | Every priority audience maps to problems, services and CTAs |
| E02 | Canonical service registry | Every public service has deliverables, process, boundaries and CTA |
| E03 | Euroconsult evidence base | Public claims have provenance; unsupported claims HOLD |
| E04 | People registry | Every published person has verified identity/role/competence evidence |
| E05 | Case-study registry | No case result without evidence/confidentiality classification |
| E06 | Information architecture | Route map, canonicals, navigation, internal-link contract complete |
| E07 | Design system | Responsive/accessibility component contract passes visual QA |
| E08 | Homepage and core public site | Visitor, trust and commercial QA green |
| E09 | PARTENER -> EUCONS opportunity bridge | Read-only verified projection with provenance and stale-data handling |
| E10 | Opportunity matching | Deterministic match score, exclusions, confidence and explanation |
| E11 | Lead engine | Validation, consent, dedupe, scoring and synthetic end-to-end fixtures |
| E12 | CRM Lite | Lead/opportunity/offer lifecycle and audit history deterministic |
| E13 | Offer engine | Scope/deliverables/versioning complete; undefined price fails closed |
| E14 | Knowledge engine | Evidence-backed guides/analysis/opportunity/case/FAQ projections |
| E15 | Autonomous editorial loop | Discovery -> fact kernel -> QA -> publish/reconcile receipts |
| E16 | SEO engine | Metadata, schema, sitemap, canonicals, clusters and orphan checks |
| E17 | LinkedIn adapter | Doctrine, outbox, dry-run, retry and receipts green |
| E18 | Facebook adapter | Platform-specific outbox, dry-run, retry and receipts green |
| E19 | Commercial email adapter | Consent-aware transactional/follow-up dry-runs and receipts |
| E20 | Analytics contract | Funnel events, attribution and provider-neutral adapter contract |
| E21 | Privacy/security | GDPR map, minimization, retention, input/output and secret guards |
| E22 | GitHub automation | Build, quality, scheduler, reconciliation, health workflows green |
| E23 | Persistence | Atomic state transitions, receipts and replay-safe state writes |
| E24 | Recovery | Interrupted/stale/duplicate/failed execution recovery deterministic |
| E25 | Preview production | GitHub preview serves complete build; journeys pass smoke tests |
| E26 | Adversarial QA | Contradictory, missing, stale, spam and outage fixtures fail safely |
| E27 | Full acceptance | Opportunity -> lead -> match -> offer -> outboxes -> receipts E2E green |
| E28 | CLOSED-DEV | Code/content/workflows/tests complete; no development blockers |
| E29 | External handoff | Only unavoidable domain/social/mail authorization steps remain |
| E30 | PRODUCTION CLOSED | Production smoke, health, social/mail and recovery green |

## Autonomous execution rule

Always select the smallest unclosed phase/sub-unit that materially advances the terminal acceptance test. Prefer reuse over duplication, preserve sibling-product contracts, and persist a checkpoint after every successful development unit.

## Priority order inside a phase

1. contract/schema;
2. deterministic implementation;
3. fixtures/tests;
4. quality gate;
5. state/receipt;
6. preview/public projection when applicable.

## Definition of `PRODUCTION_READY`

All E00-E28 gates are green and E29 contains only credential/ownership actions. No missing design, copy, code, schema, test, recovery behavior or adapter dry-run may be deferred to E29.
