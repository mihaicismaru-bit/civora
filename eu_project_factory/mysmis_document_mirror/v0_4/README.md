# MySMIS Document Mirror v0.4

Status: **IMPLEMENTED CORE / LOCAL AUTHENTICATED RUN REQUIRED**

This unit is the read-only acquisition layer required by `CP-310224-DEEP-EXPORT-INGESTED-007`.

## Scope

- canonicalize MySMIS URLs before queueing so pagination/query combinations do not explode into hundreds of duplicate routes;
- resolve direct same-origin download candidates only;
- prefer candidate filenames from the persisted 310224 P0 queue;
- require SHA-256 + body review before any Project SSOT promotion;
- create machine-readable mirror receipts;
- preserve fail-closed behavior when MySMIS exposes a JS/button-only download action.

## Safety boundary

The v0.4 core does **not** click MySMIS buttons, submit forms, upload, sign, delete, save, or modify any server-side state. A missing direct GET URL becomes `BLOCKED_NO_DIRECT_GET`, not an implicit click.

## Current P0 queue

1. Signed financing contract body from `DOSAR_CONTRACT`.
2. Act Additional 1 accepted chain.
3. Notification 2 accepted body.
4. Notification 3 accepted body.
5. Notification 4 accepted/final body.
6. Monitoring plan body.
7. Report Progress 1 final body.

## Validation

`mirror_core.test.mjs` covers canonical route deduplication, preservation of report snapshot identity, same-origin GET gating, filename ranking, and fail-closed receipt semantics.

## Execution boundary

The next runtime step requires the user's authenticated local Edge/MySMIS session. The browser adapter must use this core and the persisted queue, download/hash recovered binaries locally, export a receipt, then archive binaries + receipt in Google Drive before reconciliation.

No merge/canonicalization should occur until the exact branch head is validated.
