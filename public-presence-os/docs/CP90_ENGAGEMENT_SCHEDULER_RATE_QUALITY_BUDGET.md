# CP90 / M59 — ENGAGEMENT SCHEDULER + RATE/QUALITY BUDGET v1

**Status:** CLOSED / VERIFIED / EFFECTIVE OFFLINE ONLY / LIVE HOLD

## Control state

- Global checkpoint: **CP58**
- Global kill switch: **ENGAGED**
- LIVE AUTHORITY: **NONE**
- Parent checkpoint: **CP89 / M58 — CLOSED / VERIFIED / EFFECTIVE OFFLINE ONLY**
- Next checkpoint: **CP91 — NOT STARTED**

## Purpose

CP90 implements the deterministic scheduling and pacing layer for the Growth Loop. It converts already-prepared engagement candidates into a bounded offline schedule while enforcing quality, capability, rate, similarity, cooldown, thread-saturation, human-review and retry gates. The module performs no OAuth, token/secret resolution, social API call, external write, publication, deployment or paid-service call.

The scheduler is designed around the canonical early-engagement hot window after publication. It does **not** treat rate budgets as activity targets. Every budget is a hard ceiling, and an empty or low-volume queue is valid.

## Implemented contract

### Bounded hot-window polling

`EngagementScheduler.build_poll_plan()` produces deterministic timezone-aware polling slots. Policy defaults to a four-hour window with 30-minute polling and permits only the canonical 2–4 hour window. Invalid IANA timezones or unbounded windows fail closed.

### Hard rate ceilings

The offline policy defines explicit ceilings for:

- global daily engagement;
- global weekly engagement;
- per-account daily engagement;
- per-thread saturation window;
- outbound value-add daily actions;
- amplification daily actions.

These values are development safety ceilings, not targets and not live authorization.

### Quality + repetition control

The scheduler requires a minimum quality score, normalizes outgoing text deterministically, blocks exact or high-similarity repeats, enforces account cooldown, and caps thread saturation. No ML service or network call is used for similarity; CP90 uses a deterministic normalized-token Jaccard score.

### Queue fairness

Candidates receive a stable base priority (`INBOUND_REPLY`, then `OUTBOUND_VALUE_ADD`, then `AMPLIFICATION`) and a deterministic fairness round. Repeated candidates from the same account or thread cannot occupy every early queue position when alternatives exist. Stable tie-breaking uses quality, due time and action ID.

### Human-review boundary

Any conflict risk, reputational risk or ambiguous political-persuasion risk is routed to `HUMAN_REVIEW_REQUIRED`. CP90 does not optimize political persuasion and does not infer sensitive traits or sensitive relationships.

### Capability truthfulness

- Unknown or unverified capability → `HOLD_CAPABILITY_UNVERIFIED`.
- Manual-only or unsupported automation → `MANUAL_ACTION_PACKET`.
- A candidate that would require a real write → `HOLD_KILL_SWITCH_ENGAGED` while the canonical kill switch remains engaged and LIVE AUTHORITY is NONE.
- CP90 never assumes broad outbound commenting, follow/unfollow or another write surface.

### Receipt + retry safety

Every candidate receives a deterministic SHA-256 payload fingerprint. Matching prior receipt = idempotent no-op; conflicting receipt for the same action ID = fail-closed hold. Retry count is bounded by policy and exhaustion produces `HOLD_RETRY_EXHAUSTED_FAIL_CLOSED`.

### Forbidden growth mechanics

The policy explicitly rejects automated follow/unfollow, mass-commenting, engagement pods, repetitive praise, copy-paste replies, synthetic conversation farming, political microtargeting, sensitive-trait inference, sensitive relationship profiling, clickbait and fabricated conflict.

## Executable files

1. `config/engagement_scheduler_rate_quality_budget_policy.json`
2. `src/public_presence_os/engagement_scheduler.py`
3. `tests/test_cp90_engagement_scheduler_rate_quality_budget.py`
4. `docs/CP90_ENGAGEMENT_SCHEDULER_RATE_QUALITY_BUDGET.md`
5. `config/module_registry.json` — M59 PASS marker; global checkpoint remains CP58.

