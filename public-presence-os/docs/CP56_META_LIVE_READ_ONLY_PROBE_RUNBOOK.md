# CP56 — META LIVE READ-ONLY PROBE RUNBOOK + EVIDENCE CAPTURE CONTRACT v1

Status: `PASS_CP56_RUNBOOK_EVIDENCE_CAPTURE_CONTRACT_LOCAL_ONLY / HOLD_PILOT_CP57_OFFLINE_EVIDENCE_BUNDLE_VALIDATOR_AND_OPERATOR_DRY_RUN`

## Purpose

CP56 defines the exact operator runbook and immutable evidence-capture contract for a later Meta read-only verification. CP56 does **not** execute that verification. It does not resolve secrets, connect accounts, materialize live endpoints, perform HTTP calls, publish, write externally, or deploy.

The contract is bound to the exact CP55 `MetaReadOnlyGateReceipt`. Facebook Page, Instagram Professional and Threads remain the only active lanes. LinkedIn remains held until production API access, X remains excluded while its API is paid, and Bluesky remains held until a local ROI test passes.

## Hard safety invariants

- Global kill switch stays engaged for the entire CP56 unit.
- CP56 only permits a future read-only method class of `GET`.
- `POST`, `PUT`, `PATCH` and `DELETE` are explicitly forbidden.
- No automatic live retry is permitted.
- Raw secret bytes and raw token values may never be persisted in the evidence bundle.
- Only redacted, canonicalized and SHA-256-bound evidence may persist later.
- A future API version pin and endpoint must be re-verified by the operator against the current official Meta documentation at execution time; CP56 deliberately does not hard-code a version as permanently valid.
- A CP56 PASS is not live entitlement, not account connection, not pilot readiness and not publication authority.

## Future operator runbook contract

The following sequence is the only admissible shape for a later, separately authorized read-only probe. CP56 records the sequence but does not execute it.

1. Verify the exact CP55 gate hash and exact CP56 policy hash.
2. Verify `global_kill_switch_engaged=true` and all runtime write/network/account-connection flags remain false before any future live probe boundary is opened.
3. Re-check the current official Meta documentation for the target lane. Record the chosen API version pin, the documentation source reference and the operator UTC timestamp as evidence. Abort on ambiguity or version drift.
4. Re-check the exact documented read-only endpoint for token-debug/credential-state evidence. The persisted artifact must be redacted before hashing; raw token or secret bytes are forbidden from persistence.
5. Re-check and execute only the documented minimal identity readback appropriate to the lane. Persist only redacted identity-match evidence.
6. Capture the exact permission set, capability set and expiry state required by the existing CP50–CP55 contracts. Canonicalize sets before hashing.
7. Hash the redacted canonical read-only response material with SHA-256. Do not upload the evidence to an external service.
8. Produce a zero-write proof: observed method class must be GET-only, no publisher/queue mutation may occur, no external write may occur, and the global kill switch must remain engaged.
9. If any identity, permission, capability, endpoint, API-version or method invariant differs from the contract, abort. Discard unredacted working material and preserve only redacted/hash-bound diagnostic evidence.
10. A successful future read-only probe remains insufficient to publish. Publication and deployment require later pilot gates.

## Platform probe classes

### Facebook Page

- `TOKEN_DEBUG_READ_ONLY`
- `PAGE_IDENTITY_READ_ONLY`
- `PAGE_PERMISSION_CAPABILITY_READBACK`

### Instagram Professional

- `TOKEN_DEBUG_READ_ONLY`
- `IG_PROFESSIONAL_IDENTITY_READ_ONLY`
- `IG_PERMISSION_CAPABILITY_READBACK`

### Threads

- `TOKEN_DEBUG_READ_ONLY`
- `THREADS_PROFILE_IDENTITY_READ_ONLY`
- `THREADS_PERMISSION_CAPABILITY_READBACK`

The executable CP56 source keeps endpoint selection symbolic as `OPERATOR_VERIFIED_META_DOCUMENTED_ENDPOINT`. This is intentional: the current documented endpoint and API version must be verified again at the later execution boundary rather than silently fossilized in source.

## Evidence contract

The CP55 required evidence set is carried forward unchanged and all slots remain `NOT_CAPTURED` in CP56:

| Evidence code | Capture contract |
|---|---|
| `LIVE_TOKEN_DEBUG_REDACTED` | redacted canonical JSON + SHA-256 |
| `LIVE_ACCOUNT_IDENTITY_MATCH_REDACTED` | redacted canonical identity match + SHA-256 |
| `LIVE_PERMISSION_SET_EXACT` | sorted exact string set + SHA-256 |
| `LIVE_CAPABILITY_SET_EXACT` | sorted exact string set + SHA-256 |
| `LIVE_EXPIRY_STATE` | normalized expiry state + SHA-256 |
| `LIVE_READ_ONLY_RESPONSE_HASH` | SHA-256 only |
| `OPERATOR_TIMESTAMP_UTC` | RFC3339 UTC value + SHA-256 |
| `API_VERSION_PIN` | version literal + official-source binding + SHA-256 |
| `ZERO_WRITE_CONFIRMATION` | local invariant proof + SHA-256 |

Every slot requires canonicalization and redaction. Raw secret/token persistence and external evidence upload are forbidden.

## Recovery and rollback

Recovery is fail-closed. On non-GET behavior, endpoint drift, API-version drift, identity mismatch, permission/capability mismatch or any unexpected write-capable condition, the future probe must abort immediately. The global kill switch remains engaged. Unredacted working material is discarded. Only redacted/hash-bound evidence may be retained. There is no automatic live retry.

Because CP56 itself performs no mutation, no network action and no account connection, CP56 rollback is repository-only: revert the CP56 source/config/docs/tests/registry changes. No remote-account rollback is required.

## Validation target

CP56 is complete only when:

- the CP56 compiler deterministically binds an exact CP55 gate and policy hash;
- all active lanes compile platform-native GET-only probe steps;
- all nine evidence slots remain `NOT_CAPTURED`;
- raw secret/token persistence is impossible by contract;
- recovery and zero-write requirements are explicit;
- repository validation, compile, tests, product-layout and reproducible-package checks pass.

## Next bounded unit

`CP57 — META OFFLINE EVIDENCE BUNDLE VALIDATOR + OPERATOR DRY-RUN v1`

CP57 will validate a fully synthetic/redacted evidence bundle against the CP56 schema and run an operator dry-run with no real secrets, accounts or network. It will not perform a live Meta probe, publish or deploy.
