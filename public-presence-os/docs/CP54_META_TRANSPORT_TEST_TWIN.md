# CP54 — Meta Transport Test Twin + Request-Signing Boundary v1

## Status

`PASS_CP54_SYNTHETIC_META_TRANSPORT_TWIN / HOLD_PILOT_CP55_LIVE_CONNECTION_GATES`

This checkpoint adds a transport-shaped test twin only. It does not add a live HTTP client, OAuth flow, account lookup, real token resolver, publishing authority, external write path or deploy path.

## Exact lineage

The twin accepts only an exact, already-valid lineage:

1. CP50 `OfflineRequestPlan`.
2. CP52 `SyntheticPreflightReceipt` whose `plan_id` and `plan_hash` match CP50 exactly.
3. CP53 `OperatorProvisioningPacket` whose preflight receipt ID/hash matches CP52 exactly and whose platform/mode/auth/permissions/capabilities match CP50.

Any drift fails closed before request serialization.

## Synthetic-only bindings

The unit intentionally refuses production-looking runtime values:

- destination IDs must match the `TEST_DESTINATION_*` namespace;
- API versions must match `TEST_API_VERSION_*`;
- image staging URLs must use `https://example.invalid/`;
- bearer tokens must be explicitly prefixed `TEST_ONLY_TOKEN_*`;
- signing secrets must be explicitly prefixed `TEST_ONLY_SIGNING_SECRET_*`;
- the credential marker must be exactly `PPOS_TEST_ONLY`.

These values exist only inside tests or explicit local dry-run construction. CP54 never resolves CP51 `ENV:` or `OS_KEYCHAIN:` references.

## Authorization boundary

CP54 exercises the shape of a bearer-auth boundary without persisting credential material. A synthetic bearer value is accepted only when it carries the test-only marker. The receipt stores only SHA-256 of the full synthetic authorization value; the token itself is excluded from the serialized receipt.

This is **not** evidence that a live Meta token is valid or entitled to publish.

## Request-signing boundary

Each synthetic request receives an internal HMAC-SHA256 over its canonical unsigned request representation using the explicit test-only signing secret. The resulting digest is recorded only as an internal twin proof.

Important boundaries:

- `signature_scope = TWIN_INTERNAL_HMAC_SHA256_ONLY`;
- no production Meta request-signing semantics are asserted;
- no signature header is emitted;
- no app secret, token, or secret reference is serialized;
- the signature is never sent to any network target.

The purpose is to test secret-handling, canonicalization and deterministic-signature boundaries before a later live-gate design is considered, not to emulate undocumented or unverified production behavior.

## Idempotency and retry

Every request gets a deterministic local idempotency key bound to the CP50 plan hash, request ordinal/operation and synthetic destination hash. CP54 explicitly does **not** claim that Meta accepts or honors this key, and it never emits a wire idempotency header.

The retry classifier is synthetic and status-only:

- 2xx → `SUCCESS_SYNTHETIC`;
- 429 → `RETRY_RATE_LIMIT_SYNTHETIC`;
- 408/500/502/503/504 → `RETRY_TRANSIENT_SYNTHETIC`;
- 401/403 → `NO_RETRY_AUTH_SYNTHETIC`;
- other 4xx → `NO_RETRY_CLIENT_SYNTHETIC`;
- all other valid HTTP status values → `HOLD_UNKNOWN_SYNTHETIC_STATUS`.

This classifier is a local test policy, not a claim about live Meta error semantics. Live error payloads and retry requirements must be reverifed before any real transport is authorized.

## Network and authority invariants

CP54 keeps all of the following false:

- secret-reference resolution;
- environment/keychain reads;
- OAuth;
- real account lookup;
- account connection;
- network attempts;
- publish attempts;
- external writes;
- deploy;
- live entitlement verification;
- live transport readiness;
- pilot publish readiness.

The global kill switch remains required and engaged.

## Platform lanes

Active lanes remain exactly:

- Facebook Page;
- Instagram Professional;
- Threads.

LinkedIn remains held until production API access exists. X remains excluded while its required API is paid. Bluesky remains held until a later local ROI test passes.

## Validation target

The unit is complete when:

- all five currently supported Meta platform/mode combinations compile deterministically;
- exact CP50→CP52→CP53 lineage is enforced;
- production-looking destinations, API versions, staging URLs and credentials are rejected;
- serialized receipts contain no token or signing-secret material;
- request hashes, internal signatures and local idempotency keys are deterministic;
- retry classification is deterministic and synthetic-only;
- source contains no network or secret-resolution implementation;
- repository policy remains fail-closed.

## Remaining HOLD

Pilot remains held. CP54 does not authorize a real connection.

Next bounded unit: `CP55_META_READ_ONLY_CONNECTION_GATE_CONTRACT_AND_KILL_SWITCH_INTERLOCK` — a fail-closed contract for the future read-only connection test, including explicit kill-switch interlock and evidence requirements, still without making a real account connection or publication unless a later checkpoint separately authorizes it.
