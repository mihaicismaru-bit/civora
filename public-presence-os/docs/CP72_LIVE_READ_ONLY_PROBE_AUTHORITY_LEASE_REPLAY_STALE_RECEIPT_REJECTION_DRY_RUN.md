# CP72 — Live Read-Only Probe Authority Lease Replay + Stale Receipt Rejection Dry-Run v1

## Purpose

CP72 is one bounded, local-only control-plane unit after CP71. It proves that a synthetic authority-lease terminal receipt can be accepted at most once and that neither an exact replay nor a stale pre-terminal `ACTIVE` receipt can resurrect the lease after expiry or explicit revocation.

CP72 does **not** activate runtime authority. It does not connect a social account, resolve a secret, read ENV/keychain material, perform OAuth, execute a Meta request, publish, write externally, promote the control plane, deploy, or use a paid service.

## Canonical scope

Active lanes remain exactly:

- `FACEBOOK_PAGE`
- `INSTAGRAM_PROFESSIONAL`
- `THREADS`

Deferred/excluded lanes remain unchanged:

- `LINKEDIN` — `HOLD_UNTIL_PRODUCTION_API_ACCESS`
- `X` — `EXCLUDED_WHILE_API_IS_PAID`
- `BLUESKY` — `HOLD_UNTIL_LOCAL_ROI_TEST_PASSES`

The global control checkpoint intentionally remains `CP58` and the global kill switch remains engaged.

## Parent binding

CP72 is exact-bound to the current CP71 contract, CP71 dry-run fingerprint and CP71 synthetic lease ID/hash. All receipts use canonical JSON and SHA-256 fingerprints. Any parent, receipt, policy, lane, state or hash drift fails closed.

## Two independent terminal-path fixtures

CP72 exercises two independent synthetic paths; it does not claim both terminal events occur in one real lease lifecycle.

### Expiry path

1. A terminal `EXPIRED` receipt is accepted once in an in-memory synthetic seen-set.
2. Presenting the exact same receipt hash again is classified as replay and rejected.
3. A pre-expiry `ACTIVE` receipt observed at `2030-01-01T00:14:59Z` but presented at the CP71 expiry boundary `2030-01-01T00:15:00Z` is stale and rejected.

### Revocation path

1. A terminal `REVOKED` receipt is accepted once in an independent in-memory synthetic seen-set.
2. Presenting the exact same receipt hash again is classified as replay and rejected.
3. A pre-revocation `ACTIVE` receipt observed at `2030-01-01T00:04:59Z` but presented at the CP71 revocation boundary `2030-01-01T00:05:00Z` is stale and rejected.

In both fixtures, terminal state is monotonic: no later or replayed receipt may restore `ACTIVE` authority.

## Ordered validation phases

1. `CP71_PARENT_EXACT_BOUND`
2. `EXPIRY_TERMINAL_RECEIPT_ACCEPTED_ONCE`
3. `EXPIRY_EXACT_REPLAY_REJECTED`
4. `EXPIRY_STALE_ACTIVE_RECEIPT_REJECTED`
5. `REVOCATION_TERMINAL_RECEIPT_ACCEPTED_ONCE`
6. `REVOCATION_EXACT_REPLAY_REJECTED`
7. `REVOCATION_STALE_ACTIVE_RECEIPT_REJECTED`
8. `TERMINAL_STATE_RESURRECTION_REJECTED`
9. `ZERO_IO_OBSERVED`
10. `AUTHORITY_REMAINS_INACTIVE`

A PASS is emitted only if every phase is satisfied.

## Fail-closed invariants

CP72 rejects any attempt to weaken exact replay rejection, stale receipt rejection, terminal single-acceptance, terminal-state non-resurrection, zero-I/O, CP71 binding, active-lane scope or `GET`-only scope. Receipt hash or shape tampering also fails closed.

A structurally valid CP72 PASS means only:

`SIMULATED_REPLAY_STALE_RECEIPT_REJECTION_PASS_NO_AUTHORITY_NO_RESURRECTION_NO_MUTATION`

It is never interpretable as live authorization, runtime authority, account connectivity or permission to execute a live read-only probe.

## Blockers retained

- `HOLD_REAL_EXTERNAL_AUTHORIZATION_RECEIPT_NOT_INGESTED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED`
- `HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED`
- `HOLD_PILOT_PUBLISH_NOT_AUTHORIZED`
- `HOLD_CP72_RECEIPT_LEDGER_SYNTHETIC_ONLY`
- `HOLD_CP72_REPLAY_STALE_REJECTION_PASS_IS_NOT_RUNTIME_AUTHORITY`

## Rollback

Rollback target is CP71. Remove the CP72 policy, engine, tests, documentation and M41 registry row. No external recovery is necessary because CP72 performs no external effects.

## Next granular unit

`CP73_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION_DRY_RUN`

CP73 is named only and is not implemented by CP72.
