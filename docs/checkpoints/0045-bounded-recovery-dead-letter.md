# CIVORA Checkpoint 0045 — Bounded Recovery and Dead-Letter Transactions

Status: CODE_COMPLETE_CI_PENDING

## Objective

Prevent permanently unrecoverable transactions from remaining forever in `prepared` state and being replayed on every orchestrator startup.

## Implemented

- Added durable transaction state `dead_letter`.
- Added configurable `max_recovery_attempts` to `TransactionJournal` with a safe default of 3.
- Recovery failures increment `recovery_attempts` atomically and persist `last_error`.
- A transaction reaching the configured retry bound transitions atomically from `prepared` to `dead_letter`.
- Dead-letter records are excluded from future automatic replay.
- Added `dead_letters()` inspection API.
- Unified health reporting now includes `dead_letter_count`.
- Presence of one or more dead-letter transactions marks the transaction journal `degraded` and therefore blocks orchestrator startup through the existing health gate.

## Validation added

- bounded retry transitions to `dead_letter` after the configured attempt limit;
- dead-letter state persists across journal re-instantiation;
- dead-letter transaction is not replayed again;
- invalid retry bounds are rejected;
- health report exposes dead-letter count and degraded status.

## Completed gates

- BOUNDED_TRANSACTION_RECOVERY: PASS_IMPLEMENTATION_REVIEW
- DURABLE_DEAD_LETTER_STATE: PASS_IMPLEMENTATION_REVIEW
- DEAD_LETTER_REPLAY_SUPPRESSION: PASS_IMPLEMENTATION_REVIEW
- DEAD_LETTER_HEALTH_VISIBILITY: PASS_IMPLEMENTATION_REVIEW
- FAIL_CLOSED_STARTUP_ON_DEAD_LETTER: INHERITED_FROM_STARTUP_HEALTH_GATE
- PYTHON_3_11_3_12_3_13_CI: PENDING_CURRENT_HEAD
- WINDOWS_NATIVE_VALIDATION: PENDING

## Remaining backlog

1. Add explicit dead-letter resolution/requeue workflow with audited operator action.
2. Add deduplication/coalescing for repeated recovery health events.
3. Add multiprocess end-to-end crash/recovery tests for story-to-review.
4. Wire Source Registry and Signal Store into default Orchestrator health composition where runtime paths are available.
5. Add Windows-native validation.
6. Begin Fact Kernel and claim/evidence reconciliation implementation.

## Blockers

- Current head requires GitHub Actions validation before this checkpoint can be marked CLOSED_VALIDATED.
- Windows-native behavior remains unvalidated because no Windows runner result has yet been recorded.

## Next action

Implement an audited dead-letter resolution API supporting explicit `requeue` and `abort` transitions without silently discarding failed work, then validate it through the recovery ledger and startup health gate.
