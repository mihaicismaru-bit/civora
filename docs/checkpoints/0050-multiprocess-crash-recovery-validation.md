# CIVORA Checkpoint 0050 — Multiprocess Crash/Recovery Validation

Status: CODE_COMPLETE_CI_PENDING

## Objective

Validate CIVORA persistence and recovery guarantees across independent OS processes rather than only multiple instances inside one Python process.

## Implemented validation

Added `tests/test_multiprocess_recovery.py` with four end-to-end scenarios:

1. process exits after `TransactionJournal.prepare()` but before review queue write; a later startup replays the durable transaction, writes the review item, commits the transaction, and returns runtime health to an allowed state;
2. process exits after review queue write but before journal commit; later startup replays idempotently and does not duplicate the queue item, including across a second independent startup;
3. twelve independent Python processes enqueue distinct review items concurrently into the same `ReviewQueue`; validation requires every update to survive;
4. twelve independent Python processes prepare distinct transactions concurrently into the same `TransactionJournal`; validation requires every record to survive.

The subprocess approach intentionally crosses interpreter/process boundaries and therefore exercises the file-locking and atomic read-modify-write implementation under real multi-process contention.

## Acceptance gates

- MULTIPROCESS_PREPARE_CRASH_RECOVERY: TEST_ADDED
- MULTIPROCESS_POST_QUEUE_PRECOMMIT_RECOVERY: TEST_ADDED
- MULTIPROCESS_REPLAY_IDEMPOTENCE: TEST_ADDED
- REVIEW_QUEUE_CROSS_PROCESS_NO_LOST_UPDATE: TEST_ADDED
- TRANSACTION_JOURNAL_CROSS_PROCESS_NO_LOST_UPDATE: TEST_ADDED
- PYTHON_3_11_3_12_3_13_CI: PENDING_CURRENT_HEAD
- WINDOWS_NATIVE: PENDING

## Remaining backlog

1. implicit Source Registry and Signal Store wiring into startup health composition;
2. Windows-native persistence/locking validation;
3. Fact Kernel implementation;
4. claim/evidence reconciliation;
5. production observability/operational CLI around health and dead-letter resolution.

## Blockers

No user credential or irreversible external action is required for the implementation in this checkpoint. Windows-native validation remains environment-dependent.

## Next canonical action

Wire Source Registry and Signal Store into the default `UnifiedHealthInspector` created by `Orchestrator`, then add integration tests proving corruption/recovery in those stores participates in the startup fail-closed decision.