## Closure acceptance matrix

CP90 focused tests cover:

- CP58 / kill-switch / LIVE AUTHORITY invariants;
- bounded timezone-aware polling;
- clean offline dry-run eligibility;
- live-write kill-switch hold;
- capability-unverified hold;
- MANUAL_ACTION_PACKET fallback;
- human-review escalation;
- forbidden-mechanic rejection;
- quality floor;
- retry exhaustion fail-closed;
- semantic duplicate rejection;
- global daily and weekly ceilings;
- account ceiling and cooldown;
- thread saturation;
- hot-window expiry;
- receipt idempotency/conflict rejection;
- deterministic fairness ordering;
- inactive-lane hold;
- malformed-time fail-closed;
- deterministic fingerprints;
- type-specific outbound/amplification ceilings;
- invariant zero external writes / zero social API calls.

## Verified closure evidence

- Implementation PR: **#1226 — MERGED**.
- Candidate exact-head: `3a890dbfa4cb1ca69b6ef0fe4b717b8d5eb7ebba`.
- Implementation merge commit: `abfb4d4dbb5962dad8ff311aae7ab7b8adfc5131`.
- PUBLIC PRESENCE OS CI **#211 / run `35440446595` — SUCCESS** on the exact candidate head.
- Pre-merge attestation confirmed no conflicting PPOS/workflow drift before merge.
- Fresh post-merge comparison from `abfb4d4dbb5962dad8ff311aae7ab7b8adfc5131` to main `e86e513a1743e41c4956e3eb7ac56933cafacf2b` is **10 commits ahead / 0 behind** and contains **no `public-presence-os/**` changes**.
- CP58 remains the global checkpoint; kill switch remains ENGAGED; LIVE AUTHORITY remains NONE.

## Safety statement

This closed checkpoint is effective **offline only**. `ELIGIBLE_DRY_RUN` means only that an action may occupy an offline simulated schedule. It is **not** permission to send it. The module exposes no transport and reports `external_write_count=0` and `social_api_call_count=0` for every path.

## Decision

CP90 / M59 is CLOSED / VERIFIED / EFFECTIVE OFFLINE ONLY / LIVE HOLD. This closure does not promote the global checkpoint beyond CP58, disengage the kill switch, create live authority, connect any social account, resolve OAuth/tokens/secrets, perform a live probe, write externally, publish, deploy or invoke a paid service. CP91 remains NOT STARTED.

## Blocker

No product-semantic blocker remains for CP90. Closure-marker normalization itself must pass exact-head CI and be merged/read back before the registry/document closure state becomes authoritative on `main`.

## Rollback

Before closure-normalization merge: close the closure-normalization PR and discard branch `ppos/cp90-closure-normalization-20260919`; merged CP90 implementation remains intact with candidate markers on `main`.

After closure-normalization merge: revert only the closure-normalization commit/merge to restore candidate markers while leaving the CP90 implementation merge intact. Any implementation rollback is a separate explicit action and must not alter CP58, kill-switch state or LIVE AUTHORITY without authorization.

## Changelog

- 2026-09-19 — CP90 implementation PR #1226 merged after exact-head CI #211 SUCCESS and pre-merge no-overlap attestation.
- 2026-09-19 — Closure-marker normalization prepared: M59 PASS marker + CP90 CLOSED / VERIFIED / EFFECTIVE OFFLINE ONLY / LIVE HOLD documentation. No live authority granted; CP91 not started.

## NEXT EXACT ACTION

Run exact-head PUBLIC PRESENCE OS CI for the closure-normalization branch and fresh-read the PR/current main/base drift. If and only if CI is terminal SUCCESS, the exact-head is unchanged and no conflicting `public-presence-os/**` drift appears, perform only the CP90 closure-normalization merge + post-merge readback. Do not start CP91 in the same run.
