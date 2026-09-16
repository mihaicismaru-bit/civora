# CP85 / M54 — INBOUND REPLY ENGINE v1

## Status

`CANDIDATE / OFFLINE ONLY / HUMAN REVIEW REQUIRED / NO POSTING AUTHORITY / LIVE HOLD`

Global control remains `CP58`. The global kill switch remains `ENGAGED`.

## Purpose

CP85 turns inbound comments, replies and account mentions into deterministic, evidence-bound response candidates without granting any runtime or posting authority. It consumes only caller-supplied offline observations. It performs no OAuth, account connection, token resolution, network request, live probe, publish, external write or deploy.

The engine is bounded to the active lanes `FACEBOOK_PAGE`, `INSTAGRAM_PROFESSIONAL`, and `THREADS` and binds every ingress route back to the CP83 Growth Capability Matrix. Unknown or non-PASS capabilities fail closed rather than being presented as supported automation.

## Canonical classifications

The exact CP85 classification set is:

- `QUESTION`
- `AGREEMENT_WITH_SUBSTANCE`
- `CORRECTION`
- `COUNTERPOINT`
- `EXPERT_LEAD`
- `COMMUNITY_SIGNAL`
- `LOW_VALUE`
- `ABUSE_SPAM`

Classification uses explicit local evidence tags with fail-safe precedence. Abuse/spam wins first; correction wins over question; unknown evidence fails closed. No sensitive-trait inference, sensitive relationship profiling, political microtargeting or synthetic conversation farming is permitted.

## Capability gating

Ingress is modeled as an exact `(platform, surface_kind)` route. `OWN_CONTENT_COMMENT` and `OWN_CONTENT_REPLY` bind to CP83 `INBOUND_REPLY`; `ACCOUNT_MENTION` binds to CP83 `MENTION_DISCOVERY`.

- Instagram Professional and Threads routes whose CP83 classification is `PASS_OFFLINE_CONTRACT` may be processed as offline automation candidates, but remain `HOLD_LIVE_PERMISSION` for any live read or write.
- Facebook Page inbound reply routes remain capability/live-permission held.
- Facebook Page mention discovery remains `MANUAL_ONLY` and therefore produces a capability hold rather than fake API support.
- An `OFFLINE_API_FIXTURE` is rejected on any route whose policy does not explicitly allow it.

## Response candidates

A reply candidate is generated only from explicit `response_evidence` supplied to the offline engine. The engine does not invent facts. If a substantive classification has no fact-bound response evidence, the result is `HOLD_EDITORIAL_CONTEXT_REQUIRED` with no reply text.

All generated reply text is a draft. `human_review_required=true`, `posting_authority=false`, `external_write_allowed=false`, `external_write_attempted=false`.

`LOW_VALUE` and `ABUSE_SPAM` are terminal no-reply outcomes. Existing terminal no-reply states cannot be resurrected by a later offline pass.

## Early-response SLA model

The engine labels candidates only for prioritization; it does not schedule or post them:

- `HOT_0_2H` — own content is at most 2 hours old.
- `PRIORITY_2_4H` — older than 2 hours and at most 4 hours old.
- `STANDARD_AFTER_4H` — older than 4 hours.

These are service-priority labels, not activity targets or authorization to reply.

## Deduplication and conversation state

Candidate identity is deterministic from platform, surface, inbound reference, conversation reference and owned-content reference. Identical duplicates collapse to one result. The same identity with conflicting payload bytes fails closed as `HOLD_CP85_CONFLICTING_DUPLICATE`.

Conversation-state outputs are explicit and monotonic across terminal states. The engine can return a draft for human review, a hold awaiting editorial context, or a terminal no-reply state; it cannot perform the actual reply.

## Zero fabricated external state

Unavailable external metrics are exactly `UNKNOWN`. No follower/reach/engagement metric is synthesized. No live API state is inferred from the offline contract.

## Rollback

Before promotion, rollback is branch/PR closure without merge. If CP85 is later merged but not closure-promoted, revert only the CP85 code/config/test/docs/module-registry changes. CP58 and the kill switch remain unaffected.

## Next unit after verified closure

Only after exact-head CI is terminal green, fresh-main drift is re-read, and CP85 is separately closure-promoted may work begin on `CP86 / M55 — OUTBOUND VALUE-ADD ENGAGEMENT ENGINE v1`.
