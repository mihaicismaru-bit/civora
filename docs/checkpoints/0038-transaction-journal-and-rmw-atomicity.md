# CIVORA Checkpoint 0038 — Transaction journal and read-modify-write atomicity

Status: `CODE_COMPLETE_CI_PENDING`

## Scope

This checkpoint introduces the durable write-ahead transaction journal required for coordinated multi-store operations and closes a concurrency defect discovered during implementation review.

## Implemented

- `TransactionJournal` with durable `prepared`, `committed`, and `aborted` states.
- at-least-once replay of prepared transactions through idempotent recovery handlers.
- persisted recovery attempt counters and last-error diagnostics.
- backup recovery and checksum validation inherited from `AtomicJsonStore`.
- `AtomicJsonStore.update()` for one-lock read-modify-write cycles.
- journal state transitions migrated to `AtomicJsonStore.update()` so stale process-local snapshots cannot silently overwrite another writer's records.
- regression coverage for two independently loaded journal instances writing sequentially to the same store.

## Important finding

Previous cross-process locking protected `load()` and `save()` individually but did not serialize the complete component-level read-modify-write cycle. A process could load state, another process could commit a change, and the first process could later save its stale snapshot. The new `AtomicJsonStore.update()` primitive closes this lost-update class for consumers that use it.

`SourceRegistry`, `ReviewQueue`, and `SignalStore` still need to migrate their component mutations to this primitive before their read-modify-write operations can be considered concurrency-safe end-to-end.

## Gates

- durable transaction preparation: PASS_IMPLEMENTATION_REVIEW
- durable transaction terminal states: PASS_IMPLEMENTATION_REVIEW
- deterministic prepared-record discovery: PASS_IMPLEMENTATION_REVIEW
- failed recovery observability: PASS_IMPLEMENTATION_REVIEW
- atomic store read-modify-write primitive: PASS_IMPLEMENTATION_REVIEW
- stale-writer journal regression coverage: ADDED_PENDING_EXECUTION
- full automated suite: PENDING_CI
- native Windows validation: PENDING

## Blockers

GitHub Actions has not emitted a workflow run for the current head. Network access from the local execution container is unavailable, so the repository cannot be cloned there for an independent full-suite execution during this run.

## Next action

Migrate `SourceRegistry`, `ReviewQueue`, and `SignalStore` mutations to `AtomicJsonStore.update()`, then add stale-writer regression tests for each. After that, integrate the transaction journal into the story-to-review transition and implement restart replay.
