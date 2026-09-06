# CP56 — META LIVE READ-ONLY PROBE RUNBOOK + EVIDENCE CAPTURE CONTRACT v1

## Result

`PASS_CP56_LIVE_READ_ONLY_PROBE_RUNBOOK_CONTRACT_LOCAL_ONLY / HOLD_PILOT_CP57_META_READ_ONLY_EVIDENCE_VALIDATOR_AND_SYNTHETIC_FIXTURE_PACK`

CP56 defines the deterministic operator runbook and immutable evidence schema for a future Meta read-only verification. It does not execute that verification. The unit is contract-only, local-only and bound to the exact CP55 read-only gate and runtime policy.

## Scope

Active lanes remain exactly:

- `FACEBOOK_PAGE`
- `INSTAGRAM_PROFESSIONAL`
- `THREADS`

LinkedIn remains held until production API access exists. X remains excluded while its required API access is paid. Bluesky remains held until a later local ROI test passes.

## Exact lineage and kill switch

A CP56 runbook receipt is valid only when the CP55 gate validates, its `gate_id`/`gate_hash` and CP54 transport-twin lineage are preserved, and the current runtime-policy SHA-256 exactly matches the SHA-256 bound by CP55. The global kill switch must remain engaged. CP56 contains no unlock, override or automatic disengagement path.

The future probe method class is restricted to semantic `GET`. `POST`, `PUT`, `PATCH` and `DELETE` are fail-closed. CP56 does not materialize a live endpoint, resolve a secret reference, read ENV/keychain, perform OAuth, make a network request, look up or connect a real account, publish, write externally or deploy.

## Evidence capture schema

The nine CP55 requirements are promoted into an explicit immutable schema while remaining `NOT_CAPTURED` in CP56:

1. `LIVE_TOKEN_DEBUG_REDACTED` — redacted metadata hash only.
2. `LIVE_ACCOUNT_IDENTITY_MATCH_REDACTED` — redacted identity hash only.
3. `LIVE_PERMISSION_SET_EXACT` — sorted exact string set.
4. `LIVE_CAPABILITY_SET_EXACT` — sorted exact string set.
5. `LIVE_EXPIRY_STATE` — enum plus optional UTC expiry.
6. `LIVE_READ_ONLY_RESPONSE_HASH` — SHA-256 of the redacted response.
7. `OPERATOR_TIMESTAMP_UTC` — operator capture time in UTC.
8. `API_VERSION_PIN` — non-secret exact version string.
9. `ZERO_WRITE_CONFIRMATION` — boolean attestation bound to a local audit SHA-256.

Missing evidence is never represented as success, zero, empty entitlement or inferred capability. CP56 cannot mark any slot captured.

## Redaction and persistence rules

Redaction must occur before hashing or persistence. Raw response bodies, raw headers, secret material, token fragments and raw account identifiers are forbidden from persistence. Sensitive key families such as `access_token`, `authorization`, `client_secret`, `refresh_token`, cookies and session material are explicitly deny-listed. The future response evidence is the hash of the redacted representation, not the raw response.

## Future operator procedure

The contract fixes the procedure order: validate CP55 exact binding; reconfirm runtime policy and kill switch; select one active lane; pin the API version; later materialize the minimum read-only endpoint; later resolve the secret reference only ephemerally; execute only `GET`; redact before persistence; hash the redacted response; capture all required evidence atomically; verify a zero-write local audit; invalidate the evidence on any method, write or lineage drift.

Every step is tagged `may_execute_in_cp56=false`. The procedure is therefore documentation and validation structure only, not authority to execute a live probe.

## Recovery and rollback

Abort and invalidate the future evidence on a mutating method, unexpected write evidence, kill-switch drift, API-version drift, permission/capability drift, identity mismatch, redaction failure, or hash/lineage mismatch. The rollback target is CP55. Throughout recovery the kill switch stays engaged, secret material is not persisted, no account connection is retained, and publishing/deployment remain disabled.

## Explicit non-authority

CP56 grants zero live entitlement, live connection or pilot-publish authority. It performs zero secret resolution, environment/keychain reads, OAuth, real account lookup, account connection, network calls, publishing, external writes or deployment. No paid service is introduced.

## Next unit

`CP57 — META READ-ONLY EVIDENCE VALIDATOR + SYNTHETIC FIXTURE PACK v1` will implement a fully local validator for CP56-shaped evidence using synthetic fixtures only. It will test atomic completeness, redaction, hashing, zero-write proof and lineage drift without resolving real secrets, contacting Meta, connecting accounts, publishing or deploying.
