# CP39 — M13 image rights / asset provenance minimal executable slice

CP39 reimplements the image-rights gate as canonical executable source without importing unavailable historical source bytes. It consumes no network and performs no account connection, publication, queue mutation or deploy.

## Contract

The local SQLite registry is append-only for source revisions, original assets, rights records, evidence snapshots and derivatives. Original identity is exact SHA-256. Provenance, evidence sets, terms, rights records, derivative lineage, eligibility decisions and visual-input bindings are deterministic hashes.

Discovery is not acquisition. `SOCIAL_DOWNLOAD_UNCLEARED`, `SEARCH_ENGINE_DOWNLOAD`, `PRESS_COPY_UNCLEARED` and `MAP_SCREENSHOT_AS_PHOTO` are rejected. A publicly visible URL is never treated as reuse permission. Automatic render-QA eligibility is limited to `OWNED`, `LICENSED` and `PUBLIC_DOMAIN`, and each requires snapshot-bound evidence. `FAIR_USE_REVIEW` is human-review only, `UNKNOWN` holds, and `BLOCKED` is a hard stop.

Licensed use is fail-closed on platform, purpose, territory, commercial use, modification policy, attribution, validity/review window and ShareAlike output-license compatibility. Public-domain use requires an explicit `PUBLIC_DOMAIN_DETERMINATION` or `CC0_DEDICATION`. Copyright clearance never substitutes for subject/privacy/personality clearance. `PROFILE_PHOTO` cannot become `SOCIAL_EDITORIAL` media.

Only Facebook Page, Instagram Professional and Threads are eligible visual targets. LinkedIn remains production-API-gated, X excluded while the API is paid, and Bluesky remains `HOLD_ROI`.

## Downstream boundary

`bind_visual_input()` creates a `RIGHTS_BOUND_VISUAL_INPUT_ONLY` object for M06 with exact asset, provenance, source, rights-record and eligibility hashes. This object has visual-render-input authority only; it has no story-fit, queue, publish or deploy authority and always reports `publish_eligible=false`.

## Safety

No live media is downloaded. No external asset is reused. Tests use synthetic hashes and local SQLite only. Kill-switch/runtime policy remains unchanged and engaged.
