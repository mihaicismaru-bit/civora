# CP92 / M61 — PILOT GROWTH OPERATIONS MANUAL + SHADOW PILOT PLAN v1

## Status

`IMPLEMENTATION CANDIDATE / OFFLINE SHADOW PLAN ONLY / LIVE HOLD`

Global checkpoint remains `CP58`. The global kill switch remains `ENGAGED`. LIVE AUTHORITY remains `NONE`. CP92 is not yet closed, verified, promoted, or live-effective.

This unit defines the operator manual and future shadow-pilot contract only. It does **not** connect a real account, perform OAuth, resolve tokens/secrets, call a social API, execute a live read-only probe, observe real comments/mentions, perform an external write, publish, deploy, or use a paid service.

## Canonical purpose

CP92 implements the roadmap's final Growth development unit:

1. operator setup for engagement permissions and read-only validation;
2. shadow mode in which real comments/mentions may later be observed and recommendations generated without writes;
3. pilot success criteria and rollback;
4. an explicit authorization packet remains mandatory before any first real reply/comment/publish.

Because pilot/live authorization has not been granted, the executable implementation is deliberately split into:
- a **future operator permission-validation packet**;
- an **offline synthetic shadow-rehearsal engine**;
- a **success/rollback contract** that cannot mark a real shadow pilot complete.

## Artifacts

- `config/pilot_growth_operations_shadow_plan_policy.json`
- `src/public_presence_os/pilot_growth_operations.py`
- `tests/test_cp92_pilot_growth_operations.py`
- `docs/CP92_PILOT_GROWTH_OPERATIONS_MANUAL_SHADOW_PILOT_PLAN.md`
- `config/module_registry.json` M61 candidate marker

## Operator setup — future authorized read-only phase

For each active lane — Facebook Page, Instagram Professional, Threads — `build_operator_setup_packet()` emits a `MANUAL_ACTION_PACKET_AUTHORIZATION_REQUIRED`. The packet asks the operator to capture only the evidence needed for a future, explicitly authorized read-only validation:

- current official capability surface;
- read-only permission scope;
- object-level readback where applicable;
- zero write authority;
- kill-switch-engaged confirmation.

The packet itself performs no connection, credential exchange, OAuth, token resolution, API call, or probe.

Lane controls remain:
- Facebook Page: active target lane, future read-only validation required;
- Instagram Professional: active target lane, future read-only validation required;
- Threads: active target lane, future read-only validation required;
- LinkedIn: `HOLD_PRODUCTION_API_ACCESS`;
- X: `EXCLUDED_PAID_API`;
- Bluesky: `HOLD_ROI`.

Unknown capability remains `HOLD_CAPABILITY_UNVERIFIED`.

## Shadow mode contract

Until explicit pilot authorization, the executable path accepts **synthetic fixtures only**. A real/live observation raises `HOLD_CP92_LIVE_SHADOW_OBSERVATION_NOT_AUTHORIZED`.

For synthetic comments/replies/mentions, the engine may produce only:
- `RECOMMENDATION_ONLY_HUMAN_REVIEW`;
- `MANUAL_ACTION_PACKET`; or
- `HOLD_CAPABILITY_UNVERIFIED`.

It cannot dispatch a reply, comment, follow/unfollow action, quote/repost, publish, or other write. Missing metrics remain `UNKNOWN`.

The recommendation mapping is deliberately bounded:
- QUESTION → fact-bound inbound reply draft recommendation;
- CORRECTION → verification/correction response recommendation;
- COUNTERPOINT → respectful context/counterpoint recommendation;
- EXPERT_LEAD → human-review relationship-continuity escalation;
- MENTION → review for useful context;
- LOW_VALUE / ABUSE_SPAM → no engagement;
- unknown event → human review, never autonomous write.

## Growth safety

The existing Growth rules remain binding:
- no automated follow/unfollow;
- no mass-commenting;
- no engagement pods;
- no repetitive praise;
- no copy-paste replies;
- no synthetic conversation farming;
- no political microtargeting;
- no sensitive-trait inference;
- no sensitive relationship profiling;
- no clickbait optimization or fabricated conflict;
- rate budgets remain hard ceilings, never targets;
- relationship continuity uses only public, non-sensitive metadata;
- future writes must remain kill-switch-bound, receipt-bound, idempotent, bounded-retry, and fail-closed on exhaustion.

## Pilot success criteria

A future real shadow pilot may be called successful only when all canonical evidence exists:

1. capability matrix revalidated and current;
2. read-only permission receipts complete for active lanes;
3. real shadow observations generate useful recommendations with zero writes;
4. no unsupported-action drift;
5. missing metrics remain `UNKNOWN`;
6. growth-safety filters hold;
7. rate budgets remain ceilings;
8. audit/readback receipts are complete.

`evaluate_offline_shadow_rehearsal()` can return `PASS_CP92_OFFLINE_SHADOW_PLAN_REHEARSAL` for synthetic evidence. That state proves only that the **plan contract** can be rehearsed offline. It always returns `shadow_pilot_completed=false` and `authorization_captured=false`; it is not proof that the real shadow pilot occurred.

## Rollback

Any future shadow pilot must stop and remain on hold if there is:
- capability drift;
- authorization drift;
- kill switch not engaged;
- unsupported-action attempt;
- any external write;
- fabricated external state;
- sensitive-profiling signal;
- growth-safety violation.

The deterministic rollback packet requires stopping the shadow observation plan, preserving audit evidence, invalidating unverified capability assumptions, keeping the kill switch engaged, keeping LIVE AUTHORITY at NONE, and requiring fresh owner authorization before any future live step.

## Authorization boundary

No first real reply/comment/publish is permitted by CP92. Explicit owner authorization remains separately required after read-only validation and shadow-pilot evidence. CP92 does not promote global checkpoint CP58.

## Closure semantics

This implementation candidate is not CP92 closure. Closure requires:
- exact-head CI success;
- fresh PR mergeability/base-drift readback;
- bounded merge;
- post-merge readback;
- a separate closure-marker normalization unit if the established project workflow still requires it.

No checkpoint after CP92 is started or implied. Any future canonical unit requires a new explicit roadmap/owner decision.

## Rollback before merge

Close the CP92 implementation PR and discard the branch. `main` remains at CP91 CLOSED / VERIFIED / EFFECTIVE OFFLINE ONLY / LIVE HOLD.

## Next exact action

After this candidate is persisted, run exact-head CI and fresh PR/current-main/PPOS drift checks. Only on terminal CI SUCCESS, stable exact-head, mergeable PR, and no conflicting `public-presence-os/**` drift may the bounded CP92 implementation be merged and read back. Do not create or start CP93.
