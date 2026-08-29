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

Still fail-closed / not implemented:

- native acquisition agent and byte spool
- SHA-256 binary validation and Drive readback validation
- Drive-first persistence, Artifact Registry and SSOT reconciliation
- CDP debugger fallback
- authorized authenticated live benchmark execution
- second-project generalization and v1.0 release-candidate receipt

The connector is therefore not `VERIFIED_FUNCTIONAL`.
