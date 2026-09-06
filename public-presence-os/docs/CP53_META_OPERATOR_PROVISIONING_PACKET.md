# CP53 — Meta Operator Provisioning Packet + Offline Checklist v1

## Scope

CP53 converts the exact CP52 synthetic connection preflight plus its exact CP51 connection profile into a deterministic operator-facing provisioning packet. The packet is preparation evidence only. It does not resolve credentials, observe real accounts, call Meta, connect destinations, publish, write externally or deploy.

Active lanes remain exactly:

- Facebook Page;
- Instagram Professional;
- Threads.

Deferred lanes remain unchanged:

- LinkedIn: production API access required;
- X: excluded while the API is paid;
- Bluesky: `HOLD_ROI` until a later local ROI decision.

## Contract inputs

A CP53 packet requires:

1. an exact, valid CP52 `SyntheticPreflightReceipt` in `PASS_SYNTHETIC_PREFLIGHT_ONLY`;
2. the exact CP51 `ConnectionProfile` bound by that receipt;
3. exact equality for platform, mode, auth-reference kind, required permissions and required capabilities;
4. complete offline evidence already accepted by CP51/CP52;
5. the global fail-closed rule that live reverification is still mandatory.

Any mismatch fails closed.

## What the packet contains

The packet is SHA-256-bound and deterministic. It contains only safe operator metadata:

- CP52 receipt id/hash;
- CP51 profile id/hash;
- platform and mode;
- symbolic auth-reference kind;
- symbolic `ENV:` or `OS_KEYCHAIN:` secret-reference locator;
- required permission set;
- required capability set;
- lane-specific prerequisites;
- operator checklist items;
- explicit live blockers.

No credential material is accepted or emitted.

## Offline checklist model

Checklist items have only two kinds of state in CP53:

- offline contract evidence already proven by CP51/CP52;
- pending operator/future-checkpoint evidence that must remain blocking for live connection.

A CP53 packet therefore being `OFFLINE_OPERATOR_PACKET_READY` never means `live_connection_ready` and never means `pilot_publish_ready`.

The required operator evidence covers:

- ownership/control of the intended destination and sufficient operator access;
- current Meta app/use-case configuration;
- current official permission and capability reverification;
- token expiry/rotation/revocation policy, without storing the token;
- future exact destination binding;
- future exact API-version pinning;
- a future explicitly authorized read-only connection test before any write path;
- kill-switch, disconnect, revocation and local rollback recovery;
- a fresh final human authorization after all pilot gates pass.

## Lane-specific prerequisites

### Facebook Page

The packet requires operator evidence that the Page exists, the operator has sufficient Page access, the Meta app/self-use context is defined, the Page publishing permission path is reverified against current official Meta documentation, and the Page access-token mint path is documented out of band. The exact required permissions remain bound from CP50/CP51 rather than retyped by the operator.

### Instagram Professional

The packet requires operator evidence that the account is Professional (Business or Creator), the current Instagram publishing product/use case is configured, publish permissions are reverified against current official Meta documentation, and live media-staging requirements are documented for image publishing. CP53 does not stage media or observe an account.

### Threads

The packet requires operator evidence that the Threads profile exists, the Threads API use case is configured, publish permissions are reverified against current official Meta documentation, and the create-then-publish container flow is reverified before any future live test.

## Freshness rule

Meta platform setup, permissions, product names, API versions, token behavior and app-review requirements can change. CP53 deliberately does not freeze a literal live API version or claim current entitlement. Immediately before a future live connection test, the operator must reverify the relevant official Meta documentation and bind dated evidence into a later checkpoint.

The implementation canon current on 2026-09-06 keeps these permission contracts in the executable CP50/CP51 source:

- Facebook Page: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`;
- Instagram Professional: `instagram_business_basic`, `instagram_business_content_publish`;
- Threads: `threads_basic`, `threads_content_publish`.

Those values remain pre-live contract evidence only until live reverification succeeds.

## Safety boundary

CP53 always records or implies all of the following as false:

- secret material included;
- secret resolved;
- environment read;
- keychain read;
- network attempted;
- real account lookup attempted;
- account connected;
- publish attempted;
- external write performed;
- deploy performed;
- live entitlement verified;
- live connection ready;
- pilot publish ready.

The global kill switch remains required.

## Completion criterion

CP53 is complete when:

- the packet compiler is deterministic and hash-bound;
- all active lane/mode combinations compile from exact CP52+CP51 evidence;
- mismatches and tampering fail closed;
- policy and product-layout validation pass;
- full tests pass;
- reproducible packaging passes;
- no secret, network, real account, publishing or deploy capability is introduced.

## Next granular unit

`CP54_META_TRANSPORT_TEST_TWIN_AND_REQUEST_SIGNING_BOUNDARY`

CP54 should implement a synthetic Meta transport test twin and a request-signing/auth-header boundary that operates only on fake credential material injected by tests. It must prove serialization, retry classification and idempotency behavior without environment/keychain reads, real tokens, real endpoints, network calls, account connection, publishing or deploy.
