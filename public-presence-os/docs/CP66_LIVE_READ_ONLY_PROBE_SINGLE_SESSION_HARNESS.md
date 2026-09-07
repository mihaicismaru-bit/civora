# CP66 — Live Read-Only Probe Single-Session Execution Harness Dry-Run v1

## Status

`PASS_CP66_SINGLE_SESSION_EXECUTION_HARNESS_DRY_RUN_MOCK_ONLY_LIVE_HOLD`

CP66 advances one granular unit beyond CP65. It proves that the future read-only probe sequence can be executed end-to-end through a strictly injected in-memory mock transport while preserving the existing live hold.

## Scope

CP66 is local/offline only. It does not resolve credentials, read environment variables or keychains, perform OAuth, look up or connect real accounts, open sockets, call Meta, publish, write externally, promote the control plane, deploy, or use paid services.

The active lanes remain exactly:

- Facebook Page
- Instagram Professional
- Threads

LinkedIn remains held until production API access, X remains excluded while the API is paid, and Bluesky remains held until a local ROI test passes.

## Parent bindings

The harness binds deterministically to:

1. the CP65 execution-admission contract;
2. the CP65 operator preflight packet;
3. the CP65 admission receipt, which must remain `HOLD_EXTERNAL_HUMAN_AUTHORIZATION_REQUIRED_NO_EXECUTION`;
4. the CP64 evidence-import contract;
5. the CP63 synthetic session envelope used by CP64.

Any ID/hash drift fails closed.

## Injected transport boundary

The harness has no default transport. A caller must inject a transport object. CP66 accepts only a transport declaring:

- `kind = MOCK_IN_MEMORY_NO_NETWORK`;
- `network_capable = false`;
- a synchronous `execute(request)` boundary;
- one call exactly per synthetic session step.

A network-capable transport, a different transport kind, a missing execute boundary, a mutating method, or a real URL is rejected before live execution can occur.

The repository implementation contains only `DeterministicMockTransport`; it computes synthetic response fingerprints in memory and has no networking dependency.

## Session semantics

The CP63 step order is replayed once, in order, with `GET` as the only allowed method. Each request contains metadata already present in the synthetic session envelope and a SHA-256 request fingerprint. The receipt stores only structural metadata and request/response fingerprints; raw request/response payload persistence is outside CP66 and forbidden by policy.

The dry-run receipt proves:

- exact step cardinality;
- deterministic step order;
- exactly one transport call per step;
- zero retries;
- zero writes;
- zero network attempts;
- zero secret material;
- zero external writes;
- kill switch still engaged;
- no authorization, authority, account connection, live probe, publication, or deploy.

## Fault injection

`DeterministicMockTransport` can inject a synthetic fault at a selected sequence number. The harness fails closed on the first fault and does not retry. Automatic retry is deliberately forbidden in CP66 so retry/idempotency behavior can be introduced later behind a separate, explicit unit and evidence boundary.

## Authority boundary

A CP66 PASS is evidence of local harness correctness only. It is not a live authorization, credential entitlement, account connection approval, network permission, publish permission, deploy permission, or control-plane promotion.

The global registry checkpoint therefore remains `CP58`.

## Rollback

Rollback target: `CP65`.

Removing the CP66 policy, harness module, test, documentation, control manifest entries, and M35 registry row restores the CP65 state without changing runtime authority.

## Next unit

`CP67_LIVE_READ_ONLY_PROBE_AUTHORIZED_SESSION_REQUEST_PACKET_AND_OPERATOR_HANDOFF`

CP67 may define the immutable request/handoff packet required before any separately authorized live read-only session, while preserving fail-closed behavior and without itself connecting accounts or publishing.
