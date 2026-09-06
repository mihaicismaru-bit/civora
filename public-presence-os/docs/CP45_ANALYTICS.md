# CP45 — M10 ANALYTICS MINIMAL EXECUTABLE SLICE + LOCAL RECEIPT TELEMETRY v1

## Decision

`PASS_M10_EXECUTABLE / HOLD_PILOT_M11_M14_GAPS`

## Scope

M10 is a deterministic local analytics slice bound only to exact M09 `DryRunPublishReceipt` objects. It records what the local dry-run publisher actually proved and refuses to manufacture remote performance evidence.

This clean-room implementation consumes the validated CP22 analytics canon as design evidence while narrowing execution to the current CP44 truth boundary: there are no real account connections, no external post IDs and no delivered posts, so external analytics are `NOT_CONNECTED`, not zero.

## Contract

- Active platforms remain exactly Facebook Page, Instagram Professional and Threads.
- LinkedIn remains `PRODUCTION_API_ACCESS_REQUIRED`.
- X remains `EXCLUDED_WHILE_API_PAID`.
- Bluesky remains `HOLD_ROI`.
- Every M09 receipt is fully revalidated before analytics ingest.
- The exact M09 receipt SHA-256 is the analytics evidence binding.
- `observed_at_utc` cannot precede the local publisher attempt.
- Caller `request_id` plus exact receipt and observation timestamp provide deterministic retry/idempotency.
- Exact retry returns the same snapshot and does not duplicate the event log.
- Request-ID payload drift fails closed.
- One M09 receipt may create at most one local analytics snapshot.

## Remote metric truth

The CP22 rule `null != zero` remains binding.

Because CP45 performs no remote analytics lookup, the following fields exist only as an explicit unknown/not-connected ontology: VIEWS, REACH, IMPRESSIONS, LIKES, REACTIONS, COMMENTS, REPLIES, SHARES, REPOSTS, QUOTES, SAVES, CLICKS and CONVERSIONS.

For every one of them:

- `availability=NOT_CONNECTED`;
- `value=null`;
- `source_metric_name=null`.

CP45 does not compute engagement, click or conversion rates. `derived_metrics_state=NOT_COMPUTABLE_NOT_CONNECTED` and `performance_evidence_ready=false`.

## Learning boundary

`learning_input_ready=true` means only that M11 may consume the exact local operational telemetry record. The permitted handoff scope is `LOCAL_OPERATIONAL_TELEMETRY_ONLY`.

CP45 grants no performance-learning authority, learning feedback write, ranking-weight mutation, content-policy mutation, scheduling mutation or automatic strategy change.

## Persistence

Local SQLite tables:

- `analytics_receipt_inputs` — immutable exact M09 receipt snapshots;
- `analytics_snapshots` — one append-only local analytics snapshot per receipt;
- `analytics_events` — append-only event log.

All three tables reject UPDATE and DELETE.

## Privacy

CP45 is aggregate content-level only. It contains no person-level identifiers, follower profiles, demographics or sensitive audience dimensions.

## Authority boundary

M10 has only local analytics authority. It has no external analytics, network, real-account, learning-write, strategy-mutation, public-publish or deploy authority. The global kill switch remains engaged.

## Validation target

- clean M09 receipt -> receipt-bound local analytics snapshot;
- all three active lanes accepted;
- all remote metrics remain `NOT_CONNECTED/null`, never numeric zero;
- tampered or falsely delivered M09 receipts fail closed;
- observation-time ordering is enforced;
- retry/idempotency and duplicate prevention pass;
- SQLite snapshot/event ledgers are append-only;
- static source scan finds no network/live-analytics client;
- synthetic rehearsal recognizes M10 as executable while M11 and M14 remain HOLD.

## Blockers / deferred

Still OFF/deferred: real Meta analytics endpoint execution, OAuth/token resolution, live post/account IDs, real insight permissions, real metric availability, pagination, account-level analytics, demographics, webhooks, performance learning, strategy mutation and deploy.

Historical visual blocker remains unchanged: `HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED / HOLD_IDENTITY_EQUIVALENCE`.

## Changelog

- Added `config/analytics_policy.json`.
- Added `src/public_presence_os/analytics.py`.
- Added `tests/test_cp45_analytics.py`.
- Added receipt-bound local analytics SQLite persistence and append-only event log.
- Promoted M10 from historical `SYNTHETIC_ONLY` evidence to `CP45_MINIMAL_EXECUTABLE_SLICE`.
- Advanced M11 Learning to NEXT.
- Preserved zero network/account/publish/deploy authority.

## Rollback

Rollback authority is the pre-CP45 exact main head from which the CP45 branch was created. Reverting the CP45 commit restores M10 to historical-only `SYNTHETIC_ONLY` without affecting M01–M09, M12, M13, the global kill switch or any external account because CP45 performs no external action.

## Next dependency

CP46 — M11 LEARNING MINIMAL EXECUTABLE SLICE + LOCAL SHADOW LEARNING LEDGER v1. It may consume only exact CP45 analytics snapshots and must preserve `NO_AUTO_MUTATION`, especially while performance evidence is unavailable.
