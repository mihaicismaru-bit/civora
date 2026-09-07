# CP61 — Control Plane Promotion + Authorization Intake Contract v1

## Status

`PASS_CP61_AUTHORIZATION_INTAKE_CONTRACT_LOCAL_ONLY_CONTROL_PROMOTION_HOLD`

CP61 defines the fail-closed contract by which a later explicit human authorization can be presented for validation. It does **not** ingest a real authorization, promote the control plane, resolve secrets, connect an account, call a social API, publish, write externally or deploy.

The global control checkpoint remains **CP58**. CP61 is a local contract milestone only.

## Canonical lanes

Active lanes remain exactly:

- Facebook Page
- Instagram Professional
- Threads

Deferred/excluded lanes remain:

- LinkedIn — hold until production API access exists.
- X — excluded while automated API access is paid.
- Bluesky — hold until a later local ROI test passes.

## Parent binding

CP61 compiles and validates the exact current CP60 operator handoff packet. The resulting contract binds:

- CP60 packet id and SHA-256;
- CP60 policy SHA-256;
- CP61 policy SHA-256;
- runtime policy SHA-256;
- module registry SHA-256.

Any drift fails closed.

## Intake schema

A future authorization submission must carry exactly these fields:

`authorization_id`, `gate_code`, `decision`, `allowed_platforms`, `scope`, `authorizer_reference`, `authorized_at`, `expires_at`, `authorization_evidence_sha256`, `cp60_packet_id`, `cp60_packet_hash`, `nonce`.

The contract accepts only `GRANT` or `DENY` as structural decisions, requires an opaque `HUMAN:` authorizer reference, requires UTC `Z` timestamps with a positive validity window, requires an exact CP60 binding and requires a SHA-256 evidence digest. Platforms must be a non-empty subset of the three active lanes.

The raw nonce is never copied into the validation receipt; only its SHA-256 is retained.

## Gate separation

`LIVE_READ_ONLY_CONNECTION_PROBE` is bound to `READ_ONLY_CONNECTION_AND_EVIDENCE_CAPTURE_ONLY`. A structurally valid future grant can become only a candidate for CP62 validation.

`PILOT_PUBLISH` is bound to `PILOT_PUBLISH_ONLY_AFTER_SEPARATE_LIVE_VALIDATION`. Even a structurally valid future grant has no effective publish authority until later live evidence and later promotion gates are satisfied.

CP61 therefore prevents a read-only authorization from being widened into publish authority and prevents any publish authorization from bypassing live validation.

## Zero-authority invariant

A CP61 contract has all of the following fixed to false:

- external authorization ingested;
- authorization activated;
- live evidence captured;
- secret reference resolved;
- environment/keychain read;
- OAuth attempted;
- real account lookup attempted;
- account connected;
- network attempted;
- live probe attempted;
- publish attempted;
- external write performed;
- control plane promoted;
- deploy performed;
- paid service used;
- self-authorization performed.

The global kill switch remains engaged.

## Structural submission validator

CP61 includes an offline shape validator for synthetic fixtures. Its receipt is always `VALIDATED_SHAPE_ONLY_NO_AUTHORITY`, including when the supplied synthetic decision is `GRANT`. A shape receipt cannot activate authority, promote control, enable network, enable a live probe, publish or deploy.

This validator exists to prove that the future authorization boundary is deterministic and fail-closed; it is not an authorization executor.

## Blockers retained

- `HOLD_EXTERNAL_AUTHORIZATION_NOT_INGESTED`
- `HOLD_LIVE_EVIDENCE_NOT_CAPTURED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED`
- `HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED`
- `HOLD_PILOT_PUBLISH_NOT_AUTHORIZED`

## Rollback

Rollback target is CP60. Remove the CP61 policy, compiler, tests, documentation and M30 registry entry; restore repository-layout binding to CP60. No external recovery action is necessary because CP61 performs no external side effect.

## Next unit

`CP62_AUTHORIZATION_RECEIPT_VALIDATOR_AND_CONTROL_PROMOTION_DRY_RUN`

CP62 may validate a synthetic/external-shaped immutable authorization receipt and rehearse control-plane promotion locally. It must remain dry-run only unless a separately verified explicit human authorization and the applicable live-evidence prerequisites exist; no account connection, social API traffic, publication or deployment is implied by CP61.
