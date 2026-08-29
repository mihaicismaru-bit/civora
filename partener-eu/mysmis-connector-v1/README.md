# MySMIS Connector v1

Capability-gated, read-only connector skeleton for authenticated Chrome/Edge sessions.

This unit implements generic DOM artifact inventory, least-invasive candidate classification,
download observation metadata, URL redaction, and deterministic offline regression fixtures for
the two acceptance tracks:

- WRITING: 367944 / AI4WORK STEP
- IMPLEMENTATION: 310224

The extension never clicks a control. Save, Submit, Delete, Sign, Upload and Modify controls are
classified as blocked. POST-based exports remain blocked unless an independent evidence record
proves the operation read-only; even then, automated invocation requires a separate authorization
gate. The connector does not read or persist request headers, cookies, browser storage, passwords,
MFA data or tokens.

## Run the deterministic unit

```sh
npm test
```

## Current capability state

Implemented in this unit:

- Manifest V3 skeleton and generic page inventory
- direct-link, route, embedded-body and UI-download candidate classification
- least-invasive acquisition ordering without execution
- `chrome.downloads` observation
- response metadata observation using response headers only
- sensitive URL query redaction
- fixtures derived from persisted Drive evidence for 310224 and 367944
- local/manual-download intake agent with regular-file and symlink gates
- streaming SHA-256 plus magic/MIME/size validation
- content-addressed spool with atomic object, index, receipt and checkpoint writes
- idempotent replay, same-byte deduplication and logical artifact versioning

Still fail-closed / not implemented:

- Drive upload adapter and post-upload SHA-256 readback validation
- Artifact Registry and SSOT reconciliation
- CDP debugger fallback
- authorized authenticated live benchmark execution
- second-project generalization and v1.0 release-candidate receipt

The connector is therefore not `VERIFIED_FUNCTIONAL`.

## Manual intake CLI

The CLI consumes only a completed local download. It does not connect to MySMIS or the network:

```sh
node native/cli.mjs \
  --source /path/to/download.pdf \
  --spool /path/to/spool \
  --project 310224 \
  --track IMPLEMENTATION \
  --kind CONTRACT \
  --name "Financing contract" \
  --filename contract.pdf \
  --mime application/pdf
```
