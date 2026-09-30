# S-A2.5 — Cross-Lane Read Coverage + Replay Idempotency

Date: 2026-09-30

Status: IMPLEMENTED / LOCAL AGGREGATION ONLY / LIVE WRITE OFF / KILL SWITCH ENGAGED

S-A2.5 adds a deterministic projection over validated S-A2.4 read-observability snapshots. It aggregates coverage across exactly the three active lanes: FACEBOOK_PAGE, INSTAGRAM_PROFESSIONAL and THREADS. It introduces no network execution, no transport widening and no credential handling.

Exact snapshot replays for the same lane are collapsed deterministically. Input ordering does not affect the aggregate identity. A second, different valid snapshot for the same lane in one aggregation attempt is treated as an ambiguous/conflicting replay and fails closed rather than guessing which snapshot is newer.

Coverage states are explicit: NO_ACTIVE_LANE_SNAPSHOTS, PARTIAL_ACTIVE_LANE_COVERAGE, ALL_ACTIVE_LANES_PRESENT and ALL_ACTIVE_LANES_OBSERVED. Missing lanes are named explicitly and never inferred as healthy.

External metrics remain exactly UNKNOWN wherever S-A2.4 cannot provide them. The aggregate records the per-lane UNKNOWN metric count and rejects any attempt to replace UNKNOWN with zero, null, an estimate or an inferred value.

Authority remains zero: network OFF; external write OFF; publish OFF; deploy OFF; write-permission activation OFF; paid services OFF; kill switch ENGAGED. No token, App Secret, password or 2FA material is read, stored, copied or logged.

Lane canon is unchanged: LinkedIn remains HOLD until production API access; X remains excluded while the useful API is paid; Bluesky remains HOLD until a local ROI test passes.

Changelog: added M66 cross-lane read coverage compiler, deterministic replay/no-op semantics, canonical lane ordering, explicit missing-lane coverage, UNKNOWN-preserving aggregate metrics and local regression tests.

Decision: cross-lane observability is a pure local projection over validated S-A2.4 snapshots. Ambiguous same-lane state is fail-closed. No live metric acquisition or write authority is implied by aggregate completeness.

Blockers: integration remains stacked on S-A2.4. No merge is forced and no deploy is permitted from this unit.

Next granular unit: S-A2.6 — deterministic persistence/reload envelope for read-observability and cross-lane coverage snapshots, with checksum/corruption rejection, local-only and zero live authority.
