# CP73 — Live Read-Only Probe Authority Lease Terminal Tombstone Reconciliation Dry-Run v1

## Purpose

CP73 is one bounded, local-only control-plane unit after CP72. It reconciles a synthetic terminal lease tombstone with a deterministic synthetic receipt ledger for the two independent CP72 terminal fixtures: expiry and explicit revocation.

CP73 does **not** activate runtime authority. It does not connect a social account, resolve a secret, read ENV/keychain material, perform OAuth, execute a Meta request, publish, write externally, promote the control plane, deploy, or use a paid service.

## Canonical scope

Active lanes remain exactly:

- `FACEBOOK_PAGE`
- `INSTAGRAM_PROFESSIONAL`
- `THREADS`

Deferred/excluded lanes remain unchanged:

- `LINKEDIN` — `HOLD_UNTIL_PRODUCTION_API_ACCESS`
- `X` — `EXCLUDED_WHILE_API_IS_PAID`
- `BLUESKY` — `HOLD_UNTIL_LOCAL_ROI_TEST_PASSES`

The global control checkpoint intentionally remains `CP58` and the global kill switch remains engaged. Method scope remains `GET` only.

## Parent binding

CP73 is exact-bound to the current CP72 contract, CP72 dry-run fingerprint and synthetic lease ID/hash. The CP72 dry-run is deterministically rebuilt from the CP71 synthetic fixture before reconciliation. Parent, policy, lane, receipt, ledger, tombstone or digest drift fails closed.

All local evidence objects use canonical JSON plus SHA-256 binding.

## Synthetic receipt ledger

Each terminal scenario has exactly three ledger entries:

1. terminal receipt — `ACCEPTED` exactly once;
2. exact terminal receipt replay — `REJECTED`;
3. stale pre-terminal `ACTIVE` receipt presented at the terminal boundary — `REJECTED`.

The expiry and revocation paths remain independent fixtures; CP73 does not claim both terminal events occur in one real lease lifecycle.

A valid ledger has exactly one accepted terminal entry and no accepted `ACTIVE` entry at or after terminal time.

## Terminal tombstone

For each scenario CP73 creates an immutable synthetic tombstone bound to:

- lease ID/hash;
- terminal state and terminal time;
- terminal receipt ID/hash;
- accepted terminal ledger-entry ID/hash;
- CP72 dry-run ID/hash.

The tombstone must exactly match the single accepted terminal ledger entry. A conflicting terminal state, altered receipt binding, altered ledger binding, changed parent fingerprint or changed tombstone digest fails closed.

## Ordered validation phases

1. `CP72_PARENT_EXACT_BOUND`
2. `EXPIRY_LEDGER_TERMINAL_UNIQUE`
3. `EXPIRY_TOMBSTONE_EXACT_MATCH`
4. `REVOCATION_LEDGER_TERMINAL_UNIQUE`
5. `REVOCATION_TOMBSTONE_EXACT_MATCH`
6. `REPLAY_AND_STALE_REJECTIONS_PRESERVED`
7. `CONFLICTING_TERMINAL_STATE_REJECTED`
8. `POST_TERMINAL_ACTIVE_ACCEPTANCE_REJECTED`
9. `TERMINAL_TOMBSTONE_IMMUTABLE_HASH_BOUND`
10. `ZERO_IO_OBSERVED`
11. `AUTHORITY_REMAINS_INACTIVE`

A PASS is emitted only when every phase is satisfied.

## Fail-closed invariants

CP73 rejects:

- duplicate accepted terminal entries;
- a tombstone terminal state that differs from the accepted terminal ledger entry;
- receipt/hash/ledger binding tampering;
- loss of CP72 replay or stale-receipt rejection evidence;
- accepted `ACTIVE` state at or after terminal time;
- any weakening of immutable tombstone, zero-I/O, CP72 binding, `GET`-only or canonical lane guards;
- any attempt to convert structural reconciliation into runtime authority.

A structurally valid CP73 PASS means only:

`SIMULATED_TERMINAL_TOMBSTONE_RECONCILIATION_PASS_LEDGER_CONSISTENT_NO_AUTHORITY_NO_MUTATION`

It is never interpretable as live authorization, runtime authority, account connectivity or permission to execute a live read-only probe.

## Blockers retained

- `HOLD_REAL_EXTERNAL_AUTHORIZATION_RECEIPT_NOT_INGESTED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED`
- `HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED`
- `HOLD_PILOT_PUBLISH_NOT_AUTHORIZED`
- `HOLD_CP73_TOMBSTONE_LEDGER_SYNTHETIC_ONLY`
- `HOLD_CP73_RECONCILIATION_PASS_IS_NOT_RUNTIME_AUTHORITY`

## Rollback

Rollback target is CP72. Remove the CP73 policy, engine, tests, documentation and M42 registry row, and remove the four CP73 expected-file entries from `control.py`. No external recovery is necessary because CP73 performs no external effects.

## Next granular unit

`CP74_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_DRY_RUN`

CP74 is named only and is not implemented by CP73.
