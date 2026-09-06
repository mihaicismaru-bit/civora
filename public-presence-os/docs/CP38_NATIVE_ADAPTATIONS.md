# CP38 — M05 Native Adaptations Minimal Executable Slice + FB/IG/Threads Contract v1

CP38 reimplements M05 as canonical executable source without connecting accounts, calling platform APIs, mutating queues, publishing or deploying.

## Inputs

M05 accepts only canonical M04 `MasterDraftBrief` objects. It validates the CP37 brief ID/hash, authority flags, source class, attribution requirements and support-item evidence binding before adapting anything.

An M04 brief that is not `native_adaptation_input_ready=true` remains HOLD on every active lane. M05 does not repair upstream evidence gaps.

## Active lanes

Exactly three lanes are materialized:

- `FACEBOOK_PAGE`
- `INSTAGRAM_PROFESSIONAL`
- `THREADS`

LinkedIn remains gated on production API access. X remains excluded while API use is paid. Bluesky remains `HOLD_ROI`.

## Adaptation rule

M05 is deliberately conservative. It may only rearrange the exact M04 source title and source excerpt and add fixed attribution scaffolding. It may not paraphrase, truncate, infer hashtags, infer entities, infer calls to action, infer impact, infer audience fit or invent connective factual claims.

Channel-specific renderings are therefore structural rather than generative:

- Facebook Page: headline + clearly labeled primary-source context + source URL.
- Instagram Professional: caption-oriented headline/context + primary-source attribution; downstream visual is required.
- Threads: compact headline/context + source attribution.

The configured character budgets are internal editorial house limits, not assertions about platform API maxima. If the exact evidence-bound text does not fit a lane's house budget, that lane becomes `HOLD_LENGTH_BUDGET`; text is not truncated. The bundle becomes rights-input-ready only when all three active lanes are ready.

## Authority boundary

M05 has native-adaptation authority only. It has no fact, visual, queue or publish authority. `api_write_allowed=false`, `network_fetch_performed=false`, and `real_account_connection_performed=false` are structural invariants.

## Downstream handoff

A fully ready M05 bundle can enter the rights/provenance stage. CP38 intentionally does not implement image rights, visual generation, QA, approval, queueing or publishing.

## Pilot posture

This slice is pre-pilot and dry-run only. No public post, account connection, external write or deployment is authorized by CP38.
