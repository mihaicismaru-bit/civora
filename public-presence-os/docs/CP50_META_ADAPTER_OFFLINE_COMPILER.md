# CP50 — Meta Free-API Adapter Contract + Offline Request Compiler v1

## Status

`PASS_CP50_OFFLINE_META_ADAPTER_COMPILER / HOLD_PILOT_CONNECTION_PROFILE_SECRET_REFERENCE_AND_OPERATOR_PROVISIONING`

CP50 adds the canonical free-API adapter contract for the three active PUBLIC PRESENCE OS lanes: Facebook Page, Instagram Professional, and Threads. It compiles deterministic request plans only. It performs no HTTP request, credential resolution, account lookup, OAuth action, account connection, remote write, publication, or deploy.

## Scope completed

- Added `public_presence_os.meta_adapters` with immutable offline publish intents, deterministic request steps, exact SHA-256 request-plan binding, and fail-closed validation.
- Added a static capability contract per active platform and mode without asserting real account entitlement.
- Bound text payloads by SHA-256 and single-image plans by exact media SHA-256 plus alt-text SHA-256.
- Enforced symbolic future bindings only: `DESTINATION_ID_REQUIRED`, `API_VERSION_REQUIRED`, and `STAGING_URL_REQUIRED`.
- Kept authentication as typed reference kinds only: `PAGE_ACCESS_TOKEN_REF`, `INSTAGRAM_USER_TOKEN_REF`, and `THREADS_USER_TOKEN_REF`.
- Added `meta_adapter_policy.json`, regression tests, product-layout registration, module registry state, and next-unit checkpointing.

## Active adapter plans

### Facebook Page

- TEXT: one offline POST template to `/{API_VERSION}/{DESTINATION_ID}/feed` on `graph.facebook.com`.
- SINGLE_IMAGE: one offline POST template to `/{API_VERSION}/{DESTINATION_ID}/photos` with the symbolic media staging reference.
- Required permission contract: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`.
- Authentication binding remains a Page token reference; no token material is present in source or plans.

### Instagram Professional

- SINGLE_IMAGE only in CP50.
- Create container: `/{API_VERSION}/{DESTINATION_ID}/media` on `graph.instagram.com`.
- Publish container: `/{API_VERSION}/{DESTINATION_ID}/media_publish`.
- Required permission contract for Instagram Login: `instagram_business_basic`, `instagram_business_content_publish`.
- Media staging stays a symbolic placeholder because Meta retrieves publishing media from a publicly reachable URL during a future live attempt.

### Threads

- TEXT and SINGLE_IMAGE.
- Create container: `/{API_VERSION}/{DESTINATION_ID}/threads` on `graph.threads.net`.
- Publish container: `/{API_VERSION}/{DESTINATION_ID}/threads_publish`.
- Required permission contract: `threads_basic`, `threads_content_publish`.
- SINGLE_IMAGE binds media hash and alt text; the compiled create step includes the symbolic media URL and alt text.

## Fresh platform verification — 6 September 2026

Current Meta-owned Postman resources were checked before closing the contract. The Facebook workspace still documents managed-Page token acquisition and Page-scoped acting identity. The official Instagram workspace is current in September 2026 and documents professional-account publishing with Instagram Login, `graph.instagram.com`, image-container creation, container publication, and the two business publishing permissions used above. The official Threads workspace was updated on 2 September 2026 and documents the two-phase text/image container and publish flow.

Facebook Page publication endpoint templates remain inherited from the already-canonized CP17 publisher contract and are marked `REVERIFY_BEFORE_LIVE`; CP50 does not turn a historical endpoint template into immutable platform truth. Every platform plan carries `live_reverification_required=true`, and API versions remain placeholders rather than literals.

Reference resources used for the current verification:

- Meta verified Postman team: `https://www.postman.com/meta/`
- Facebook API managed Pages token collection: `https://www.postman.com/meta/facebook/`
- Instagram official workspace: `https://www.postman.com/meta/instagram/overview`
- Instagram publishing documentation: `https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api`
- Threads official workspace: `https://www.postman.com/meta/threads/overview`
- Threads publishing documentation: `https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api`

## Fail-closed rules

