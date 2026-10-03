# PUBLIC PRESENCE OS — META LIVE AUTONOMY CHECKPOINT

Date: 2026-10-03
Stage: `READY_FOR_READ_ONLY_REAL_CREDENTIALS`
Safety: `KILL_SWITCH=ENGAGED`, `LIVE_WRITE=OFF`, no external GREEN action, no owner write authority.

## Reconciled repository truth

- CP81–CP92 and the growth loop remain the canonical local implementation.
- S-A1 is the latest merged Meta checkpoint and verifies the intended Facebook Page, Instagram Professional account, Threads account, and Meta app without storing secrets.
- The unmerged S-A2.1–S-A2.7 successor stack was integrated rather than recreated. S-A2.7 contained a fixture identity defect; the fixture now uses the canonical verified IDs and all successor tests pass.
- The new live runtime extends S-A2 with secret-safe GET-only transport, real normalized event persistence, CP92 real-event shadow decisions, and a future controlled-write safety boundary. It does not grant external authority.

## Gap matrix

### EXISTS_AND_VERIFIED

- Deterministic editorial, rights/provenance, QA, approval, queue, dry-run publisher, analytics, learning, engagement, relationship, amplification, and scheduling modules through CP92.
- S-A1 Facebook Page `2816314015107071`, Instagram Professional `17841429701593250`, and Threads `28391623420464631` identity binding.
- S-A2 credential contract, normalized boundary, event cursor, observability, cross-lane coverage, atomic persistence, and stale-generation rejection.
- GET-only allowlisted Meta hosts, bounded retry, 429/5xx handling, response size bound, no token in URL for ordinary reads, and redacted operator output.
- SQLite WAL event log with provenance, network/object IDs, observed/fetched timestamps, content-fingerprint deduplication, and restart-safe cursors.
- Real-read event bridge to CP92, shadow decision/evaluation ledgers, permanent GREEN/AMBER/RED policy, and a hard 100-decision calibration floor.
- Controlled-write ledger requiring explicit durable authority, GREEN classification, unexpired approval, kill-switch checks, idempotency, pre-event, receipt, readback, and post-event.
- Local failure-soak coverage for authorization failure/expiry, 429/5xx-equivalent transport failure, timeout/ambiguous ACK, duplicate invocation, restart after an unconfirmed attempt, invalid payload response, missing rights evidence, readback failure, stale approval, kill switch before and mid-queue, and database contention.

### EXISTS_BUT_INCOMPLETE

- Exact live permission/scope readback: implemented boundary, not observed with current credentials.
- Page/Instagram/Threads insights: official capability recorded; exact live metric availability remains `UNKNOWN` until readback.
- Webhooks: operationally preferable for supported comment/reply changes, but no callback deployment or subscription receipt exists; status remains `HOLD`.
- Failure soak uses deterministic transport doubles. Live sandbox validation remains gated behind credentials and explicit write authorization.
- Dashboard integration remains the existing local approval surface; no new hosted service was introduced.

### MISSING

- A real read-only sync receipt from this runtime.
- Real shadow decisions and a statistically adequate sample of at least 100, unless actual account activity proves that unreasonable.
- Completed human calibration labels and an external action promoted to GREEN.
- A durable explicit owner authorization receipt for any social write.
- Limited-write receipt, controlled-autonomy soak evidence, and autonomous-production evidence.

### EXTERNAL_CONFIGURATION_REQUIRED

- Local secret provisioning for the Meta user credential and Threads user credential. A Page credential may be supplied or derived in memory from the accessible-Pages response.
- App-side read scopes needed for the selected live surfaces. Write scopes are not requested during read-only activation.
- Webhook callback/subscription configuration only if later justified and deploy gates pass.
- Explicit owner authorization after real shadow acceptance and calibration; this mission text is not treated as write authorization.

### UNSUPPORTED_BY_OFFICIAL_API

- Instagram generic public keyword/topic search and arbitrary broad third-party commenting are not used; they route to `MANUAL_ACTION_PACKET`.
- Facebook broad topic/hashtag discovery is not assumed.
- Facebook Page mention discovery and reaction publishing remain `CAPABILITY_UNVERIFIED` for the exact object/auth model and therefore cannot execute.
- Automated follow/unfollow, mass commenting, sensitive profiling, political microtargeting, synthetic conversation, and spam are RED regardless of future API capability.

## Capability truth

The machine-readable matrix is `config/meta_capability_matrix_live.json`. Its sources are Meta's official, verified Postman workspaces. Official support never implies that the current app token has the entitlement; live scope and object-level readback remain mandatory.

## Decisions

1. Use a Meta user credential to resolve accessible Pages and derive Page authority in memory; permit an explicit Page credential as an optional runtime override.
2. Use a separate Threads user credential because Threads authorization is a distinct flow and host.
3. Persist no raw Meta response. Only normalized, secret-free records cross the storage boundary.
4. Keep insights `UNKNOWN` until exact live metric readback; do not fabricate zeros.
5. Keep every external action AMBER until real calibration. Only `IGNORE` and `MANUAL_ACTION_PACKET` are currently GREEN because neither performs a social write.
6. Treat ambiguous external-write results as terminal HOLD. Never retry them blindly.

## Rollback

1. Set `KILL_SWITCH=true` and `LIVE_WRITE=false` in the local runtime environment.
2. Stop the scheduler/runtime process; do not delete event, decision, or write ledgers.
3. Preserve `var/meta-events.sqlite3`, `var/meta-shadow.sqlite3`, and any future controlled-write ledger as evidence.
4. Revert the application to the last green Git commit or archive this worktree. No remote deployment currently exists to roll back.
5. Run repository validation and read-only preflight before resuming.

## Current blocker

No Meta credential variables are present in the execution environment. Consequently no live API request, real observation, shadow sample, or social write was performed.
