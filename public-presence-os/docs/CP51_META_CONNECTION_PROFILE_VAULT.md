# CP51 — Meta Connection Profile + Secret-Reference Vault v1

## Scope

CP51 adds a local-only, fail-closed boundary for staging future Meta connection profiles without connecting any account and without reading any credential material.

Active lanes remain exactly:

- Facebook Page
- Instagram Professional
- Threads

LinkedIn remains gated on production API access, X remains excluded while its API is paid, and Bluesky remains on `HOLD_ROI`.

## Secret-reference contract

Only symbolic secret references are accepted:

- `ENV:<UPPERCASE_VARIABLE_NAME>`
- `OS_KEYCHAIN:<service/account locator>`

The module validates and stores the reference string only. It does not inspect the environment, call an OS keychain, resolve a credential, refresh a token, perform OAuth, look up a real account, or make a network request.

Literal destination IDs and literal API versions remain forbidden. CP50 placeholders `DESTINATION_ID_REQUIRED` and `API_VERSION_REQUIRED` remain mandatory.

## Immutable offline evidence

A profile can be staged in either state:

1. `STAGED_UNVERIFIED` — no permissions, capabilities, expiry assertion, or evidence hash may be smuggled into the record.
2. `OFFLINE_EVIDENCE_BOUND` — a SHA-256 evidence artifact is required and observed permissions/capabilities must exactly match the CP50 static contract for the selected platform and mode. Expiry must be explicitly `KNOWN` with RFC3339 UTC time, or explicitly `UNKNOWN`.

Even complete offline evidence never asserts current live entitlement. Every profile remains `live_reverification_required=true`.

## Local vault

The executable vault uses SQLite and stores only:

- immutable connection-profile JSON;
- symbolic secret references;
- exact profile/evidence hashes;
- append-only staging events;
- idempotency keys.

A repeated `request_id` with the same event is idempotent. Reusing it with different event content fails closed.

## Authority boundary

CP51 grants only local profile compilation and local secret-reference staging authority. It grants none of the following:

- secret resolution;
- environment reads;
- OS-keychain reads;
- network access;
- real-account discovery;
- account connection;
- publishing;
- external writes;
- deploy.

The global kill switch remains mandatory and engaged.

## Validation target

CP51 is complete when source, policy, tests, registry and product-layout checks pass while proving that no secret/network/account action is possible from this slice.

## Next granular unit

`CP52_META_CONNECTION_PREFLIGHT_SYNTHETIC_PROVISIONING_READBACK`

CP52 will exercise the CP50 request compiler and CP51 connection-profile boundary together using synthetic identifiers and synthetic evidence only, producing a deterministic local preflight/readback receipt. It will still have no credential resolution, real-account connection, network transport, publish or deploy authority.
