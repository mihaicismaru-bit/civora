# CP88 / M57 — AMPLIFICATION ENGINE v1

State: **CANDIDATE / OFFLINE ONLY / LIVE HOLD**.

## Purpose
CP88 adds deterministic offline amplification selection to the Growth Loop. It identifies existing posts and public conversations that merit a materially new follow-up, second post, explainer, correction, future-content idea, or quote/repost handoff. It is a recommendation/packaging layer only: it grants no publishing, account, network, targeting, or external-write authority.

## Eligible outcomes
- `FOLLOW_UP_POST` — materially new continuation of an existing own post.
- `SECOND_POST` — distinct second treatment when the material delta and novelty gates pass.
- `EXPLAINER` — deeper treatment when a topic or strong thread needs explanation.
- `CORRECTION` — correction candidate when the correction-need threshold and material-delta gate pass.
- `CONTENT_IDEA` — converts a strong substantive thread into a future content idea without copying the thread.
- `QUOTE_REPOST` — never becomes an automated write in CP88; it is converted to a `MANUAL_ACTION_PACKET` only after rights/context checks.

## Selection and quality boundary
The offline score combines relevance, substance, novelty, follow-up value, and explanation value. Selection also requires materially new information and a minimum material delta. Strong comment threads may become explainers or future-content ideas. Weak, repetitive, low-novelty, or non-material candidates produce `NO_ACTION`.

Self-amplification is bounded by deterministic duplicate fingerprints. Reusing the same source/action/topic or recreating an equivalent content idea fails closed instead of producing repetitive posting. Exact receipt replay is idempotent; conflicting reuse of a provenance receipt fails closed.

## Capability and rights boundary
CP88 consumes the verified CP83 `QUOTE_REPOST` baseline without upgrading it:
- Facebook Page: `MANUAL_ONLY` → `MANUAL_ACTION_PACKET`.
- Instagram Professional: `UNSUPPORTED` → `MANUAL_ACTION_PACKET`, live gate `HOLD_CAPABILITY_UNVERIFIED`.
- Threads: `MANUAL_ONLY` → `MANUAL_ACTION_PACKET`.

Every quote/repost candidate requires explicit rights and context checks. Unknown capability is `HOLD_CAPABILITY_UNVERIFIED`. CP88 does not invent a broad quote/repost API write surface.

## Safety boundary
The module fails closed for political microtargeting, sensitive-trait inference, sensitive relationship profiling, synthetic conversation farming, fabricated conflict, non-public source evidence, unknown platforms, policy weakening, duplicate amplification, and batch overflow. Clickbait/conflict manufacture is not an amplification strategy.

## Authority
- Global control checkpoint remains **CP58**.
- Global kill switch remains **ENGAGED**.
- LIVE AUTHORITY remains **NONE**.
- No OAuth, account connection, token/secret resolution, social API traffic, live probe, publish, external write, automated targeting, deploy, or paid service.
- External metrics remain `UNKNOWN` unless actually observed in a later authorized phase.

## Rollback
Discard/revert the CP88 candidate files and remove the M57 candidate registry entry. Verified CP87 remains the predecessor; CP58 and the engaged kill switch remain unchanged.

## Promotion gate
Do not promote or merge CP88 until exact-head PUBLIC PRESENCE OS CI is terminal `SUCCESS` and a later fresh-main subtree-integrity/mergeability readback passes. CP89 must not start in the same unit.
