# VÂLCEA CLAR — System Audit & Cleanup Baseline

Date: 2026-08-22
Branch: `cleanup/valcea-runtime-simplification-20260822`

## Canonical target architecture

`Sources → Fact Kernel → Live Newsroom → Canonical Export → Social Engine`

GitHub Actions is the scheduler/execution environment, repository state is durable truth, and ChatGPT is an operator console only. Diagnostics and compatibility checks do not own production state; recovery and remote account/profile mutations are explicit-only.

## Cleanup result — Phases 1–4

Original audit:
- 86 VÂLCEA workflow files;
- 29 unregistered background writers;
- 2 background dispatchers.

Strict Phase-4 audit on PR merge-ref against current `main`:
- 51 VÂLCEA workflow files;
- 21 registered canonical jobs, all present;
- 0 unregistered autonomous writers;
- 0 unregistered background writers;
- 0 unregistered push-only writers;
- 0 unregistered autonomous/background dispatchers;
- 0 unregistered autonomous/background observers;
- 30 remaining noncanonical workflows are manual/PR-only QA, diagnostics, recovery or explicit maintenance;
- 0 retired-but-present executable workflows;
- `strict_blockers: []`.

## Consolidation completed

- duplicate Publication Reconcile and redundant dispatch loops removed;
- fact mutation consolidated behind Fact Kernel orchestration;
- Signal Radar + strict Primary Signal Verifier + bounded discovery consolidated;
- cultural and identity monitoring consolidated;
- Premium/Rich/Gambling/legal/news-index presentation consolidated into canonical export;
- manual-social, one-shot Arutela/CET republish and historical bridge patch paths removed;
- diagnostics converted to read-only/artifact output;
- recovery/account/profile mutation converted to explicit-only;
- duplicate presentation/social preview QA consolidated;
- all remaining noncanonical push-only observers demoted to PR/manual acceptance in Phase 4;
- narrow duplicate HTTP observer demoted to manual diagnostic; Public HTTP Health remains canonical;
- stale HTTP workflow-run listeners reconciled to Live Newsroom.

## Phase-4 defects found and fixed

- Photo Atlas PR acceptance now regenerates deterministically instead of requiring stale committed generated state.
- `telegram_profile_identity_deploy.py` now imports `tempfile`, fixing its deployer self-test.
- Profile Presence no longer incorrectly requires textual equality between profile `role` and native editorial `product_role`; they are separate semantic layers and the validator now requires the appropriate declared native product role instead.

## Reconciliation with main

The cleanup branch remains historically diverged because production continued to persist generated editorial/runtime/state commits while cleanup was developed. The behind-side drift is dominated by generated state rather than competing automation architecture.

No forced rebase is used. GitHub PR checks validate the synthetic merge ref combining current `main` with the cleanup branch. Phase-4 functional head `f8c98b6742e6c5e5e8ddfd778d9e32491eec4c7a` passed the strict ownership and core acceptance gates against current `main`. Subsequent commits only update this audit document.

## Gate

PR remains DRAFT. Do not merge without explicit owner approval.
