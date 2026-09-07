# CP77 — Live Read-Only Probe Authority Lease Terminal Tombstone Recovery Journal Corruption Rejection Dry-Run v1

## Status

`PASS_CP77_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION_DRY_RUN_LOCAL_ONLY_FAIL_CLOSED_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD`

Global control checkpoint remains **CP58**. CP77 is a bounded recovery-safety validation milestone only; it does not promote the control plane and does not confer runtime authority.

## Purpose

CP77 extends the CP76 crash-consistency model with a deterministic, synthetic recovery-journal validator. It proves that structurally valid CP76 recovery journals are accepted as positive controls and that eight bounded corruption classes are rejected fail-closed before any recovery effect can occur.

## Exact parent binding

CP77 is SHA-256 bound to the exact CP76 contract, CP76 dry-run, lease identity/hash, CP76 policy, runtime policy and current module registry. The parent CP76 crash model remains unchanged.

## Positive-control corpus

All **12** CP76 crash-consistency cases are converted into canonical synthetic journals: four recovery cases × three crash points. Every positive-control journal contains exact CP76 transaction, baseline, recovery-result, phase/record and lease bindings, with canonical-JSON SHA-256 payload and journal seals.

## Corruption corpus

Exactly eight corruption classes are injected deterministically:

1. malformed schema version;
2. missing required field;
3. duplicate conflicting transaction entry;
4. illegal phase ordering;
5. baseline hash mismatch;
6. payload hash tamper;
7. invalid commit-marker parent binding;
8. terminal binding mismatch.

Every corruption must produce its exact expected HOLD reason. Any accepted corruption, unexpected rejection reason, baseline change, recovery effect, storage mutation or runtime mutation fails CP77 closed.

## Safety boundary

- local synthetic model only;
- method allowlist remains `GET` only;
- Facebook Page, Instagram Professional and Threads remain the only active lanes;
- LinkedIn remains held until production API access;
- X remains excluded while API access is paid;
- Bluesky remains held until a local ROI test passes;
- no real account connection;
- no secret resolution, ENV/keychain reads or OAuth;
- no social API/network traffic or live probes;
- no publishing or external/storage writes;
- no deploy and no paid services;
- global kill switch remains engaged;
- no control-plane promotion and no runtime authority activation.

## Changelog

- Added M46 recovery-journal corruption rejection engine.
- Added canonical synthetic journal construction and SHA-256 sealing.
- Added positive controls for all 12 CP76 crash cases.
- Added deterministic eight-class corruption injector and exact HOLD verification.
- Added duplicate-conflict ledger rejection before recovery execution.
- Added baseline-preservation and zero-recovery-effect invariants.
- Added CP77 policy, tests, registry entry and product-layout lock.

## Decisions

- Corruption validation remains entirely in-house and dependency-free.
- Semantic mutations are re-sealed where appropriate so rejection tests validate semantics rather than relying only on a broken outer digest.
- Duplicate conflicting transaction IDs are rejected at the ledger boundary before journal recovery validation.
- CP77 PASS is evidence of fail-closed recovery-journal handling only; it is not authorization to connect, probe, publish or deploy.

## Blockers preserved

`HOLD_REAL_EXTERNAL_AUTHORIZATION_RECEIPT_NOT_INGESTED`, `HOLD_SECRET_REFERENCE_NOT_RESOLVED`, `HOLD_REAL_ACCOUNT_NOT_CONNECTED`, `HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED`, `HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED`, `HOLD_PILOT_PUBLISH_NOT_AUTHORIZED`, `HOLD_CP77_RECOVERY_JOURNAL_SOURCE_SYNTHETIC_ONLY`, `HOLD_CP77_CORRUPTION_REJECTION_PASS_IS_NOT_RUNTIME_AUTHORITY`.

## Rollback

Rollback target is **CP76**. Removing the CP77 module, policy, tests, docs and M46 registry entry returns the project to the validated CP76 crash-consistency state without touching runtime policy, account configuration, external systems or public content.

## Next unit

`CP78_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION_DRY_RUN`

CP78 is named only; it is not started by CP77.
