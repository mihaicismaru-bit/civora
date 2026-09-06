# CP39 — M13 Image Rights / Asset Provenance Minimal Executable Slice v1

CP39 reimplements the historical CP13 rights/provenance contract as canonical GitHub executable source without importing unavailable historical source bytes.

## Purpose

M13 is a local, deterministic, fail-closed rights layer between M05 native text adaptations and M06 visual production. It does not decide legal ownership from public visibility, download assets, connect accounts, publish, queue, deploy, or infer permissions from URLs.

## Canonical rules

- Exact original identity is SHA-256 over local bytes.
- Provenance is separately hashed and binds acquisition route, source revision, creator, source URL, media class, clearance state, capture metadata and exact original hash.
- Source revisions, originals, rights revisions, evidence snapshots and derivatives are append-only SQLite records. UPDATE and DELETE are blocked by database triggers.
- Discovery and acquisition are separate. `SOCIAL_DOWNLOAD_UNCLEARED`, `SEARCH_ENGINE_DOWNLOAD`, `PRESS_COPY_UNCLEARED` and `MAP_SCREENSHOT_AS_PHOTO` are rejected acquisition routes.
- A public URL or publicly visible image is never treated as reuse permission by itself.
- Automatic eligibility is limited to evidence-backed `OWNED`, `LICENSED` and `PUBLIC_DOMAIN` records.
- `FAIR_USE_REVIEW` is always human-review hold; `UNKNOWN` holds; `BLOCKED` stops.
- Every automatically eligible rights revision has explicit platform, purpose, territory, commercial-use, modification and evidence scope.
- Attribution and ShareAlike requirements are fail-closed.
- Subject/personality/privacy clearance remains separate from copyright status; PENDING/REQUIRED holds and BLOCKED stops.
- `PROFILE_PHOTO` cannot be repurposed as `SOCIAL_EDITORIAL` post media.
- Rights supersession/revocation makes older rights records stale. Derivatives resolve to the root original, so a later root revocation propagates to derivative eligibility.

## M05 → M13 → M06 binding

`bind_rights_bound_visual_input()` accepts only an integrity-valid canonical M05 `NativeAdaptationBundle`. If M05 is not `rights_input_ready`, M13 returns `HOLD_INPUT_NOT_READY` without performing rights eligibility.

For an M05-ready bundle, one candidate asset and one exact current rights record are evaluated independently for Facebook Page, Instagram Professional and Threads using the same social-editorial usage request. The minimal CP39 common-visual contract becomes `READY_RIGHTS_BOUND_VISUAL_INPUT` only when all three active lanes are `ELIGIBLE_RENDER_QA`.

This is deliberately conservative. A later M06 implementation may support separate per-platform visual assets, but CP39 does not weaken rights scope to enable that future behavior.

## Authority boundary

M13 has rights/provenance authority only. Every `RightsEligibility` has `publish_eligible=false`; `RightsBoundVisualInput` has no fact, visual, queue, publisher, network, account-connection or deploy authority.

## Active/deferred platforms

Active: Facebook Page, Instagram Professional, Threads.

Deferred: LinkedIn until production API access; X excluded while its required API lane is paid; Bluesky remains `HOLD_ROI`.

## Validation targets

The CP39 test suite covers exact SHA/provenance binding, unauthorized acquisition rejection, public-visibility non-permission, automatic/hold/blocked rights states, subject-clearance separation, profile-photo restriction, attribution and ShareAlike gates, expiry/review holds, rights supersession and derivative revocation propagation, append-only triggers, M05 integrity binding, deterministic replay, authority boundaries and policy consistency.

No real image, external account, live media ingest, public post, queue mutation or deployment is performed by CP39.
