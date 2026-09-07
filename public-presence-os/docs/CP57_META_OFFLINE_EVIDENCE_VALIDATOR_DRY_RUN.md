# CP57 — META OFFLINE EVIDENCE BUNDLE VALIDATOR + OPERATOR DRY-RUN v1

Status: `PASS_CP57_SYNTHETIC_EVIDENCE_BUNDLE_VALIDATOR_DRY_RUN_LOCAL_ONLY / HOLD_PILOT_CP58_PILOT_READINESS_AGGREGATOR_AND_LIVE_CONNECTION_AUTHORIZATION_GATE`

## Purpose

CP57 validates the CP56 evidence contract without touching Meta, real accounts, real credentials, OAuth, live endpoints, publishing, external writes or deployment. It creates a deterministic, hash-bound synthetic evidence bundle and replays the CP56 read-only operator sequence as a local dry-run.

This is a structural verification unit only. A CP57 PASS proves that the local evidence schema, redaction guard, canonicalization, SHA-256 binding, GET-only method guard and zero-write interlock are internally coherent. It does not prove that any Meta credential, account, permission, capability, API version or endpoint is live or valid.

Facebook Page, Instagram Professional and Threads remain the only active lanes. LinkedIn remains held until production API access, X remains excluded while its API is paid, and Bluesky remains held until a later local ROI test passes.

## Exact CP56 binding

The CP57 receipt binds the exact CP56 contract through:

- `cp56_contract_id`
- `cp56_contract_hash`
- `validator_policy_sha256`
- platform and mode
- the exact ordered CP56 probe-class sequence

The CP56 receipt is revalidated before CP57 accepts it. CP57 refuses any CP56 receipt that pretends live evidence was already captured or that exposes live/network/account authority.

## Synthetic evidence bundle

CP57 materializes all nine evidence codes required by CP55/CP56, but each record is explicitly marked `SYNTHETIC_OFFLINE_ONLY` and `SYNTHETIC_VALIDATED`.

| Evidence code | CP57 synthetic content |
|---|---|
| `LIVE_TOKEN_DEBUG_REDACTED` | redacted synthetic credential-state fixture |
| `LIVE_ACCOUNT_IDENTITY_MATCH_REDACTED` | synthetic account-reference match fixture |
| `LIVE_PERMISSION_SET_EXACT` | synthetic non-live permission-set fixture |
| `LIVE_CAPABILITY_SET_EXACT` | synthetic non-live capability-set fixture |
| `LIVE_EXPIRY_STATE` | synthetic known-expiry fixture |
| `LIVE_READ_ONLY_RESPONSE_HASH` | SHA-256 of a synthetic GET-only response seed |
| `OPERATOR_TIMESTAMP_UTC` | caller-supplied RFC3339 UTC dry-run timestamp |
| `API_VERSION_PIN` | `TEST_API_VERSION_V1`, explicitly non-live |
| `ZERO_WRITE_CONFIRMATION` | local proof that network, queue mutation, publisher write and external write are false |

Every payload is canonicalized before hashing. The persisted CP57 receipt contains only canonical synthetic payloads plus their SHA-256 digests.

## Redaction and secret guard

The validator fails closed if a synthetic evidence payload includes a sensitive field name such as an authorization header, cookie, client secret, refresh credential, access credential, bearer credential or signing secret. It also rejects bearer-like credential material in string values.

This guard is intentionally stricter than the normal synthetic fixture generator. CP57 therefore exercises the failure mode that a future live evidence capture path must preserve: redact first, then canonicalize and hash; never persist raw secret material.

## Operator dry-run

For each CP56 probe class, CP57 creates one deterministic dry-run step with:

- method `GET` only;
- endpoint selector `SYNTHETIC_OFFLINE_ENDPOINT_ONLY`;
- no endpoint materialization;
- no secret-reference resolution;
- no network attempt;
- no external write;
- result `PASS_SYNTHETIC_SERIALIZATION_ONLY`.

The sequence is platform-native and preserves the CP56 probe classes for Facebook Page, Instagram Professional and Threads. Any method drift, endpoint drift, class drift, order drift or external-authority flag causes a HOLD.

## Kill switch and zero-write proof

The global kill switch remains engaged. CP57 cannot disengage it and does not create any unlock path. The synthetic zero-write evidence must assert all of the following:

- method allowlist is exactly `GET`;
- network attempt is false;
- queue mutation is false;
- publisher write is false;
- external write is false;
- global kill switch is engaged.

A CP57 PASS remains insufficient for pilot publication.

## Determinism and idempotency

Given the same exact CP56 contract, CP57 policy and operator dry-run timestamp, the generated fixture, evidence records, dry-run steps and final bundle hash are identical. The receipt ID is derived from the bundle hash, so duplicate compilation is deterministic and locally idempotent.

## Authority boundary

CP57 has zero authority for:

- real secret-reference resolution;
- environment or keychain reads;
- OAuth;
- real account lookup or connection;
- network access;
- publishing;
- queue/publisher external writes;
- deployment;
- paid services.

The source module contains no HTTP client dependency and no live probe execution function.

## Validation scope

The CP57 test suite verifies deterministic compilation, exact nine-code evidence coverage, canonical payload hashes, sensitive-material rejection, zero-write failure behavior, GET-only dry-run sequencing, receipt tamper detection, active/deferred platform canon, runtime kill-switch state and source-level absence of network/secret-resolution execution paths.

## Recovery and rollback

Failure is non-destructive. Discard the invalid synthetic bundle, keep the global kill switch engaged and return to the exact CP56 contract. No rollback mutation is required because CP57 performs no external action.

Repository rollback is the normal Git revert of the CP57 merge. No account, network, queue, publisher or deployment cleanup is needed.

## Pilot state after CP57

Pilot remains HOLD. CP57 does not authorize a live read-only probe and does not authorize account connection or publication. The next bounded unit is:

`CP58_META_PILOT_READINESS_AGGREGATOR_AND_LIVE_CONNECTION_AUTHORIZATION_GATE`

CP58 must remain fail-closed and should aggregate the exact CP50–CP57 evidence into a single pilot-readiness decision surface without connecting accounts or publishing.
