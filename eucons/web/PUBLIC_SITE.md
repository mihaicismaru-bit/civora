# EUCONS Core Public Site — E08

## Purpose

E08 turns the verified EUCONS commercial canon into a deterministic, provider-independent public-site build. The build is still a development preview: every generated page is `noindex,nofollow` until later production acceptance gates explicitly change the publication state.

## Truth boundary

The public renderer may use only:

- E01 audience/CTA canon for navigation and user journeys;
- E02 services that have a valid, publishable E03 `SERVICE_OFFERING` claim;
- E04 people records in `PUBLISHABLE` state;
- E05 case records in `PUBLISHABLE` state;
- E06 route and canonical contracts;
- E07 design-system assets.

It must not invent company history, legal identity, people, testimonials, clients, project results, numeric performance, prices, funding status/deadlines/budgets or contact details.

## Homepage contract

The homepage must make the commercial proposition understandable to a first-time visitor, expose verified service offerings, show clear audience paths and provide internal qualification/offer CTAs. People, cases and funding-opportunity sections are conditional and are omitted when no publishable records exist.

## Empty-state contract

Dedicated team, project and funding indexes may explain the verification policy and current absence of public records, but the homepage must not use fake placeholders or invented proof to fill empty sections.

## Lead journeys

E08 may render the structure and copy for evaluation/offer journeys, but it must not pretend the E11 lead transport is active. Controls remain explicit development dry-runs until E11 closes.

## Legal surfaces

E06 legal routes are materialized for route completeness, but remain development-only placeholders until E21 privacy/security/legal acceptance. They are never represented as production legal advice or a finalized privacy policy during E08.

## Acceptance

E08 closes only when a clean temporary build:

1. materializes every E06 core and service route;
2. contains no external CSS/font runtime dependency;
3. links only to known internal paths in primary commercial navigation;
4. omits HOLD/unverified people, cases and commercial claims;
5. has a clear homepage value proposition, service paths, audience paths and CTAs;
6. keeps all pages `noindex,nofollow` during development;
7. passes deterministic visitor/trust/commercial regressions.
