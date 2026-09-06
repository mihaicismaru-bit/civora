# CP39 — M13 Image Rights / Asset Provenance Minimal Executable Slice + Rights-Bound Visual Input v1

## Scope

CP39 reimplements M13 as canonical executable source before M06 visual materialization. It is a clean-room implementation from the validated PUBLIC PRESENCE OS rights/provenance canon; the historical CP13 SQLite source bytes are not available and are not represented as imported code.

CP39 is deliberately a deterministic contract layer. It does not download media, crawl image providers, connect social accounts, render visuals, approve a post, mutate a queue, call a publisher, publish or deploy. The historical append-only SQLite registry and event-log persistence remain a separate executable unit rather than being falsely claimed by this slice.

## Upstream input

M13 accepts only an exact CP38 `NativeAdaptationBundle` whose three active text lanes are ready. Before using it, M13 recomputes every adaptation identity/hash and the full M05 bundle identity/hash and rejects tampering or downstream authority.

The active platform set remains exactly:

- Facebook Page;
- Instagram Professional;
- Threads.

LinkedIn remains gated on production API access, X remains excluded while its API is paid, and Bluesky remains `HOLD_ROI`.

## Asset identity and provenance

An image original is bound to exact SHA-256 bytes plus deterministic provenance. The provenance hash includes media type/size/class, creator identity, acquisition route and source, acquisition time, optional discovery lead, optional capture time/location, subject-clearance state and optional metadata SHA-256.

Discovery and acquisition are separate. CP39 permits only explicit acquisition routes:

- `OWNED_CAPTURE`;
- `LICENSED_DIRECT_DOWNLOAD`;
- `PUBLIC_DOMAIN_DIRECT_DOWNLOAD`.

`SOCIAL_DOWNLOAD_UNCLEARED`, `SEARCH_ENGINE_DOWNLOAD`, `PRESS_COPY_UNCLEARED` and `MAP_SCREENSHOT_AS_PHOTO` are not acquisition routes. Openverse remains discovery-only; Wikimedia Commons and Europeana require per-item rights review; social and press media are lead-only/prohibited by default without an independent reuse grant.

## Snapshot evidence

A rights URL is not evidence by itself. Every rights record is bound to one or more materialized evidence snapshots identified by exact SHA-256 bytes, positive byte size, canonical URI, capture time and deterministic evidence hash. The evidence-set hash is order-independent and fails closed on conflicting evidence IDs.

## Rights revisions

Rights records are immutable values with deterministic IDs/hashes and contiguous revision/supersession semantics. A new revision supersedes the previous record; new use referencing an older record becomes `HOLD_STALE_RIGHTS`. A current `BLOCKED`/`REVOCATION` record blocks use bound to an earlier permission.

Automatic eligibility is restricted to:

- `OWNED` with ownership basis and owned-capture provenance;
- `LICENSED` with explicit license identity/legal URL, platform/purpose/territory, commercial-use and modification rules, attribution, validity/review and ShareAlike output-license terms when applicable;
- `PUBLIC_DOMAIN` with snapshot evidence and either `PUBLIC_DOMAIN_DETERMINATION` or `CC0_DEDICATION` basis.

`FAIR_USE_REVIEW` is always human-review HOLD. `UNKNOWN` is HOLD. `BLOCKED` is a hard stop.

Copyright permission does not imply personality/privacy clearance. `PENDING` or `REQUIRED` subject clearance is human-review HOLD; `BLOCKED` is a hard stop. `PROFILE_PHOTO` is prohibited as `SOCIAL_EDITORIAL` post media.

## Per-lane eligibility

Every active lane receives an explicit `UsageRequest` and `RightsLaneDecision`. The decision checks the exact current rights record, exact evidence-set hash, validity/review time, platform, purpose, territory, commercial context, required modifications, attribution and ShareAlike output license.

The output status is one of:

- `ELIGIBLE_RENDER_QA`;
- `HOLD_RIGHTS`;
- `HOLD_HUMAN_REVIEW`;
- `HOLD_STALE_RIGHTS`;
- `BLOCKED`.

No decision can set `publish_eligible=true`.

For the current native contract, Instagram Professional is the required downstream visual lane, Facebook Page is preferred and Threads is optional. M13 can hand off to M06 only when the required Instagram usage is `ELIGIBLE_RENDER_QA`. Failure on a preferred/optional lane does not silently grant that lane; its explicit HOLD/BLOCKED decision remains binding.

## Authority boundary

`RightsBoundVisualInput` has rights authority only. It always keeps fact, visual, approval, queue and publish authority false, and also keeps API writes, network fetch and real-account connection disabled.

## Persistence boundary

The validated historical CP13 canon described an append-only SQLite registry and revocation lineage, but those executable source bytes are unavailable in the canonical GitHub tree. CP39 therefore does not pretend that persistent store has been imported. The full DB/event-log implementation remains separately deferred; CP39 provides the deterministic values, hashes, revision semantics and eligibility contract that such a store can later persist.

## Pilot effect

M13 moves from historical evidence-only maturity to canonical executable source. The executable gap falls by one while the pilot remains fail-closed. M06 VISUAL becomes the next clean-room target.

No public publishing, real account connection, external media acquisition, paid service or deployment is authorized by CP39.
