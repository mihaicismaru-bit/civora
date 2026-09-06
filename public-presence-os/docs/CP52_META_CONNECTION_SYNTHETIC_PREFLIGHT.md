# CP52 — Meta Connection Preflight + Synthetic Provisioning Readback v1

## Scope

CP52 binds the CP50 offline request compiler to the CP51 local connection-profile vault and proves that the two boundaries agree before any live connection work is permitted.

The active lanes remain exactly Facebook Page, Instagram Professional and Threads. LinkedIn remains gated on production API access, X remains excluded while its API is paid, and Bluesky remains `HOLD_ROI`.

## Inputs

A CP52 run requires all of the following, exact and hash-bound:

- a valid CP50 `OfflineRequestPlan`;
- a valid CP51 `ConnectionProfile`;
- the CP51 `VaultReceipt` produced when that profile was staged;
- an exact readback of the stored profile from the local SQLite reference vault;
- complete offline capability evidence already accepted by CP51.

No literal destination ID, literal API version, access token, account ID or live entitlement is accepted or derived.

## Binding checks

The preflight fails closed unless these values match exactly between the CP50 plan and CP51 profile:

- platform;
- publication mode;
- authentication-reference kind;
- required permissions;
- required capabilities.

The preflight additionally binds the request-plan hash, profile hash, vault event hash and exact stored-profile payload hash.

## Synthetic provisioning readback

The readback proves only that the locally staged profile is the same immutable profile that the request plan expects. Its entitlement state is always `SYNTHETIC_CONTRACT_ONLY`.

A successful result is `PASS_SYNTHETIC_PREFLIGHT_ONLY`. That result explicitly means:

- no secret was resolved;
- no environment or OS-keychain secret was read;
- no real destination was observed;
- no literal API version was observed;
- no network call was attempted;
- no account was connected;
- no publish was attempted;
- no external write or deploy occurred;
- live entitlement is still unverified;
- live reverification remains mandatory.

A synthetic PASS does **not** mean the system is ready to publish.

## Local ledger

CP52 can record the deterministic preflight receipt in a local SQLite ledger. Receipt records are immutable, the event log is append-only, and `request_id` is idempotent. Reusing a request ID with different event content fails closed.

The receipt and ledger do not store credential material.

## Authority boundary

CP52 grants only local preflight, local readback and local receipt-record authority. It grants no secret-resolution, network, account-connection, publishing, external-write or deploy authority. The global kill switch remains required and engaged.

## Completion criterion

CP52 is complete when the source, policy, tests, product-layout validation and reproducible package all pass while proving exact CP50↔CP51 binding and zero external action.

## Next granular unit

`CP53_META_OPERATOR_PROVISIONING_PACKET_OFFLINE_CHECKLIST`

CP53 should convert the now-validated synthetic boundary into an operator-facing provisioning packet and deterministic offline checklist for future Meta account connection. It must still avoid secret resolution, real-account connection, network calls, publishing and deploy.
