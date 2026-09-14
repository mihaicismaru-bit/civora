# CP83 / M52 — GROWTH CAPABILITY MATRIX + ENGAGEMENT API GATE v1

## State
CANDIDATE_IMPLEMENTATION — OFFLINE CONTRACT ONLY — LIVE HOLD

## Control
- Global control checkpoint remains **CP58**.
- Global kill switch remains **ENGAGED**.
- Parent activation checkpoint: **CP82 / M51 — CLOSED / VERIFIED / EFFECTIVE**.
- Next unit is only named: **CP84 / M53 — ENGAGEMENT RADAR v1**. CP84 is not implemented here.

## Purpose
CP83 converts the Growth-loop platform baseline into an exact, fail-closed capability gate for the three active lanes: Facebook Page, Instagram Professional and Threads.

The matrix is the exact Cartesian product of 3 platforms × 7 capability kinds = 21 rows: `INBOUND_REPLY`, `OUTBOUND_COMMENT`, `MENTION_DISCOVERY`, `HASHTAG_TOPIC_DISCOVERY`, `QUOTE_REPOST`, `INSIGHTS`, `FOLLOW`.

Each row is classified as exactly one of `PASS_OFFLINE_CONTRACT`, `HOLD_LIVE_PERMISSION`, `UNSUPPORTED`, `MANUAL_ONLY`. `PASS_OFFLINE_CONTRACT` means only that an official documented surface is sufficient to model an offline contract. It never grants live permission or runtime authority.

## Capability decisions
### Facebook Page
The current official Meta Postman material gives a current Page-token/task baseline, but this unit does not assume arbitrary external-object commenting, generic hashtag/topic discovery, quote/repost automation or automated follow/unfollow. Where exact write/discovery capability is not verified, the row fails closed to `MANUAL_ONLY` with `HOLD_CAPABILITY_UNVERIFIED`.

### Instagram Professional
Official Meta material supports own-media comment management/replies, mention discovery, hashtagged-media discovery and professional metadata/metrics. Those exact surfaces can be modeled offline, but live use remains permission/account/readback gated. Arbitrary third-party outbound commenting is not assumed. Follow stays manual by policy.

### Threads
Official Meta material supports reply reading/management, mention discovery and post insights. CP83 permits an offline contract for an outbound value-add reply only when it is scoped to a specific readable post/reply; broad or mass commenting authority remains forbidden. Any unverified quote/repost write stays manual.

## Manual fallback
Any `MANUAL_ONLY` or `UNSUPPORTED` action must produce a deterministic `MANUAL_ACTION_PACKET`. The packet explicitly records that automation and external write were not attempted, human review is required and the kill switch is engaged. Unknown platform/capability pairs fail closed as `HOLD_CAPABILITY_UNVERIFIED`.

## Truthfulness
No live metric value is inferred. Every unavailable external metric remains `UNKNOWN`.

## Growth safety
CP83 encodes hard prohibitions against automated follow/unfollow, mass-commenting, engagement pods, repetitive praise, copy-paste replies, synthetic conversation farming, political microtargeting, sensitive-trait inference and sensitive relationship profiling. Broad outbound commenting is never assumed. Future writes remain required to be kill-switch-bound, receipt-bound, idempotent, bounded-retry and fail-closed.

## Official evidence locators
- Meta / Facebook Postman: https://www.postman.com/meta/facebook/documentation/r56bjfd/facebook-api
- Meta / Instagram Postman: https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login
- Meta / Threads replies Postman: https://www.postman.com/meta/threads/folder/34203612-1cc7918f-d63d-45fd-bdaa-e8855d0338cb
- Meta / Threads mentions Postman: https://www.postman.com/meta/threads/request/34203612-fc3f21da-0a53-44ab-80e2-8cd8c376a42a
- Meta / Threads insights Postman: https://www.postman.com/meta/threads/request/34203612-385abc7d-b3cc-4e5d-9937-ebbe7174e041

These locators are evidence for the offline contract only. Real permissions, account linkage, exact object writeability and live API responses remain unverified until a separately authorized read-only/provisioning phase.

## Explicit non-authority
This unit performs no account connection, OAuth, token/secret resolution, environment/keychain read, social API traffic, live probe, external write, publish, deployment or paid-service use.

## Rollback
Rollback target: CP82. Delete the four CP83 files and remove M52 from `module_registry.json`; CP58 remains the global control checkpoint.

## Next exact action
After exact-head repository CI is available, read it. If fully green, re-read current `main`, verify zero overlapping `public-presence-os/**` drift and PR mergeability, then perform the bounded CP83 integration/closure step only. Do not start CP84 in the same run.
