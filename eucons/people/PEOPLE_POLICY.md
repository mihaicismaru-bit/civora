# EUCONS People Publication Policy v1

## Purpose

EUCONS may present the people behind Euroconsult services only when the public profile is derived from verified identity, current role and competence evidence. The people registry is not a marketing biography scratchpad.

## Publication rule

A person may be `PUBLISHABLE` only when all of the following are true:

1. the person has one `PUBLISHABLE` E03 claim of class `EXPERT_IDENTITY`;
2. at least one current `PUBLISHABLE` claim of class `EXPERT_ROLE` exists;
3. at least one `PUBLISHABLE` competence/credential claim of class `EXPERT_CREDENTIAL` exists;
4. every public service association points to a canonical E02 service;
5. every public biography statement is traceable to publishable claim IDs;
6. any public photo is explicitly verified and tied to active evidence;
7. no conflicting current-role evidence is unresolved.

Missing evidence produces `HOLD`. EUCONS must not create a plausible-sounding role, biography, seniority, credential, project count or portrait to fill a visual gap.

## Photos

A profile photo is optional. `VERIFIED` photos require a source/evidence reference appropriate for public use. When no verified photo exists, the public UI may use a neutral initials/avatar treatment derived from an already verified display name; it must not invent or synthesize a portrait of a real person.

## Role freshness

Roles are time-sensitive. A role claim must be current according to its evidence contract. Historical roles may remain in audit history but cannot silently become the current displayed role.

## Competence and service associations

A competence claim supports only the competence actually evidenced. Service associations are editorial routing metadata; they do not expand the person's credentials. A profile cannot be connected to a service merely to improve conversion if no verified role/competence basis exists.

## Development fallback

Until verified Euroconsult-specific people evidence is ingested, the canonical public people projection is empty and the site must omit person claims rather than publish placeholders. This development fallback does not satisfy the later E08 content/commercial presentation gate by itself; E08 may only expose people that pass this E04 contract.
