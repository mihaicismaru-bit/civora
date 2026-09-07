# CP62 — Authorization Receipt Validator + Control Promotion Dry-Run v1

## Checkpoint

**State:** `PASS_CP62_AUTHORIZATION_RECEIPT_VALIDATOR_DRY_RUN_LOCAL_ONLY_CONTROL_PROMOTION_HOLD`

**Control checkpoint:** remains `CP58`.

**Parent:** CP61 — Control Plane Promotion + Authorization Intake Contract v1.

CP62 advances one unit only. It validates the shape receipt emitted by CP61 into an immutable, hash-bound local receipt and simulates the control-plane promotion decision without mutating the registry, runtime policy, network state, accounts, queue, publisher, or deployment state.

## What was added

- `config/authorization_receipt_validator_policy.json`
- `src/public_presence_os/authorization_receipt_validator.py`
- `tests/test_cp62_authorization_receipt_validator.py`
- this checkpoint document
- productization registry/required-file bindings for M31

The repository acceptance path uses a **synthetic authorization fixture only**. It is not a real external-human authorization and cannot be converted into one by the module.

## Receipt contract

The CP62 immutable receipt is exact-bound to:

1. the CP61 contract ID and SHA-256;
2. the CP61 shape-receipt ID and SHA-256;
3. the CP60 handoff packet ID and SHA-256;
4. the authorization ID, gate, decision, platform subset and scope;
5. the authorization window and evidence SHA-256;
6. SHA-256 references for authorizer identity and nonce.

Raw `HUMAN:` references, raw nonce values and raw authorization evidence are not persisted by the CP62 receipt.

## Control-promotion dry-run

The dry-run starts from canonical control checkpoint `CP58` and never commits a promotion.

- `GRANT` for `LIVE_READ_ONLY_CONNECTION_PROBE` → candidate-only PASS, no authority.
- `GRANT` for `PILOT_PUBLISH` → HOLD until live evidence and a later gate.
- `DENY` → HOLD.
- kill switch remains engaged.
- registry/runtime mutation is forbidden.
- network, account lookup/connection, OAuth, live probes, publishing, external writes and deployment remain forbidden.

## Platform policy

Active lanes remain exactly:

- Facebook Page
- Instagram Professional
- Threads

Deferred/excluded lanes remain:

- LinkedIn — HOLD until production API access.
- X — excluded while the API is paid.
- Bluesky — HOLD until a local ROI test passes.

## Changelog

- Added M31 authorization-receipt validator.
- Added deterministic immutable receipt IDs/hashes.
- Added deterministic local control-promotion dry-run receipts.
- Added fail-closed tamper checks for CP61/CP60 bindings, platform scope, evidence, authorizer-reference hash and nonce hash.
- Added explicit zero-side-effect assertions and a synthetic-only repository-validation fixture.
- Kept global control checkpoint at CP58.

## Decisions

- CP61 structural validation remains separate from CP62 immutable receipt validation.
- CP62 does not ingest or activate external authorization.
- A dry-run `GRANT` is evidence that the local decision path is coherent, **not** authority to contact Meta or publish.
- The global kill switch cannot be disengaged by CP62.
- No paid service is introduced.

## Blockers retained

- `HOLD_EXTERNAL_AUTHORIZATION_NOT_INGESTED`
- `HOLD_LIVE_EVIDENCE_NOT_CAPTURED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED`
- `HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED`
- `HOLD_PILOT_PUBLISH_NOT_AUTHORIZED`

## Rollback

Rollback target is CP61. Removing the M31 files and registry/productization bindings restores the prior authorization-intake-only state; no external state needs reversal because CP62 performs no external I/O.

## Next unit

`CP63_LIVE_READ_ONLY_PROBE_SESSION_ENVELOPE_AND_ZERO_WRITE_RECORDER_DRY_RUN`

CP63 should define the deterministic session envelope and zero-write evidence recorder used before any future live read-only probe. It must remain a local dry-run unit: no real credentials, no real account connection, no Meta network call, no publish and no deploy.
