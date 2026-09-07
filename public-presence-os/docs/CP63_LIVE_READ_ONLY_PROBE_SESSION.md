# CP63 — Live Read-Only Probe Session Envelope + Zero-Write Recorder Dry-Run v1

## Checkpoint

**State:** `PASS_CP63_SESSION_ENVELOPE_ZERO_WRITE_RECORDER_DRY_RUN_LOCAL_ONLY_LIVE_HOLD`

**Global control checkpoint:** remains `CP58` intentionally. CP63 does not promote the control plane and does not create live authority.

## Scope completed

CP63 defines the deterministic, synthetic-only envelope that a future Meta read-only probe session must conform to, and a local zero-write recorder dry-run that proves the planned sequence contains no mutating method, network attempt, secret material or external write.

The envelope is exact-hash-bound to the CP62 authorization-receipt-validator contract, its immutable receipt and its control-promotion dry-run. Probe classes and evidence codes are inherited exactly from CP56 rather than duplicated as an independent source of truth.

## Canonical lanes

Active lanes remain exactly:

- `FACEBOOK_PAGE`
- `INSTAGRAM_PROFESSIONAL`
- `THREADS`

Deferred/excluded lanes remain unchanged:

- LinkedIn — `HOLD_UNTIL_PRODUCTION_API_ACCESS`
- X — `EXCLUDED_WHILE_API_IS_PAID`
- Bluesky — `HOLD_UNTIL_LOCAL_ROI_TEST_PASSES`

## Session envelope safety boundary

The only allowed method is `GET`. `POST`, `PUT`, `PATCH` and `DELETE` are rejected fail-closed. CP63 stores only synthetic endpoint labels of the form `SYNTHETIC_ENDPOINT::<PLATFORM>::<PROBE_CLASS>`; real URLs are forbidden. The API version is deliberately represented only by `SYNTHETIC_META_API_VERSION_NOT_FOR_NETWORK`, so no stale or invented live Meta API version can be mistaken for production configuration.

The global kill switch must remain engaged. Secret resolution, environment reads, keychain reads, OAuth, real-account lookup, account connection, network traffic, live probe execution, publish execution, external write, deploy and paid services all remain forbidden.

## Zero-write recorder

The recorder deterministically produces one event per synthetic probe step. Each event persists only request and response SHA-256 fingerprints derived from non-secret synthetic metadata. Raw request/response bodies, tokens and secrets are not part of the receipt schema.

Acceptance requires all counters to remain exactly zero:

- write attempts
- mutating methods
- network attempts
- secret material
- external writes

Any event drift, non-GET method, non-zero counter, raw-secret flag, network flag or external-write flag causes a fail-closed hold.

## Changelog

- Added `config/live_read_only_probe_session_policy.json`.
- Added `src/public_presence_os/live_read_only_probe_session.py`.
- Added deterministic CP62→CP63 session-envelope hash binding.
- Added exact CP56 probe-class and evidence-code binding.
- Added synthetic zero-write event recorder and immutable recorder receipt.
- Added CP63 test suite covering determinism, tamper detection, GET-only enforcement, synthetic-endpoint enforcement, evidence preservation and zero-authority invariants.
- Registered `M32_LIVE_READ_ONLY_PROBE_SESSION` without advancing the global control checkpoint.
- Added CP63 artifacts to product-layout validation.

## Decisions

1. CP63 is dry-run only; the word “live” describes the future boundary being modeled, not an executed live session.
2. No production Meta endpoint or API version is encoded at CP63.
3. CP56 remains the canonical source for probe classes and evidence codes.
4. CP62 remains the authorization-chain parent; CP58 remains the global control checkpoint.
5. A zero-write proof is structural and hash-bound, not an operator assertion.

## Blockers retained

- `HOLD_EXTERNAL_AUTHORIZATION_NOT_INGESTED`
- `HOLD_LIVE_EVIDENCE_NOT_CAPTURED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED`
- `HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED`
- `HOLD_PILOT_PUBLISH_NOT_AUTHORIZED`
- `HOLD_CP63_SESSION_DRY_RUN_ONLY`

## Safety status

At CP63 completion there must still be: 0 real social accounts connected; 0 real secrets resolved; 0 environment/keychain reads; 0 OAuth; 0 social API network calls; 0 live probes; 0 publish attempts; 0 external writes; 0 public posts; 0 deploy; 0 paid services.

## Rollback

Rollback target is CP62. Remove the CP63 policy/module/tests/docs and the M32 registry row, then restore product-layout expectations to CP62. No external rollback is required because CP63 performs no external mutation.

## Next unit

`CP64_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT_GATE_AND_REPLAY_VALIDATOR_DRY_RUN`

CP64 should define an offline gate for importing a future redacted/hash-bound evidence bundle and deterministically replaying its structural sequence against the CP63 envelope. It must remain dry-run only: no real secret resolution, no account connection, no Meta traffic, no publication and no deploy.
