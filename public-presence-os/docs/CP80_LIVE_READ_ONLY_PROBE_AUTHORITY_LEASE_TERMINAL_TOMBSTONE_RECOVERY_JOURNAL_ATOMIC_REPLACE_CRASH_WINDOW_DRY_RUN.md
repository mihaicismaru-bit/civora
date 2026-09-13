# CP80 — Recovery Journal Atomic Replace Crash-Window Dry-Run v1

## Status

`PASS_CP80_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW_DRY_RUN_LOCAL_ONLY_NO_TORN_REPLACE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD`

Global control checkpoint remains **CP58**. CP80 is validation-only and does not grant runtime authority.

## Scope

CP80 advances exactly one bounded recovery-safety unit after CP79. It models an atomic replacement primitive over the 12 complete journal generations already validated by CP79 and verifies restart behavior across the bounded replacement crash window.

For deterministic fixture coverage, each CP79 generation at slot `i` is paired with the next complete generation at slot `(i + 1) mod 12`. This rotation exists only to provide 12 distinct baseline/candidate byte generations for storage-primitive validation. It does **not** assert that the paired transactions form a logical recovery-state transition.

Each pair is exercised at four restart windows:

1. `AFTER_STAGE_BEFORE_REPLACE`;
2. `REPLACE_BOUNDARY_BASELINE_WINS`;
3. `REPLACE_BOUNDARY_CANDIDATE_WINS`;
4. `AFTER_REPLACE_BEFORE_ACK`.

That produces **48 deterministic restart cases**.

## Atomic replace invariant

After any modeled crash/restart, the visible journal slot must contain exactly one complete generation:

- if the baseline generation remains visible, restart must deterministically replay the atomic replace;
- if the candidate generation is visible, restart must finalize acknowledgement idempotently;
- either route must converge to the exact candidate generation hash.

The following states are forbidden:

- absent journal visibility after restart;
- a strict prefix or other partial generation;
- bytes mixed from baseline and candidate generations;
- any digest/length that is neither the complete baseline nor complete candidate generation;
- runtime/storage mutation by the dry-run itself.

## Important implementation boundary

CP80 is a **contract simulation**, not evidence that a particular filesystem, database, kernel, rename primitive, `fsync` sequence, storage device or operating system provides crash-durable atomic replacement. No real storage operation is executed. A future implementation that performs storage writes must bind this contract to a concrete backend and independently verify that backend's durability semantics before any runtime authority can be granted.

## Safety boundary

The unit remains local, synthetic and zero-I/O. It performs no storage read/write, no runtime or registry mutation, no environment/keychain read, no secret resolution, no OAuth, no account lookup or connection, no network/social API call, no live probe, no publish attempt, no external write, no deploy and no paid-service use. The global kill switch remains engaged.

Active lanes remain exactly:

- Facebook Page
- Instagram Professional
- Threads

Deferred/excluded lanes remain unchanged: LinkedIn requires production API access; X remains excluded while its API is paid; Bluesky remains held until a local ROI test passes.

## Validation gates

CP80 passes only when all of the following remain true:

- CP79 contract and dry-run lineage are exact-bound;
- 12 distinct baseline/candidate complete-generation pairs are bound;
- all four crash windows are exercised for every pair;
- all 48 restart cases validate;
- restart visibility is exactly one complete generation;
- absent, partial and mixed generations remain forbidden;
- baseline winners deterministically replay replacement;
- candidate winners finalize acknowledgement idempotently;
- every restart converges to the candidate generation;
- zero I/O, zero storage/runtime mutation and no live authority remain true;
- CP58 remains the global checkpoint.

## Rollback and next bounded unit

Rollback target: **CP79**.

Next unit is named only and is not implemented by CP80:

`CP81_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_DRY_RUN`
