# S-A2.4 — Read-Observability Snapshot Compiler

Date: 2026-09-30

Status: IMPLEMENTED / LOCAL SNAPSHOT ONLY / LIVE WRITE OFF / KILL SWITCH ENGAGED

S-A2.4 compiles deterministic observability snapshots from the validated S-A2.3 cursor + append-only event log. It introduces no transport execution and does not widen platform authority.

Active lanes remain exactly FACEBOOK_PAGE, INSTAGRAM_PROFESSIONAL and THREADS. LinkedIn remains HOLD until production API access, X remains excluded while useful API access is paid, and Bluesky remains HOLD until a local ROI test passes.

The snapshot exposes accepted event count, duplicate replay count, persisted event count, latest accepted sequence/event identity, observed operations, latest normalized identity fields and the latest UNKNOWN field set. Empty streams report NO_ACCEPTED_EVENTS and do not invent a latest event.

External social metrics unavailable in S-A2.3 are represented exactly as UNKNOWN. Null, zero, estimates and inferred values are not substituted.

Authority remains zero: network OFF; external write OFF; publish OFF; deploy OFF; write-permission activation OFF; paid services OFF; kill switch ENGAGED. Credential material is outside this unit by contract.

Changelog: added M65 read-observability compiler, UNKNOWN metric contract, exact active-lane identity checks and local regression tests. Global CP58 remains unchanged.

Decision: read observability is a pure projection over S-A2.3. Future live metric acquisition requires a separate explicit read-only capability/permission gate.

Blockers: integration remains stacked. S-A2.1 and S-A2.2 PRs are green but open; S-A2.3 has no PR. No merge is forced.

Next granular unit: S-A2.5 — observability snapshot replay/idempotency + cross-lane coverage aggregation, local-only, UNKNOWN-preserving, zero live authority.
