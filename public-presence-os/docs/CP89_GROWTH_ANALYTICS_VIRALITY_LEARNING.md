# CP89 / M58 — GROWTH ANALYTICS + VIRALITY LEARNING v1

## State

CANDIDATE / OFFLINE ONLY / NOT MERGED / NOT PROMOTED / LIVE HOLD.

Global control checkpoint remains **CP58**. Global kill switch remains **ENGAGED**. LIVE AUTHORITY remains **NONE**.

CP90 is not started by this changeset.

## Purpose

CP89 implements the Growth Loop analytics stage as a deterministic, truth-bound offline engine. It turns explicit aggregate evidence into funnel telemetry, canonical growth metrics, descriptive topic-level profiles, and non-causal virality learning packets without fetching external metrics, mutating strategy, connecting accounts, or writing to a social platform.

The primary funnel is:

`publication → reach/impressions → engaged users → comments/replies → profile visits where available → follows where available → repeat engagement → conversation depth`

## Canonical metrics

The engine implements:

- `engagement_per_reached_user = engaged_users / reach`
- `meaningful_comment_rate = meaningful_comments / comments`
- `reply_rate = replies / response_opportunities`
- `median_first_reply_latency = median(first_reply_latencies_seconds)`
- `conversation_depth = mean(conversation_depth_samples)`
- `repeat_engager_rate = repeat_engagers / engaged_users`
- `profile_visit_rate = profile_visits / reach`
- `follower_conversion_rate = follows / profile_visits`
- `outbound_comment_response_rate = outbound_comments_with_response / outbound_comments`
- `relationship_reactivation_rate = reactivated_relationships / eligible_dormant_relationships`
- `amplification_yield = successful_amplifications / amplification_candidates`
- `topic_to_growth_attribution = descriptive non-causal topic-grouped metric profile`

Missing inputs remain `UNKNOWN`. A zero denominator also remains `UNKNOWN`; it is never silently converted to zero. Aggregate reports expose explicit `KNOWN`, `PARTIAL`, or `UNKNOWN` coverage.

## Evidence model

`GrowthObservation` accepts only aggregate content-level evidence for the three active lanes: Facebook Page, Instagram Professional, and Threads. Candidate evidence classes are `SYNTHETIC_OFFLINE` and `VERIFIED_READBACK_IMPORT`. CP89 itself performs no live readback and no network request.

Person-level identifiers, sensitive-trait data/inference, sensitive relationship profiling, political microtargeting, synthetic conversation farming, clickbait optimization, and conflict fabrication fail closed.

## Virality learning

Virality is modeled only as an observed combination of:

1. topic selection;
2. packaging;
3. early engagement;
4. network propagation.

All four components must be explicitly available before an observed virality signal score is computed. The score is descriptive and non-causal. It never becomes an automatic strategy mutation. Learning output is limited to human-review notes such as preserving an evidence-bound follow-up pattern, reviewing packaging clarity without clickbait, or examining distribution context without synthetic amplification.

No manufactured conflict, engagement bait, or mechanical duplication is recommended.

## Topic attribution

Topic-to-growth output groups known metric evidence by topic. It is explicitly `DESCRIPTIVE_NON_CAUSAL`; the module cannot claim that a topic caused growth. Partial evidence is labeled instead of filled with fabricated values.

## Idempotency and fail-closed behavior

- Each observation is bound to an `observation_ref` and `provenance_ref`.
- Exact provenance replay returns the prior deterministic result.
- Conflicting provenance or observation-reference reuse fails closed.
- Batch size is a hard ceiling.
- Batch processing is atomic with respect to in-memory CP89 state: a failing observation leaves no partial receipts.
- Reports are deterministically hashed and validated before state commit.

## Authority boundary

CP89 grants no external authority:

- no external metric fetch;
- no external write;
- no social API traffic;
- no OAuth;
- no account connection;
- no live probe;
- no posting authority;
- no strategy mutation authority;
- no control-plane promotion;
- no deploy;
- no paid service.

The global checkpoint remains CP58 and the kill switch remains ENGAGED.

## Rollback

Before merge, close the CP89 PR and delete the candidate branch. After merge, revert the CP89 merge commit. CP88 / M57 remains the verified predecessor either way.

## Next gate

After exact-head CI reaches terminal SUCCESS, re-read current `main`, the `public-presence-os` subtree, PR mergeability, and base drift. Only a later bounded CP89 gate/closure unit may merge or promote this candidate. Do not start CP90 in the same run.
