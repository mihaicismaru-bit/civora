# CP75 — Live Read-Only Probe Authority Lease Terminal Tombstone Recovery Idempotency + Rollback Dry-Run v1

## Status

`PASS_CP75_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_DRY_RUN_LOCAL_ONLY_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD`

## Scope

CP75 adds one bounded recovery-safety unit after CP74. It takes each of the four synthetic CP74 terminal-tombstone recovery cases and replays the same simulated restore twice from the same canonical baseline. The two applications must compile to identical proposal and result hashes, must create no duplicate recovery effect, and must remain storage-write-free.

It then performs a simulated rollback for each case. The rollback result must reproduce the exact pre-recovery observed baseline: `null` for the missing-tombstone cases and the exact synthetic corruption hash for the corrupted-tombstone cases.

The unit is local-only, deterministic, canonical-JSON/SHA-256 bound and zero-I/O. It performs no storage restore, network request, account lookup, OAuth, live probe, publication, deploy or control-plane promotion.

## Validation cases

1. `EXPIRY_PATH / MISSING_TOMBSTONE`
2. `EXPIRY_PATH / CORRUPTED_TOMBSTONE`
3. `REVOCATION_PATH / MISSING_TOMBSTONE`
4. `REVOCATION_PATH / CORRUPTED_TOMBSTONE`

For every case, the first and second simulated recovery proposals must be identical, the first and second simulated recovery results must be identical, no duplicate effect may be observed, and the simulated rollback hash must equal the original baseline snapshot hash.

## Fail-closed guarantees

- Exact CP74 contract and CP74 dry-run binding is required.
- Exact lease binding is required.
- Recovery replay must be deterministic and idempotent.
- Duplicate recovery effects are forbidden.
- Rollback must exactly reproduce the pre-recovery baseline snapshot.
- Rollback occurs only in the simulated path after a simulated apply.
- Any storage write or runtime mutation is rejected.
- Only `GET` remains structurally allowlisted.
- Facebook Page, Instagram Professional and Threads remain the only active lanes.
- LinkedIn remains `HOLD_UNTIL_PRODUCTION_API_ACCESS`.
- X remains `EXCLUDED_WHILE_API_IS_PAID`.
- Bluesky remains `HOLD_UNTIL_LOCAL_ROI_TEST_PASSES`.
- Global kill switch remains engaged.
- Global control checkpoint remains CP58.

## Dry-run outcome

A PASS means only:

`SIMULATED_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_PASS_NO_DUPLICATE_EFFECT_NO_STORAGE_WRITE_NO_AUTHORITY`

It does not grant, activate or imply live authority.

## Rollback

Rollback target: CP74. Remove the CP75 policy/engine/tests/doc, remove M44 from the module registry, and remove the CP75 product-layout entries from `control.py`. No external recovery is required because CP75 produces no external social/runtime side effects and performs no storage mutation.

## Next unit

`CP76 — LIVE READ-ONLY PROBE AUTHORITY LEASE TERMINAL TOMBSTONE RECOVERY CRASH CONSISTENCY DRY-RUN v1`

CP76 is named only here and is not implemented by CP75.
