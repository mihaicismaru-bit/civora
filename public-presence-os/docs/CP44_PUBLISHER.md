# CP44 — M09 PUBLISHER MINIMAL EXECUTABLE SLICE + LOCAL DRY-RUN PUBLISH RECEIPT v1

## Decision

`PASS_M09_EXECUTABLE / HOLD_PILOT_M10_M14_GAPS`

## Scope

M09 is a deterministic local-only dry-run publisher. It consumes only an exact M08 `LocalOutboxItem` that is hash-valid, on an active platform, `LOCAL_OUTBOX_ONLY`, `QUEUED_LOCAL`, and `publisher_input_ready=true`.

## Contract

- Active platforms remain exactly Facebook Page, Instagram Professional and Threads.
- LinkedIn remains `PRODUCTION_API_ACCESS_REQUIRED`.
- X remains `EXCLUDED_WHILE_API_PAID`.
- Bluesky remains `HOLD_ROI`.
- M08 item bytes are revalidated before every local dry-run record.
- Caller `request_id` plus exact attempt timestamp provides deterministic retry/idempotency.
- Exact retry returns the same receipt and does not duplicate the event log.
- Request-ID payload drift fails closed.
- One outbox item may create at most one dry-run publisher receipt.
- Input snapshots, publisher receipts and attempt events are append-only in local SQLite.
- The only CP44 publisher event is `DRY_RUN_ATTEMPT_RECORDED` with outcome `NOT_DELIVERED_LOCAL_DRY_RUN`.
- M09 contains no HTTP/network client path and performs no API call.

## Truth contract

Every CP44 receipt is explicit that:

- `execution_mode=LOCAL_DRY_RUN`;
- `network_attempted=false`;
- `external_write_performed=false`;
- `account_connected=false`;
- `delivered=false`;
- `external_post_id=null`;
- `publish_authority=false`;
- `network_authority=false`;
- `account_connection_authority=false`;
- `deploy_authority=false`.

`analytics_input_ready=true` means only that the exact local receipt can be consumed by the later local M10 Analytics slice. It does not assert delivery, reach, impressions, engagement, external post creation, or any remote state.

## Authority boundary

M09 has only local dry-run publisher authority. It has no external publisher authority, public-publish authority, network authority, real-account authority or deploy authority. The global kill switch remains engaged.

## Persistence

Local SQLite tables:

- `publisher_outbox_inputs` — immutable exact M08 item snapshots;
- `dry_run_publish_receipts` — one append-only truth-bound receipt per outbox item;
- `publish_attempt_events` — append-only local attempt event log.

No credentials, tokens, real accounts, external post IDs or remote delivery claims are stored.

## Pilot state

After CP44 the remaining executable-source gaps are M10 Analytics, M11 Learning and M14 Experiments. Golden-path pilot readiness remains fail-closed until those modules are reimplemented and the complete synthetic rehearsal passes.

The historical CP29 exact-font-hash blocker remains unchanged: `HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED / HOLD_IDENTITY_EQUIVALENCE`.

## Next dependency

CP45 — M10 ANALYTICS MINIMAL EXECUTABLE SLICE + LOCAL RECEIPT TELEMETRY v1. It may consume only exact M09 local receipts and must not introduce external analytics, network, account or public-publish authority.
