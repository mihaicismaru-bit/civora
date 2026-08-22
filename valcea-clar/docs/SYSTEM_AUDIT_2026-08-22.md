# VÂLCEA CLAR — System Audit & Cleanup Baseline

Date: 2026-08-22
Branch: `cleanup/valcea-runtime-simplification-20260822`
Baseline main: `234693694f6f4663ae57ed477f7e07f2da4dc08b`

## Executive finding

The public site is currently healthy, but the repository has accumulated multiple overlapping control planes. The canonical automation registry declares 10 site-engine jobs, while many additional VÂLCEA CLAR workflows remain executable and several of them write directly to the same `valcea-clar/site/runtime` projection or related canonical state.

The dominant failure mode is not missing capability. It is excessive orchestration: multiple workflows rebuild, enrich, patch, reconcile, validate and persist the same public surface. This creates commit churn, trigger cascades, ping-pong rewrites, stale compatibility layers and makes it difficult to identify the true publication owner.

## Canonical target architecture

There must be exactly one canonical public-runtime writer:

`SOURCE DISCOVERY -> VERIFIED FACTS -> EDITORIAL WRITER -> INTEGRITY GATE -> LIVE NEWSROOM -> SITE RENDER -> PUBLICATION EVENT -> SOCIAL DISTRIBUTION`

`Live Newsroom` owns publication state and `site/runtime`. All other capabilities are either:

1. upstream data producers that never write public runtime;
2. downstream distributors that consume a durable publication event;
3. read-only validators/health observers;
4. manual recovery tools that do not run on a clock;
5. archived/retired code.

## Confirmed structural defects

### P0 — Two publication engines

`.github/workflows/valcea-clar-newsroom-live.yml` polls every five minutes and is already the registered canonical writer.

`.github/workflows/valcea-clar-publication-reconcile.yml` also runs every five minutes, uses the same concurrency group, rebuilds the same editions/runtime, updates the same newsroom state and emits the same publication event. This is a duplicate publication engine disguised as reconciliation.

Action: remove autonomous triggers from Publication Reconcile. Keep reconciliation only as explicit/manual recovery if it remains necessary.

### P0 — Profile-link ping-pong writers

`Artist Story Links` and `Person Story Links` rewrite `live-feed.json` and article pages after the newsroom renderer. When linked to every newsroom completion they repeatedly re-apply secondary presentation state that the canonical renderer does not own.

Action: never subscribe profile linkers to the newsroom heartbeat. They may run only after their own verified profile graph changes, until profile linking is folded into the canonical renderer.

### P0 — Secondary presentation control plane

`valcea-clar-premium-presentation.yml` runs hourly, subscribes to `site/runtime/**`, then writes `site/runtime` again. This is a second presentation engine over the canonical newsroom renderer.

Action: migrate the desired UX rules into one canonical renderer, then retire the scheduled/push-driven Premium Presentation writer. Until migration, treat it as compatibility, not publication authority.

### P1 — Unregistered autonomous workflows

`valcea-clar/engine/automation_registry.json` declares 10 canonical jobs, but many other VÂLCEA CLAR workflows retain `schedule`, `workflow_run`, `push` and/or `contents: write` permissions.

The existing ownership validator validates registered jobs, but does not fail merely because an additional autonomous VÂLCEA CLAR workflow exists outside the registry.

Action: extend governance so every autonomous VÂLCEA CLAR workflow must be registered, explicitly manual/test-only, or retired.

### P1 — Runtime state committed as operational telemetry

Health receipts, monitor snapshots, generated presentation state and other frequently changing outputs are committed to `main`. These commits can cause further workflow evaluations and obscure meaningful editorial/code changes.

Action: keep only durable publication/editorial state in the repository. Move transient health/telemetry to GitHub status checks and workflow artifacts where possible.

### P1 — Direct bot writes to unprotected main

`main` is currently unprotected and multiple workflows use `contents: write` to commit directly to it.

Action: first establish a single-writer runtime design; then protect `main` and restrict code/config changes to reviewed PRs. Do not enable branch protection before the runtime-write migration is complete, because current production depends on direct bot writes.

### P2 — Historical/versioned implementation accumulation

The scripts directory contains several parallel generations and wrappers, including examples such as `*_v2.py`, `*_legacy.py`, multiple diagnostic/resolver variants, bridge patchers and overlapping presentation modules.

Action: do not delete by filename alone. Build an import/workflow reference map, then classify each file `CANONICAL`, `COMPATIBILITY`, `RECOVERY`, `TEST/DIAGNOSTIC`, or `UNREFERENCED`. Delete only the final class after exact-head validation.

## Cleanup sequence

### Phase A — Stop waste without changing product behavior

- remove Live Newsroom heartbeat trigger from person/artist linkers;
- remove autonomous Publication Reconcile loop;
- stop unregistered secondary workflows from running on clocks when they only maintain derived presentation;
- preserve manual dispatch for recovery where justified;
- keep Live Newsroom, source radar, canonical fact/editorial gates, editions recap, social distribution and quality/ownership gates.

### Phase B — One renderer

- merge durable reader-UX requirements from `public_ux_*`, profile linkers and rich-story patchers into the canonical story/site renderer;
- make renderer output deterministic and idempotent;
- eliminate post-render patch workflows.

### Phase C — State hygiene

- repository: durable facts, editorial decisions, publication ledger, configuration and source registry;
- GitHub Actions artifacts/status: health probes, transient diagnostics, run receipts, retry telemetry;
- no timestamp-only commit churn.

### Phase D — Dead-code removal

- generate reference map;
- archive/remove unreferenced v1/v2/legacy/diagnostic code;
- remove retired workflows from `.github/workflows` so they cannot execute;
- simplify tests around the canonical pipeline.

### Phase E — Protection and operating model

- protect `main` for code/config;
- allow only the canonical runtime writer to persist publication state through the chosen controlled mechanism;
- fail CI when an unregistered autonomous writer appears.

## Acceptance criteria

Cleanup is complete when:

- one workflow owns canonical publication/runtime writes;
- no secondary workflow is triggered by the newsroom solely to re-patch the same pages;
- reconciliation is recovery-only, not a second heartbeat;
- no unregistered scheduled VÂLCEA CLAR writer exists;
- health checks do not create unnecessary repository commits;
- site routes, article count, holds, source provenance, legal pages and social publication contract remain intact;
- exact-head CI and public HTTP acceptance are green before merge.
