# CP81 — Recovery Journal Atomic Replace Retry Idempotency Dry-Run v1

## Status

`PASS_CP81_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_DRY_RUN_LOCAL_ONLY_EXACTLY_ONCE_ACK_NO_DUPLICATE_REPLACE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD`

Global control checkpoint remains **CP58**. CP81 is validation-only and does not grant runtime authority.

## Scope

CP81 advances exactly one bounded recovery-safety unit after CP80. It consumes all **48** synthetic crash/restart cases already validated by CP80 and verifies that repeatedly invoking recovery is idempotent.

Each CP80 case is replayed through four deterministic recovery invocations, producing **192 observations**.

## Retry-idempotency invariant

After the first recovery invocation, the visible journal generation must be the exact CP80 candidate generation and its SHA-256 must remain unchanged for every later retry.

For a CP80 case where the baseline generation remained visible after the modeled crash:

1. recovery invocation 1 may replay the atomic replace exactly once;
2. recovery invocation 2 finalizes the synthetic acknowledgement exactly once;
3. invocations 3 and 4 must be no-ops.

For a CP80 case where the candidate generation was already visible:

1. recovery invocation 1 finalizes the synthetic acknowledgement exactly once;
2. invocations 2–4 must be no-ops;
3. the replace operation must never be replayed.

Across either route:

- acknowledgement transition count must saturate at exactly one;
- replace replay count may be one only for baseline-visible parents, otherwise zero;
- duplicate acknowledgements are forbidden;
- duplicate replace replays are forbidden;
- terminal transaction resurrection is forbidden;
- post-ack retries must be deterministic no-ops;
- every visible digest must remain the exact CP80 candidate digest.

## Important implementation boundary

CP81 is a **contract simulation**. It does not perform a real retry loop against a filesystem, database, queue, lock manager or process supervisor. It does not prove that a concrete storage backend supplies exactly-once effects. Any future storage-writing implementation must bind this contract to backend-specific transactional and durability semantics and validate those semantics independently.

## Safety boundary

The unit remains local, synthetic and zero-I/O. It performs no storage read/write, no runtime or registry mutation, no environment/keychain read, no secret resolution, no OAuth, no account lookup or connection, no network/social API call, no live probe, no publish attempt, no external write, no deploy and no paid-service use. The global kill switch remains engaged.

Active lanes remain exactly:

- Facebook Page
- Instagram Professional
- Threads

Deferred/excluded lanes remain unchanged: LinkedIn requires production API access; X remains excluded while its API is paid; Bluesky remains held until a local ROI test passes.

## Validation gates

CP81 passes only when all of the following remain true:

- CP80 contract, dry-run and lease lineage are exact-bound;
- all 48 CP80 parent crash cases are covered;
- four recovery invocations are modeled for every parent case;
- all 192 observations validate;
- candidate visibility/hash is stable after first recovery;
- baseline-visible cases replay replace at most once;
- candidate-visible cases never replay replace;
- acknowledgement transitions exactly once;
- post-ack retries are no-ops;
- duplicate ack, duplicate replace and transaction resurrection remain forbidden;
- zero I/O, zero storage/runtime mutation and no live authority remain true;
- CP58 remains the global checkpoint.

## Rollback and next bounded unit

Rollback target: **CP80**.

Next unit is named only and is not implemented by CP81:

`CP82_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_EXHAUSTION_FAIL_CLOSED_DRY_RUN`
