# CP43 — M08 QUEUE MINIMAL EXECUTABLE SLICE + LOCAL APPROVAL-BOUND OUTBOX v1

## Decision

`PASS_M08_EXECUTABLE / HOLD_PILOT_M09_M14_GAPS`

## Scope

M08 is a deterministic, local-only SQLite outbox. It consumes only an exact M12 `ApprovalReviewReceipt` that is hash-valid, bound to an immutable approval event, `APPROVED_LOCAL`, `qa_verdict=PASS`, has zero QA HOLDs, and has both `local_approval_complete=true` and `queue_input_ready=true`.

## Contract

- Active platforms remain exactly Facebook Page, Instagram Professional and Threads.
- LinkedIn remains `PRODUCTION_API_ACCESS_REQUIRED`.
- X remains `EXCLUDED_WHILE_API_PAID`.
- Bluesky remains `HOLD_ROI`.
- Approval receipt bytes are revalidated before enqueue.
- One exact approval receipt may create at most one outbox item.
- Caller `request_id` plus exact enqueue timestamp provides retry/idempotency; exact retry returns the same item.
- Reusing a request ID with drift fails closed.
- Re-enqueueing an already-bound receipt with a new request ID fails closed.
- Approval receipts, outbox items and queue events are append-only in SQLite.
- The only CP43 event is `ENQUEUE_LOCAL`; no publisher attempt or network request exists in this module.
- Queue items are `publisher_input_ready=true` only for the later local/dry-run M09 contract. They are always `public_publish_eligible=false`.

## Authority boundary

M08 has local queue authority only. It has no publisher, public-publish, network, real-account-connection or deploy authority. It performs no external writes and no network delivery.

## Persistence

Local SQLite tables:

- `approval_receipts` — exact M12 receipt registry, immutable;
- `outbox_items` — one append-only item per approval receipt;
- `queue_events` — append-only local event log.

No credentials, tokens, real accounts or remote state are stored.

## Pilot state

After CP43 the remaining executable-source gaps are M09 Publisher, M10 Analytics, M11 Learning and M14 Experiments. Golden-path pilot readiness remains fail-closed until those modules are reimplemented and the full rehearsal passes.

The historical CP29 exact-font-hash blocker remains unchanged: `HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED / HOLD_IDENTITY_EQUIVALENCE`.

## Next dependency

CP44 — M09 PUBLISHER MINIMAL EXECUTABLE SLICE + LOCAL DRY-RUN PUBLISH RECEIPT v1. No network/account/public publishing authority may be introduced before pilot validation.
