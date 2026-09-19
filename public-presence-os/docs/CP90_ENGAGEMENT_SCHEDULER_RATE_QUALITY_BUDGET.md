# CP90 / M59 — ENGAGEMENT SCHEDULER + RATE/QUALITY BUDGET v1

**Status:** CANDIDATE / OFFLINE ONLY / NOT MERGED / NOT PROMOTED / LIVE HOLD

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
5. `config/module_registry.json` — M59 candidate marker only; global checkpoint remains CP58.

## Candidate acceptance matrix

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

## Safety statement

This candidate is offline-only development code. `ELIGIBLE_DRY_RUN` means only that an action may occupy an offline simulated schedule. It is **not** permission to send it. The module exposes no transport and reports `external_write_count=0` and `social_api_call_count=0` for every path.

## Rollback

Before merge, rollback is to close the CP90 PR and discard branch `ppos/cp90-engagement-scheduler-rate-quality-budget-20260919`. `main` then remains at the verified CP89 PPOS subtree.

## Promotion gate

Do not mark M59 PASS and do not start CP91 until:

1. exact-head PUBLIC PRESENCE OS CI reaches terminal SUCCESS;
2. focused CP90 tests pass in CI;
3. fresh PR mergeability is true;
4. fresh `main` has no conflicting `public-presence-os/**` drift;
5. candidate artifacts are read back from GitHub;
6. CP90 checkpoint/evidence is persisted and read back in canonical Drive.

No merge or CP91 work belongs to the CP90 candidate-creation unit.
