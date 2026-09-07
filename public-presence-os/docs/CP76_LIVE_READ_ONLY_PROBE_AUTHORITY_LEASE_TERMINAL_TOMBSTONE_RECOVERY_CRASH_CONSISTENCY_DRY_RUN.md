# CP76 — Live Read-Only Probe Authority Lease Terminal Tombstone Recovery Crash Consistency Dry-Run v1

## Status

`PASS_CP76_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_DRY_RUN_LOCAL_ONLY_NO_TORN_STATE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD`

CP76 is one bounded, local-only continuation of CP75. It does not activate runtime authority and does not perform a live probe, network call, account connection, secret lookup, OAuth flow, publish action, storage write, external write, control-plane promotion, deployment, or paid-service call.

The global control checkpoint intentionally remains **CP58** and the global kill switch remains engaged.

## Scope

CP76 proves deterministic crash consistency for the synthetic CP75 terminal-tombstone recovery transaction. It is exact-bound to the CP75 contract, CP75 dry-run, and lease hashes. The only active platform lanes remain:

- `FACEBOOK_PAGE`
- `INSTAGRAM_PROFESSIONAL`
- `THREADS`

Deferred lane canon is unchanged: LinkedIn remains held until production API access, X remains excluded while its API is paid, and Bluesky remains held until a local ROI test passes.

## Crash model

Every one of the four CP75 recovery cases is exercised at exactly three bounded synthetic crash points, for 12 deterministic cases total:

1. `AFTER_PREPARE_BEFORE_STAGE`
2. `AFTER_STAGE_BEFORE_COMMIT_MARKER`
3. `AFTER_COMMIT_MARKER_BEFORE_ACK`

The four parent recovery cases are expiry/missing, expiry/corrupted, revocation/missing, and revocation/corrupted tombstones.

For pre-commit crashes, restart must discard incomplete synthetic state, return to the exact CP75 baseline where required, and replay the deterministic CP75 recovery. For a crash after the commit marker but before acknowledgement, restart must finalize the already committed synthetic result idempotently. Every path must converge to the exact CP75 `first_apply_result_hash` with exactly one recovery effect.

All prepare, staged, commit-marker, baseline, parent and restart evidence is canonical-JSON/SHA-256 bound. The journal is an in-memory synthetic model only; no persistent journal or storage mutation is permitted in CP76.

## Fail-closed invariants

CP76 rejects parent drift, baseline drift, missing/corrupt commit-marker shape, torn state, duplicate recovery effect, restart convergence drift, policy or lane weakening, storage mutation, runtime mutation, network enablement, account connection, publishing, external writes, deployment, control-plane promotion, authority activation, secret resolution, environment/keychain reads, OAuth and paid services.

The HTTP method allowlist remains `GET` only, but CP76 executes no HTTP traffic.

## Validation outcome

A valid dry-run returns:

`SIMULATED_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_PASS_NO_TORN_STATE_NO_DUPLICATE_EFFECT_NO_STORAGE_WRITE_NO_AUTHORITY`

This means only that the local synthetic crash model converges deterministically. It is not authorization to connect accounts or execute live traffic.

## Rollback

Rollback target: **CP75**. Remove M45 plus the CP76 policy, engine, tests and document entries. No runtime or external state needs reversal because CP76 performs no external or storage mutation.

## Next unit

`CP77_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION_DRY_RUN`

CP77 is named only here and is not implemented by CP76.