1. Only `FACEBOOK_PAGE`, `INSTAGRAM_PROFESSIONAL`, and `THREADS` compile.
2. LinkedIn, X, and Bluesky are structurally rejected by this module.
3. Real destination IDs are forbidden; only the destination placeholder is accepted.
4. Literal API versions are forbidden; versions are future configuration bindings.
5. Single-image plans require exact media SHA-256, non-empty alt text, and the staging URL placeholder; a real URL is rejected.
6. Credential-bearing request parameter keys are forbidden.
7. Wire-level idempotency headers remain disabled until an endpoint-specific authoritative contract exists.
8. Network, secret resolution, real-account lookup, account connection, publication execution, external write, and deploy authority are all false.
9. The global kill switch remains required.
10. A compiled plan is not proof of permissions, capability, account connectivity, or publish eligibility.

## Validation contract

CP50 regression coverage requires:

- deterministic Facebook text and image plans;
- deterministic two-phase Instagram image plan;
- deterministic Threads text and image plans;
- Instagram text-only fail-closed behavior;
- structural rejection of LinkedIn, X, and Bluesky;
- rejection of real destination IDs, literal API versions, and real staging URLs;
- exact media/alt-text binding for images;
- plan-hash tamper detection;
- capability contracts that never assert real entitlement;
- static absence of network clients and secret-resolution functions;
- unchanged global runtime safety: kill switch engaged, network off, accounts disconnected, publishing off, deploy off.

Full repository CI is the promotion gate before merge.

## Canonical decisions

1. CP50 is a compiler, not a transport. Request plans may describe future API operations but cannot execute them.
2. Active lane scope remains exactly Facebook Page, Instagram Professional, and Threads.
3. LinkedIn remains `PRODUCTION_API_ACCESS_REQUIRED`; X remains `EXCLUDED_WHILE_API_PAID`; Bluesky remains `HOLD_ROI`.
4. Platform API versions are configuration inputs and must not be scattered literals in source.
5. Current platform documentation is evidence for the contract, not authorization to connect an account.
6. Instagram CP50 uses the current Instagram Login publishing family on `graph.instagram.com`.
7. Image publication cannot proceed to a future live adapter without a separately designed public-media staging solution; CP50 only carries `STAGING_URL_REQUIRED`.
8. Alt text remains exact-hash bound even when a platform-specific CP50 wire template does not transmit it.
9. No remote idempotency guarantee is inferred from local deterministic plan hashes.
10. Every endpoint family must be freshly reverified again immediately before live transport is ever enabled.

## Changelog

- Added offline Meta request compiler and validators.
- Added platform contracts for Facebook Page, Instagram Professional, and Threads.
- Added exact text/media/alt-text binding and deterministic plan IDs/hashes.
- Added fail-closed symbolic destination/API-version/media-staging rules.
- Added CP50 adapter policy and safety authority map.
- Added CP50 regression tests and product-layout validation entries.
- Added `M19_META_ADAPTERS` to the module registry.
- Advanced the next exact unit to CP51.

## Blockers / holds after CP50

- `HOLD_META_CONNECTION_PROFILE_NOT_IMPLEMENTED`: no executable current-source connection-profile and secret-reference boundary yet exists in the clean-room implementation.
- `HOLD_OPERATOR_EXACT_LOCAL_FONT_FILES_REQUIRED`: production-like local visual rendering still requires operator-supplied CP48-exact font files.
- Real Meta app configuration, OAuth, token acquisition/refresh, secret resolution, real account/page/profile binding, public-media staging, live transport, remote reconciliation, publication receipt, and live analytics remain intentionally OFF.
- LinkedIn production API access remains externally gated; X remains excluded while paid; Bluesky remains ROI-gated.

## Safety state

- public publishing: OFF
- real account connection: OFF
- credential resolution: OFF
- external network calls: OFF
- external publisher writes: OFF
- deploy: OFF
- paid services introduced: NONE
- global kill switch: ENGAGED

## Rollback

Rollback target: CP49. Remove the CP50 adapter source, policy, tests, documentation, and registry changes. No external rollback is required because CP50 performs no external mutation.

## Next exact granular unit

`CP51 — META CONNECTION PROFILE + SECRET-REFERENCE VAULT MINIMAL EXECUTABLE SLICE v1`

Scope: reimplement the local zero-cost connection-profile and secret-reference boundary for Facebook Page, Instagram Professional, and Threads using typed `ENV:` / `OS_KEYCHAIN:` locators and immutable capability/permission/expiry evidence, while keeping token values, OAuth execution, secret resolution, real accounts, network transport, publishing, and deploy disabled.
