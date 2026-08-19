# EUCONS Evidence Policy v1

## Purpose

The evidence layer is the trust boundary between internal commercial intent and anything EUCONS may publish as a factual claim about Euroconsult, its people, clients, projects, results, funding opportunities or commercial terms.

A claim is public only when the canonical evidence registry marks it `PUBLISHABLE` and the E03 validator can prove that the required evidence and consent/confidentiality conditions are satisfied. Missing, stale, contradictory or insufficient evidence produces `HOLD`.

## Evidence classes

- `OWNER_AUTHORIZED_CANON` — a merged EUCONS canonical contract approved by the product owner. It may prove what EUCONS is configured to offer, how a service is described, which CTA exists, or an internal policy. It does **not** prove historical performance, clients, project results, expert credentials, funding facts or quantified achievements.
- `PRIMARY_OFFICIAL` — a primary public authority, company registry, funding authority or other authoritative first-party source appropriate to the fact asserted.
- `CLIENT_CONTROLLED_RECORD` — a client-controlled contract, acceptance, deliverable, correspondence or other record. Confidential by default and publishable only after classification/permission rules permit it.
- `EUROCONS_CONTROLLED_RECORD` — Euroconsult-controlled business records that can corroborate an operational fact. They cannot by themselves convert a client relationship, testimonial or confidential result into a public claim.
- `PUBLIC_PRIMARY_ORGANIZATION_SOURCE` — a public first-party page or document of the organization/person whose identity, role or statement is being asserted.
- `VERIFIED_PARTENER_PROJECTION` — the read-only verified funding projection exposed by PARTENER.EU under the later E09 bridge contract. It may support funding facts only while freshness/provenance gates remain valid.
- `APPROVED_PRICING_RULE` — a later E13 canonical pricing rule explicitly authorized for the relevant commercial term.
- `DERIVED_ANALYSIS` — an interpretation derived from supported base facts. It can never serve as the sole evidence for the underlying material fact.

## Claim classes and minimum support

`SERVICE_OFFERING`, `SERVICE_PROCESS` and `CTA_AVAILABILITY` may be supported by `OWNER_AUTHORIZED_CANON`.

`COMPANY_IDENTITY` requires `PRIMARY_OFFICIAL` or another specifically approved legal-identity source.

`COMPANY_EXPERIENCE`, `CLIENT_RELATIONSHIP`, `PROJECT_RESULT` and quantified achievement claims require evidence that is external to the marketing copy and appropriate to the fact. Client names/results remain confidential unless publication permission is explicitly recorded.

`TESTIMONIAL` requires authentic source material and explicit publication consent.

`EXPERT_IDENTITY`, `EXPERT_ROLE` and `EXPERT_CREDENTIAL` are completed in E04 and require person/organization evidence appropriate to the assertion.

`FUNDING_FACT` requires `VERIFIED_PARTENER_PROJECTION` or an equivalent primary official source governed by the E09 opportunity bridge. A press statement, social post or calendar signal is not sufficient to change a material funding fact.

`PRICE_TERM` requires `APPROVED_PRICING_RULE`; absent such a rule, numeric prices/discounts remain `HOLD`.

## Publication states

- `PUBLISHABLE` — all minimum evidence, freshness, confidentiality and consent conditions pass.
- `HOLD` — the claim exists as a candidate but must not be projected publicly.
- `RETIRED` — historical claim no longer eligible for new publication; retained for audit history.

Public renderers, social adapters, offer generation and editorial products must consume only `PUBLISHABLE` claims. `HOLD` and `RETIRED` claims are never fallback copy.

## Contradictions and staleness

If two material evidence items conflict, the affected claim becomes `HOLD` until a deterministic resolution is recorded. If a claim type has a freshness requirement and supporting evidence is stale, the claim becomes `HOLD`; last-known-good evidence may remain stored but is not silently treated as current.

## Confidentiality and consent

Client-controlled evidence is private by default. Client identity, project results and testimonials require a publication classification compatible with public use. Testimonials additionally require explicit consent. No unpublished client record is copied into public output merely because it exists in the repository or connected storage.

## Auditability

Each claim has a stable claim ID, claim class, publication state, evidence references and a machine-readable reason when held. Evidence items have stable IDs, class, source locator and allowed claim classes. The Git commit plus validation receipt identifies the exact evidence/claim registry version that passed the gate.
