# CP74 — Live Read-Only Probe Authority Lease Terminal Tombstone Rebuild + Recovery Dry-Run v1

## Status

`PASS_CP74_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_DRY_RUN_LOCAL_ONLY_EXACT_REBUILD_NO_RUNTIME_AUTHORITY_LIVE_HOLD`

## Scope

CP74 adds one bounded recovery unit after CP73. It simulates loss and corruption of the synthetic terminal tombstones for both the expiry and revocation paths, then rebuilds each tombstone exclusively from the CP73 terminal receipt ledger.

The recovery path is local-only, deterministic, canonical-JSON/SHA-256 bound and zero-I/O. It performs no storage restore, no network request, no account lookup, no OAuth, no live probe, no publication, no deploy and no control-plane promotion.

## Recovery cases

1. `EXPIRY_PATH / MISSING_TOMBSTONE`
2. `EXPIRY_PATH / CORRUPTED_TOMBSTONE`
3. `REVOCATION_PATH / MISSING_TOMBSTONE`
4. `REVOCATION_PATH / CORRUPTED_TOMBSTONE`

For every case, the rebuilt tombstone must reproduce the original CP73 tombstone byte-for-byte at the canonical object level, including its deterministic ID and SHA-256 digest.

## Fail-closed guarantees

- Exact CP73 contract and dry-run binding is required.
- Recovery uses the CP73 ledger only; it cannot trust a missing/corrupted tombstone as source truth.
- Exactly one accepted terminal ledger entry is required per scenario.
- Missing and corrupted tombstones are both exercised.
- Any rebuilt tombstone that differs from the original canonical CP73 tombstone is rejected.
- Any simulated storage write or runtime mutation is rejected.
- Only `GET` remains structurally allowlisted.
- Facebook Page, Instagram Professional and Threads remain the only active lanes.
- LinkedIn remains `HOLD_UNTIL_PRODUCTION_API_ACCESS`.
- X remains `EXCLUDED_WHILE_API_IS_PAID`.
- Bluesky remains `HOLD_UNTIL_LOCAL_ROI_TEST_PASSES`.
- Global kill switch remains engaged.
- Global control checkpoint remains CP58.

## Recovery outcome

A PASS means only:

`SIMULATED_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_PASS_EXACT_REBUILD_NO_STORAGE_WRITE_NO_AUTHORITY`

It does not grant or imply live authority.

## Rollback

Rollback target: CP73. Remove the CP74 policy/engine/tests/doc, remove M43 from the module registry, and remove the CP74 product-layout entries from `control.py`. No external recovery is required because CP74 produces no external side effects.

## Next unit

`CP75 — LIVE READ-ONLY PROBE AUTHORITY LEASE TERMINAL TOMBSTONE RECOVERY IDEMPOTENCY + ROLLBACK DRY-RUN v1`

CP75 is named only here and is not implemented by CP74.
