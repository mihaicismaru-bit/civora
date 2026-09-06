# CP49 — Identity Runtime Activation + QA Exact-Binding Gate v1

## Status

`PASS_CP49_IDENTITY_RUNTIME_ACTIVATION / HOLD_PILOT_META_ADAPTER_AND_OPERATOR_PROVISIONING`

CP49 activates the CP48 `EDITORIAL_LEDGER_V2` contract at the local M06 visual-render and M07 visual-QA boundary. It does not recover or claim historical CP29 byte equivalence. The supersession is versioned: CP29/`EDITORIAL_LEDGER_V1` remains historical evidence; CP48 defines V2; CP49 makes V2 the canonical local runtime identity gate.

## Changelog

- Added `public_presence_os.identity_runtime.render_visual_v2` as the canonical CP49 local M06 entrypoint.
- Added `public_presence_os.identity_runtime.audit_visual_v2` as the canonical CP49 local M07 entrypoint.
- Added a renderer-contract drift gate covering render schema, palette, grid, Marginalia hooks, procedural microcopy, and font role family/style contract.
- Bound runtime acceptance to the exact CP48 font profile scope, four role SHA-256 values, font-binding digest, and identity-profile digest.
- Forbade caller substitution of alternative "expected" font hashes.
- Recomputed V2 render key and asset id after exact activation, so manifest identity metadata and deterministic identity binding agree.
- Superseded only the legacy `HOLD_IDENTITY_EQUIVALENCE` in QA, and only when the exact V2 manifest gate passes. Every unrelated QA hold is preserved.
- Preserved CP40/CP41 historical entrypoints unchanged for checkpoint reproducibility.
- Advanced `module_registry.json` to CP49 for M06, M07, and M18.
- Added `identity_runtime_policy.json` and CP49 regression tests.

## Canonical decisions

1. `EDITORIAL_LEDGER_V2` is the only identity accepted by the CP49 canonical runtime facade.
2. Exact local font bytes remain mandatory. The repository continues to package no font binaries.
3. A manifest boolean is not identity authority by itself. Identity passes only when name, font-binding digest, identity-profile digest, canonical flag, and renderer-contract drift gates all pass.
4. CP49 does not mutate the historical CP40/CP41 source semantics. The new facade is the explicit versioned activation boundary.
5. Facebook Page, Instagram Professional, and Threads remain the only active lanes. LinkedIn remains production-API gated; X remains excluded while its API is paid; Bluesky remains `HOLD_ROI`.
6. CP49 has no queue, publisher, network, real-account, public-publish, or deploy authority.

## Validation contract

Required CP49 regression coverage:

- renderer grammar matches the CP48 V2 identity contract;
- exact V2 font binding produces deterministic V2 manifests;
- exact V2 text-card QA removes the legacy identity hold and produces a downstream-valid M07 PASS report;
- noncanonical local font bindings fail closed;
- caller-supplied noncanonical expected hashes fail closed;
- manifest identity tamper fails QA;
- global runtime kill switch, network-off, publish-off, account-off, and deploy-off remain unchanged.

Full repository CI remains the promotion gate before merge.

## Blockers / holds after CP49

- `HOLD_OPERATOR_EXACT_LOCAL_FONT_FILES_REQUIRED`: production-like local rendering requires operator-provided font files matching the four CP48 SHA-256 values. No font bytes are bundled.
- `HOLD_META_API_ADAPTER_NOT_IMPLEMENTED`: the active Facebook Page / Instagram Professional / Threads lanes still lack the canonical free-API request adapter layer.
- Real credentials/accounts remain intentionally unconnected; network publishing and deployment remain disabled by policy.

These holds do not invalidate CP49. They keep the pilot fail-closed beyond this unit.

## Safety state

- public publishing: OFF
- real account connection: OFF
- external network publishing: OFF
- publisher external writes: OFF
- deploy: OFF
- paid services introduced: NONE
- global kill switch: ENGAGED

## Rollback

Rollback target: CP48 canonical state. Remove the CP49 facade/policy/test/doc changes and restore the CP48 module registry statuses. No external rollback is required because CP49 performs no account, network, publication, or deployment mutation.

## Next exact granular unit

`CP50 — META FREE-API ADAPTER CONTRACT + OFFLINE REQUEST COMPILER v1`

Scope: define deterministic, token-free, network-free request envelopes and capability gates for Facebook Page, Instagram Professional, and Threads only; keep LinkedIn/X/Bluesky gating unchanged; no real API calls, credentials, account connection, publishing, or deploy.
