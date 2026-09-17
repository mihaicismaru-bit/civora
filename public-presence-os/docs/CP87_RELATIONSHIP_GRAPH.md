# CP87 / M56 — RELATIONSHIP GRAPH v1

State: **CANDIDATE / OFFLINE ONLY / LIVE HOLD**.

## Purpose
CP87 adds a deterministic offline relationship-continuity graph for the Growth Loop. It stores only public, non-sensitive interaction metadata needed to remember prior public exchanges. It does not create targeting authority, publishing authority, account connectivity, network access, or any external write.

Canonical node types:
- `public_account`
- `content`
- `conversation`

Canonical edges:
- `replied_to`
- `mentioned`
- `quoted`
- `recurring_interaction`
- `shared_topic`
- `prior_useful_exchange`

## Privacy boundary
The graph accepts only explicit public identifiers, public content/conversation references, public conversation topic, UTC observation time, interaction-quality score, and a provenance reference. Arbitrary `extra_metadata` is rejected.

The module fails closed for:
- non-public evidence or visibility;
- sensitive-trait data or inference;
- sensitive relationship profiling;
- political microtargeting;
- unknown platform or interaction kind;
- conflicting reuse of the same provenance receipt.

It never infers political ideology, health, religion, sexuality, ethnicity, demographics, or other sensitive traits. The relationship score is computed only from repeated public interaction quality plus a bounded repetition bonus. The only permitted use is `CONTINUITY_CONTEXT_ONLY_NOT_ACTION_AUTHORITY`.

## Idempotency
Each interaction is receipt-bound by `(platform, provenance_ref)` plus the canonical payload hash. Exact replay is idempotent and does not mutate the graph. Conflicting reuse of the same provenance receipt fails closed.

## Authority
- Global control checkpoint remains **CP58**.
- Global kill switch remains **ENGAGED**.
- LIVE AUTHORITY remains **NONE**.
- No OAuth, account connection, token/secret resolution, social API traffic, live probe, posting, external write, automated targeting, deploy, or paid service.
- Unavailable external metrics remain `UNKNOWN`.

## Rollback
Revert the CP87 candidate files and the M56 candidate registry entry. Verified CP86 remains the predecessor and CP58/kill-switch authority state remains unchanged.

## Promotion gate
Do not promote or merge CP87 until exact-head repository CI is terminal `SUCCESS` and a later fresh-main overlap/mergeability readback passes. CP88 must not start in the same unit.
