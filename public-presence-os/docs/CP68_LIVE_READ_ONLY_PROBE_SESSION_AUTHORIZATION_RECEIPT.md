# CP68 — Live Read-Only Probe Session Authorization Receipt Intake + Validator Dry-Run v1

## Status

`PASS_CP68_SESSION_AUTHORIZATION_RECEIPT_INTAKE_VALIDATOR_DRY_RUN_LOCAL_ONLY_AUTHORITY_NOT_ACTIVATED_LIVE_HOLD`

CP68 advances exactly one bounded PUBLIC PRESENCE OS unit after CP67. It implements a local-only validator for the future external human `GRANT` / `DENY` receipt requested by the CP67 operator handoff. It does not activate that receipt as runtime authority.

The global control checkpoint intentionally remains **CP58** and the global kill switch remains engaged.

## Canon preserved

Active lanes remain exactly:

- `FACEBOOK_PAGE`
- `INSTAGRAM_PROFESSIONAL`
- `THREADS`

Deferred lanes remain unchanged:

- LinkedIn — `HOLD_UNTIL_PRODUCTION_API_ACCESS`
- X — `EXCLUDED_WHILE_API_IS_PAID`
- Bluesky — `HOLD_UNTIL_LOCAL_ROI_TEST_PASSES`

## Receipt intake contract

A candidate receipt must use schema `PPOS_CP68_LIVE_READ_ONLY_SESSION_AUTHORIZATION_RECEIPT_V1` and must be bound exactly to the CP67 request packet and CP67 operator handoff. The accepted field set is closed: schema version, CP67 request ID/hash, CP67 handoff ID/hash, decision, scope, platform subset, UTC validity window, human-reference SHA-256, evidence SHA-256 and nonce.

Validation is fail-closed. The decision must be `GRANT` or `DENY`; scope must remain `READ_ONLY_METADATA_PROBE`; the platform subset must be non-empty and ordered as a subset of the three active lanes; validity timestamps must be canonical UTC seconds with a positive interval; human/evidence references must already be lowercase SHA-256 digests. Raw credentials, real account identifiers and routable URLs are forbidden.

The nonce is accepted only as bounded validation input and is converted immediately to `nonce_sha256`; it is not persisted in the immutable receipt. No token, account ID, URL or secret material is persisted by the CP68 receipt.

## Dry-run semantics

A structurally valid `GRANT` produces only:

`VALIDATED_GRANT_CANDIDATE_ONLY_ZERO_IO_NO_AUTHORITY`

A valid `DENY` produces:

`HOLD_EXTERNAL_AUTHORIZATION_DENIED`

Neither outcome mutates the module registry or runtime policy, promotes the control plane, resolves secrets, connects accounts, permits network, executes a live probe, publishes, writes externally or deploys. The repository acceptance path uses a deterministic synthetic fixture only; therefore CP68 does not claim that an external authorization has actually been ingested or granted.

## Safety invariants

- global kill switch stays engaged;
- global checkpoint stays CP58;
- `external_authorization_ingested=false` in the canonical CP68 contract;
- `authorization_granted=false` and `runtime_authorization_effective=false`;
- network, live probe, account connection, publish, external write and deploy remain disabled;
- a green CP68 test result is evidence of validator readiness, not permission to contact Meta.

## Rollback and recovery

Rollback target is CP67. Remove the CP68 policy/module/test/doc and M37 registry entry, then restore the CP67 product-layout list. No external recovery action is required because CP68 has no network or account side effects.

## Blockers retained

Live evidence has not been captured; secret references remain unresolved; real accounts remain unconnected; control-plane promotion has not been executed; no live read-only probe has executed; pilot publication is not authorized. Additionally, CP68 explicitly records that a validated receipt is not runtime authority and that any later control promotion requires a separate bounded unit.

## Next bounded unit

`CP69_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX_ZERO_IO_DRY_RUN`

CP69 is named only here. CP68 does not implement it.
