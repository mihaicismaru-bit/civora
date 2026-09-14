# CP84 / M53 — ENGAGEMENT RADAR v1

## Scope

CP84 is the first executable Growth-loop discovery/scoring stage. It accepts only already-observed public-conversation candidates or offline/synthetic API fixtures, normalizes provenance and public metadata, scores eight canonical dimensions, and returns ranked candidates for human review.

It does **not** fetch a social network, connect an account, resolve credentials, publish, reply, comment, follow, quote/repost, deploy, or grant runtime authority.

## Parent binding

- parent activation checkpoint: `CP83`
- parent control checkpoint: `CP58`
- global kill switch: `ENGAGED`
- next unit: `CP85_INBOUND_REPLY_ENGINE`
- active platforms: `FACEBOOK_PAGE`, `INSTAGRAM_PROFESSIONAL`, `THREADS`

CP84 validates its six discovery routes against the compiled CP83 capability matrix. Any route/classification drift fails closed.

## Discovery routes

Only `MENTION_DISCOVERY` and `HASHTAG_TOPIC_DISCOVERY` are in CP84.

- Facebook Page: both routes are `MANUAL_ONLY`; manual public observations may be scored, but automation is never claimed.
- Instagram Professional: mentions and hashtagged-media discovery are `PASS_OFFLINE_CONTRACT`; any future live read remains permission/account gated.
- Threads: mention discovery is `PASS_OFFLINE_CONTRACT`; hashtag/topic discovery remains `HOLD_LIVE_PERMISSION` plus `HOLD_CAPABILITY_UNVERIFIED`.

Unknown platform/capability pairs fail as `HOLD_CAPABILITY_UNVERIFIED`.

## Provenance

Every candidate carries:

- platform and discovery capability;
- public conversation reference and public author/account identifier;
- source URL;
- topic and bounded context;
- observed and published timestamps;
- provenance kind and provenance reference;
- deterministic provenance and observation hashes.

Allowed provenance kinds are:

- `PUBLIC_URL_OBSERVATION`
- `OFFLINE_API_FIXTURE`
- `SYNTHETIC_FIXTURE`

Manual-only/unverified routes cannot use `OFFLINE_API_FIXTURE`. Public observations require HTTPS. Synthetic fixtures require `synthetic://`.

## Scoring

The eight canonical dimensions are exactly:

1. relevance
2. expertise fit
3. conversation momentum
4. novelty
5. answerability
6. reputational risk
7. spam risk
8. expected relationship value

All score evidence is explicit input on a 0–100 scale. CP84 does not fabricate unavailable platform metrics.

Benefit weights sum to 100. Reputational and spam risks apply deterministic penalties. Hard gates reject spam, reputational risk, low relevance, low answerability, prohibited safety signals, or hold stale candidates. Passing candidates are only `ELIGIBLE_HUMAN_REVIEW`.

## Safety

Hard safety invariants:

- posting authority is always false;
- external writes are always false;
- network access/fetch is always false;
- OAuth/account connection/live probe/deploy remain false;
- external metrics remain `UNKNOWN`;
- no automated follow/unfollow;
- no mass-commenting or engagement pods;
- no repetitive/copy-paste engagement;
- no synthetic conversation farming;
- no political microtargeting;
- no sensitive-trait inference;
- no sensitive relationship profiling.

A manually discovered candidate may rank highly, but this never converts its API capability to PASS.

## Idempotency / duplicate handling

Candidate identity is deterministic from platform + conversation reference + canonical source URL. Identical observations deduplicate. Conflicting observations for the same candidate identity fail closed as `HOLD_CP84_CONFLICTING_DUPLICATE`.

## Rollback

Remove:

- `config/engagement_radar_policy.json`
- `src/public_presence_os/engagement_radar.py`
- `tests/test_cp84_engagement_radar.py`
- this document
- the future M53 registry entry if/when added

Rollback target is CP83. CP58 remains the global control checkpoint and the kill switch remains engaged.
