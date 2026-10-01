# S-A2.7 — Persisted Snapshot Generation Ordering / Stale-State Rejection

Date: 2026-10-01

Status: IMPLEMENTED / LOCAL VALIDATION ONLY / LIVE WRITE OFF / KILL SWITCH ENGAGED

S-A2.7 adds deterministic monotonic generation metadata around the S-A2.6 persisted snapshot envelope without adding any new I/O authority. Generation 1 has no predecessor. Every later generation must advance by exactly one and bind the previous generation number plus the previous record SHA-256.

The validator rejects replayed or older persisted state, generation gaps, wrong predecessor hashes, malformed generation records, snapshot checksum drift, and any attempt to widen network, external-write, publish or deploy authority. Consumers may set a minimum accepted generation; an older record then fails closed.

The implementation deliberately reuses the S-A2.6 serializer/decoder for the embedded snapshot. S-A2.7 therefore validates ordering and freshness as a pure local contract; it does not add network calls, platform permissions, deploy behavior or a second storage mechanism.

Authority remains zero: network OFF; external write OFF; publish OFF; deploy OFF; write-permission activation OFF; paid services OFF; kill switch ENGAGED. No token, App Secret, password or 2FA material is read, stored, copied or logged.

Lane canon is unchanged: Facebook Page, Instagram Professional and Threads remain active; LinkedIn remains HOLD until production API access; X remains excluded while the useful API is paid; Bluesky remains HOLD until a local ROI test passes.

Changelog: added M68 generation envelopes, exact +1 ordering, predecessor SHA-256 linkage, stale-record rejection, minimum-generation guard and deterministic regression tests.

Decision: a persisted read-only snapshot is acceptable only when its generation is fresh and its predecessor link is exact. Generation metadata cannot confer live authority.

Blockers: dependency S-A2.6 exact-head CI must be green before integration. S-A2.7 exact-head CI must also pass; no merge is forced.

Next granular unit: S-A2.8 — deterministic recovery/read-selection policy for interrupted local generations and competing valid candidates, fail-closed and zero live authority.
