# CIVORA Checkpoint 0039 — Story → Review transactional handoff

Status: `CODE_COMPLETE_VALIDATION_PENDING`

## Objective

Make the blocked-story handoff to the review queue recoverable across process interruption without losing or duplicating review work.

## Changes

- Added `ReviewQueue.enqueue_payload(...)` for idempotent replay from durable serialized transaction payloads.
- Strengthened review-queue validation so the stored story id must match the queue key.
- Integrated `TransactionJournal` into `Orchestrator` whenever a review queue is configured.
- Added write-ahead `prepare → enqueue → commit` handling for blocked stories.
- Added `recover_pending_transactions()` and replay of `story_to_review` transactions at the start of every orchestrator run.
- Unsupported transaction operations fail closed and remain prepared rather than being silently committed.

## Recovery semantics

The handoff has at-least-once replay semantics. `ReviewQueue.enqueue_payload` is idempotent by `story_id`, making both critical crash windows recoverable:

1. Crash after journal `prepare`, before review-queue write → replay writes the queue item and commits the transaction.
2. Crash after review-queue write, before journal `commit` → replay overwrites the same story id with the same durable payload and then commits, without creating a duplicate.

## Validation added

- Recovery from a prepared transaction with no queue write.
- Idempotent recovery when the queue write already happened but the transaction is still prepared.
- Existing stale-writer tests remain in place for SourceRegistry, SignalStore, ReviewQueue and TransactionJournal.

## Gates

- `STORY_TO_REVIEW_WRITE_AHEAD_JOURNAL`: PASS_IMPLEMENTATION_REVIEW
- `CRASH_RECOVERY_BEFORE_QUEUE_WRITE`: TEST_ADDED
- `CRASH_RECOVERY_AFTER_QUEUE_WRITE`: TEST_ADDED
- `REPLAY_IDEMPOTENCE`: PASS_IMPLEMENTATION_REVIEW
- `UNSUPPORTED_TRANSACTION_FAIL_CLOSED`: PASS_IMPLEMENTATION_REVIEW
- `FULL_AUTOMATED_SUITE`: PENDING_CI
- `WINDOWS_NATIVE_VALIDATION`: PENDING

## Remaining risk

Story checkpoint files in `Orchestrator.save_checkpoint()` are still written directly and are not yet checksum-protected or atomically replaced. They are the next persistence weakness to remove.

## Next action

Move story checkpoints to the common atomic persistence primitive, add restart/recovery tests for checkpoint corruption, then build a unified recovery/health report covering journals, queues and checkpoint stores.
