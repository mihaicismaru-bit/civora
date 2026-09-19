# CP91 / M60 — GROWTH DRY-RUN ACCEPTANCE SUITE v1

## Status

`CANDIDATE / OFFLINE SYNTHETIC ONLY / LIVE HOLD`

Global checkpoint remains `CP58`. The global kill switch remains `ENGAGED`. LIVE AUTHORITY remains `NONE`. CP92 is not started.

## Purpose

CP91 is the integration acceptance gate for the Growth Loop implemented in CP83–CP90. It uses only deterministic synthetic/offline fixtures and existing executable contracts. It does not connect accounts, resolve tokens or secrets, perform OAuth, call a social API, run a live probe, publish, perform an external write, deploy, or use a paid service.

The suite proves the nine canonical roadmap requirements:

1. one synthetic publication produces bounded engagement-monitor tasks through the CP90 scheduler contract;
2. CP85 inbound comments are SLA-ranked and fact-bound response candidates remain dry-run/human-review only;
3. CP84/CP86 outbound conversations are scored, low-value candidates are rejected, and growth-safety/spam-like proposals are rejected;
4. CP87 relationship graph replay is idempotent;
5. duplicate inbound replies and scheduler actions cannot create a second effect;
6. CP90 hard rate ceilings stop excess synthetic activity;
7. the engaged kill switch suppresses every represented write path and all external-I/O counters remain zero;
8. unverified or unsupported capability becomes `MANUAL_ACTION_PACKET` or `HOLD_CAPABILITY_UNVERIFIED`, never false PASS;
9. CP89 missing analytics remain `UNKNOWN`/`None`, never coerced to zero.

## Executable artifacts

- `config/growth_dry_run_acceptance_policy.json`
- `src/public_presence_os/growth_dry_run_acceptance.py`
- `tests/test_cp91_growth_dry_run_acceptance.py`
- `docs/CP91_GROWTH_DRY_RUN_ACCEPTANCE_SUITE.md`
- `config/module_registry.json` candidate marker

The CP91 harness adds no production dispatch path. `build_engagement_monitor_tasks()` creates deterministic offline task descriptors from CP90 poll slots. `evaluate_acceptance()` requires all nine named evidence gates, rejects any observed external I/O, preserves missing external state as `UNKNOWN`, and fails closed if the policy weakens.

## Safety invariants

- Active lanes: Facebook Page, Instagram Professional, Threads only.
- LinkedIn, X and Bluesky receive no new authority.
- Unknown/unverified write capability remains `HOLD_CAPABILITY_UNVERIFIED`.
- Unsupported/manual-only actions remain manual packets rather than simulated automation.
- Automated follow/unfollow, mass-commenting, engagement pods, repetitive praise, copy-paste replies, synthetic conversation farming, political microtargeting, sensitive-trait inference, sensitive relationship profiling, clickbait optimization and fabricated conflict remain forbidden.
- Rate budgets are ceilings, never targets.
- Future writes must remain kill-switch-bound, receipt-bound, idempotent and bounded-retry/fail-closed.
- No external metric is fabricated; missing metrics remain `UNKNOWN`.

## Acceptance semantics

The executable harness may produce `PASS_CP91_OFFLINE_SYNTHETIC_ACCEPTANCE` for a fully passing synthetic evidence bundle. That result is an internal test outcome only. It does **not** itself make CP91 authoritative on `main`, does not promote global checkpoint CP58, and does not grant live authority.

Repository registry state remains a CP91 candidate until exact-head CI is terminal `SUCCESS`, the PR is mergeable without conflicting PPOS drift, the bounded change is merged, and post-merge readback is verified and persisted to the canonical Drive checkpoint.

## Rollback

Before merge: close the CP91 PR and discard the CP91 branch; CP90 remains the last closed/effective Growth checkpoint.

After merge: revert only the CP91 bounded implementation/closure commits. Global CP58 and live-hold controls remain unaffected.

## Next exact action

Run exact-head PUBLIC PRESENCE OS CI for the CP91 candidate. If and only if CI is terminal `SUCCESS`, the candidate head remains stable, the PR is mergeable, and fresh `main` shows no conflicting `public-presence-os/**` drift, perform only the CP91 implementation merge plus post-merge readback. Do not start CP92 in the same unit.
