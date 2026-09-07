# CP71 — Live Read-Only Probe Authority Lease Expiry + Revocation Dry-Run v1

## Status

`PASS_CP71_AUTHORITY_LEASE_EXPIRY_REVOCATION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD`

CP71 is one granular, reversible, local-only unit. It models the lifecycle of a synthetic authority lease candidate after CP70 and proves that expiry and explicit revocation both fail closed. It does not issue or activate runtime authority. The global control-plane checkpoint remains `CP58`.

## Scope completed

- Added `M40_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_EXPIRY_REVOCATION`.
- Exact-bound CP71 to the CP70 contract and CP70 transaction fingerprints.
- Added a deterministic 900-second synthetic lease fixture with fixed UTC issue, pre-expiry, revocation, and expiry timestamps.
- Added fail-closed expiry-at-boundary behavior.
- Added fail-closed explicit revocation before expiry.
- Added terminal-state non-reuse invariant after either expiry or revocation.
- Locked scope to `READ_ONLY_METADATA_PROBE`, `GET` only, and the active lane canon: Facebook Page, Instagram Professional, Threads.
- Added immutable SHA-256 evidence for lease and lifecycle phases.
- Added dedicated CP71 tests and product-layout coverage.

## Lease phases

1. `CP70_PARENT_EXACT_BOUND`
2. `LEASE_CANDIDATE_BOUNDED_SYNTHETIC`
3. `PRE_EXPIRY_CANDIDATE_VALIDATED_NO_RUNTIME_AUTHORITY`
4. `EXPIRY_AT_BOUNDARY_INVALIDATES_CANDIDATE`
5. `EXPLICIT_REVOCATION_INVALIDATES_BEFORE_EXPIRY`
6. `POST_TERMINAL_REUSE_REJECTED`
7. `ZERO_IO_OBSERVED`
8. `AUTHORITY_REMAINS_INACTIVE`

A structural PASS yields only:

`SIMULATED_LEASE_EXPIRY_REVOCATION_PASS_NO_AUTHORITY_NO_REUSE_NO_MUTATION`

It is not a live authorization, not a control-plane promotion, not an account connection, and not a network probe.

## Deterministic lease fixture

- issued: `2030-01-01T00:00:00Z`
- explicit revocation test point: `2030-01-01T00:05:00Z`
- pre-expiry validation point: `2030-01-01T00:14:59Z`
- expiry boundary: `2030-01-01T00:15:00Z`
- TTL: `900` seconds

These timestamps are test fixtures only and carry no real-world authorization meaning.

## Validated invariants

- Global kill switch remains engaged.
- Runtime network remains disabled.
- Account connection remains disabled.
- Publishing remains disabled.
- Deploy remains disabled.
- Registry checkpoint remains `CP58`.
- No environment/keychain reads are permitted.
- No OAuth, real-account lookup, network request, live probe, publish attempt, external write, deploy attempt, or paid-service use is permitted.
- `runtime_authorization_effective=false` and `authority_activated=false` throughout the lease dry-run.
- A lease candidate is non-reusable after synthetic expiry or explicit revocation.
- No runtime, registry, or policy mutation is performed by the engine.

## Lane decisions retained

- `FACEBOOK_PAGE`: active lane.
- `INSTAGRAM_PROFESSIONAL`: active lane.
- `THREADS`: active lane.
- `LINKEDIN`: hold until production API access.
- `X`: excluded while API access is paid.
- `BLUESKY`: hold until a later local ROI test passes.

## Blockers retained

- `HOLD_REAL_EXTERNAL_AUTHORIZATION_RECEIPT_NOT_INGESTED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED`
- `HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED`
- `HOLD_PILOT_PUBLISH_NOT_AUTHORIZED`
- `HOLD_CP71_LEASE_IS_SYNTHETIC_ONLY`
- `HOLD_CP71_EXPIRY_REVOCATION_PASS_IS_NOT_RUNTIME_AUTHORITY`

## Safety / external effects

Expected and required for CP71: 0 real social accounts connected; 0 secrets resolved; 0 environment or keychain reads; 0 OAuth; 0 social API traffic; 0 live probes; 0 publish attempts; 0 public posts; 0 external writes; 0 control-plane promotions; 0 deploys; 0 paid services.

## Rollback

Rollback target: `CP70`. Remove the CP71 policy/engine/test/doc entries and the M40 registry row; CP70 remains the prior accepted local-only activation-transaction dry-run. No external recovery is necessary because CP71 performs no external effects.

## Changelog

- Added CP71 bounded synthetic lease contract.
- Added deterministic expiry and explicit-revocation dry-run behavior.
- Added terminal-state replay/reuse rejection invariant.
- Added fail-closed CP71 test coverage.
- Added CP71 to product-layout validation.
- Preserved global checkpoint `CP58` and all live holds.

## Next unit

`CP72_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_REPLAY_AND_STALE_RECEIPT_REJECTION_DRY_RUN`

CP72 is named only. It is not implemented by CP71.
