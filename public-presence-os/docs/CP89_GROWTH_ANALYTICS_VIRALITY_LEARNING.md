# CP89 / M58 — GROWTH ANALYTICS + VIRALITY LEARNING v1

## State

CLOSED / VERIFIED / EFFECTIVE OFFLINE ONLY / LIVE HOLD.

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

## Closure evidence

- Original CP89 candidate PR: **#1223**.
- Candidate exact-head: `74ae362a8fe4439364a3671a0bfbe349d03fa3ef`.
- PUBLIC PRESENCE OS CI run **#205 / 35325310977** completed with terminal **SUCCESS** on that exact head.
- PR #1223 merged as commit `f464d3f4eefe1e966597ac39e37c2a9a8ee9d3d4`.
- Fresh current-main readback before this closure-normalization delta: `cd9b2a7bcf3ddb1772c262280fdc0fbb4334762d`.
- Current main is 6 commits ahead / 0 behind the CP89 merge commit and those intervening changes are outside `public-presence-os/**`; no conflicting PPOS drift was observed.
- M58 closure marker is normalized to `PASS_CP89_GROWTH_ANALYTICS_VIRALITY_LEARNING_OFFLINE_TRUTH_BOUND_UNKNOWN_PRESERVING_NON_CAUSAL_NO_STRATEGY_MUTATION_NO_EXTERNAL_WRITE_LIVE_HOLD` while the global registry checkpoint remains CP58.

This closure is **offline-only**. It does not authorize live account connection, OAuth, secrets, social API traffic, probes, publishing, replies/comments, deploys, or paid services.

## Rollback

If this closure-normalization candidate is not merged, close its PR and discard branch `ppos/cp89-closure-normalization-20260918`; the already-merged CP89 implementation remains on main with the pre-normalization marker text. After merge of the normalization delta, revert only that closure-marker commit if needed. Reverting the underlying CP89 implementation separately requires reverting merge commit `f464d3f4eefe1e966597ac39e37c2a9a8ee9d3d4`.

## Next gate

CP90 / M59 is the next eligible development checkpoint only after this closure-marker normalization has exact-head CI terminal SUCCESS, fresh mergeability/readback, merge, and post-merge verification. Do not start CP90 in this same run.
