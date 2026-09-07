# CP67 — Live Read-Only Probe Authorized Session Request Packet + Operator Handoff v1

## Status

`PASS_CP67_AUTHORIZED_SESSION_REQUEST_PACKET_HANDOFF_LOCAL_ONLY_AUTHORIZATION_NOT_GRANTED_LIVE_HOLD`

CP67 advances exactly one granular unit beyond CP66. It packages the already validated CP66 mock-harness lineage into an immutable request packet and a separate operator handoff for a future human authorization decision. The request is explicitly not an authorization and cannot promote any live authority.

## Scope

CP67 is local/offline only. It does not ingest a grant, resolve credentials, read environment variables or keychains, perform OAuth, look up or connect real accounts, open sockets, call Meta, execute a live probe, publish, write externally, promote the control plane, deploy, or use paid services.

The active lanes remain exactly:

- Facebook Page
- Instagram Professional
- Threads

LinkedIn remains held until production API access, X remains excluded while the API is paid, and Bluesky remains held until a local ROI test passes.

## Parent binding

The request packet binds deterministically to the CP66 contract and its CP66 single-session mock-harness run by exact ID and SHA-256. CP66 must remain in its zero-authority state with the global kill switch engaged. Any parent ID/hash, lane, state, or authority drift fails closed.

## Request semantics

The request is fixed to:

- authorization gate: `LIVE_READ_ONLY_CONNECTION_PROBE`;
- requested scope: `READ_ONLY_METADATA_PROBE`;
- requested sessions: exactly `1`;
- method allowlist: exactly `GET`;
- active platforms: Facebook Page, Instagram Professional, Threads;
- authorization state: `REQUEST_NOT_GRANTED`.

The request and handoff are canonical-JSON/SHA-256-bound and immutable. They contain no raw credential, URL, account identifier, token, secret, OAuth artifact, or live endpoint material.

## Operator handoff

The operator handoff defines what a future CP68 authorization receipt must contain without embedding any grant itself. A future external human decision must be either `GRANT` or `DENY` and must supply all of:

1. decision;
2. explicit scope;
3. approved platform subset;
4. UTC validity start;
5. UTC validity end;
6. SHA-256 human-reference fingerprint;
7. SHA-256 evidence fingerprint;
8. nonce.

The future receipt schema is `PPOS_CP68_LIVE_READ_ONLY_SESSION_AUTHORIZATION_RECEIPT_V1`. CP67 does not create such a receipt and does not infer approval from any offline PASS.

## Authority boundary

A CP67 PASS means only that the request packet and handoff are structurally complete and exactly bound to CP66. It does not grant network access, account connection, live probe execution, publication, external writes, deploy permission, or control-plane promotion.

The global registry checkpoint therefore remains intentionally `CP58`, and the global kill switch remains engaged.

## Safety invariants

The CP67 compiler proves:

- zero external authorization ingested;
- zero authorization granted;
- zero secret resolution;
- zero environment/keychain reads;
- zero OAuth;
- zero real-account lookup or connection;
- zero network attempts;
- zero live probe attempts;
- zero publish attempts;
- zero external writes;
- zero control-plane promotions;
- zero deploys;
- zero paid-service use.

## Rollback

Rollback target: `CP66`.

Removing the CP67 policy, compiler, tests, documentation, control-manifest entries, and M36 registry row restores the CP66 state without changing runtime authority.

## Next unit

`CP68_LIVE_READ_ONLY_PROBE_SESSION_AUTHORIZATION_RECEIPT_INTAKE_AND_VALIDATOR_DRY_RUN`

CP68 may define the immutable intake/validator for an externally supplied authorization receipt while remaining local/dry-run only and without itself resolving secrets, connecting accounts, executing Meta traffic, publishing, or deploying.
