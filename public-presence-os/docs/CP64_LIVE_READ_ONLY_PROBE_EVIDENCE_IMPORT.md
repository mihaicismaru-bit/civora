# CP64 — Live Read-Only Probe Evidence Import Gate + Replay Validator Dry-Run v1

## Status

`PASS_CP64_EVIDENCE_IMPORT_GATE_REPLAY_VALIDATOR_DRY_RUN_LOCAL_ONLY_LIVE_HOLD`

CP64 adds a strictly local, fail-closed import gate for a future redacted/hash-bound read-only evidence bundle and a deterministic structural replay validator against the CP63 session envelope and zero-write recorder. CP64 does not ingest live evidence, resolve credentials, connect accounts, execute network traffic, publish, write externally, promote the control plane, deploy, or use paid services.

The global control checkpoint remains intentionally pinned at **CP58**. CP64 proves only that the import/replay boundary is structurally ready; it does not create live authority.

## Completed

- Added `M33_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT`.
- Added strict bundle schema `PPOS_CP64_REDACTED_EVIDENCE_BUNDLE_V1`.
- Bound every accepted bundle exactly to the CP63 contract, CP63 session envelope, CP63 zero-write recorder, active platform set, and the nine CP56 evidence codes.
- Added canonical JSON + SHA-256 bundle binding.
- Added fail-closed detection for extra fields, missing/duplicate evidence, parent/hash drift, mutating methods, real URLs, side-effect counters, authority claims, and raw credential/token-like material.
- Added deterministic structural replay against CP63 request/response fingerprints without executing a request.
- Added immutable import and replay receipts that preserve zero-write/zero-network/no-authority state.

## Validation contract

Current CP64 execution uses only a generated synthetic redacted fixture. Evidence items contain hashes, not source payloads. Replay rows contain only CP63 synthetic endpoint labels and SHA-256 request/response fingerprints. The method allowlist is exactly `GET`; `POST`, `PUT`, `PATCH`, and `DELETE` are fail-closed. Facebook Page, Instagram Professional, and Threads remain the only active lanes.

LinkedIn remains held until production API access exists. X remains excluded while its required API access is paid. Bluesky remains held pending a positive local ROI test.

## Changelog

- `CP63 -> CP64`: introduced the offline evidence-import boundary and structural replay receipt.
- No runtime policy live capability was enabled.
- No network transport was added.
- No secret store or environment/keychain lookup was added.
- No publisher path was enabled.

## Decisions

1. The import gate is schema-strict: unexpected fields are rejected rather than ignored.
2. CP64 accepts only synthetic fixtures during this checkpoint; a structurally valid future live bundle is not treated as authority until a later explicit admission boundary.
3. Redacted evidence is represented by deterministic SHA-256 bindings, never raw response/request payloads.
4. Replay means structural comparison only; it never replays against a network endpoint.
5. The kill switch remains engaged and the global checkpoint remains CP58.

## Blockers retained

- `HOLD_EXTERNAL_AUTHORIZATION_NOT_INGESTED`
- `HOLD_LIVE_EVIDENCE_NOT_CAPTURED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED`
- `HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED`
- `HOLD_PILOT_PUBLISH_NOT_AUTHORIZED`
- `HOLD_CP64_SYNTHETIC_IMPORT_REPLAY_ONLY`

## Safety readback

Expected after CP64: zero real accounts connected; zero secret/environment/keychain reads; zero OAuth; zero social API calls; zero live probes; zero publish attempts; zero external writes; zero deployments; zero paid services. The global kill switch is engaged.

## Rollback

Rollback target: **CP63**. Remove M33 policy/source/tests/docs and the M33 registry row, then restore the productization expected-file list. No external rollback is required because CP64 has no external side effects.

## Next granular unit

**CP65 — LIVE READ-ONLY PROBE EXECUTION ADMISSION GATE + OPERATOR PREFLIGHT PACKET v1.** CP65 should define the final fail-closed admission/preflight packet for a future explicitly authorized read-only probe session. It must remain contract/offline-only unless an explicit external human authorization is actually supplied; it must not infer authority from CP64 PASS.
