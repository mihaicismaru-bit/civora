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
- injectible Drive-first adapter contract with create-only uploads and full raw readback hashing
- restart-safe Drive checkpoints that never repeat a checkpointed upload
- append-only Artifact Registry and track-specific SSOT reconciliation proposals
- external bridge exchange plans containing only relative spool paths and non-sensitive metadata
- external Drive response ingestion with complete base64 readback verification
- expiring bridge-health challenge/response bound to exact connector and agent builds
- whitelisted read-only/observe capabilities with explicit no-shell and zero-write assertions
- fixed-operation HEALTH/DISCOVER_ARTIFACTS dispatcher with expiry, build and replay gates
- dispatcher-owned zero-click/zero-write safety responses and GET/HEAD-only discovery metadata
- same-extension-only MV3 message transport with restart-safe session replay claims
- bounded current-page snapshot responder with no click, submit or navigation capability
- deterministic post-commit extension/native build attestations with sorted SHA-256 file manifests
- same-source-head package pairing and fail-closed tamper/mixed-build verification
- attested runtime bootstrap that registers the fixed MV3 transport only after both component bytes
  and the durable pair receipt match the exact source head
- deterministic installation-bundle manifest and offline preflight with exact payload allowlisting,
  altered/extra-file rejection and explicit operator rollback guidance
- portable extracted-bundle preflight CLI and Windows CMD entrypoint that revalidate both component
  attestations, emit bounded success/failure receipts and leave installation explicitly `NOT_STARTED`
- exact-build installation authorization and state-transition validator that requires an external
  approval record and cannot execute installation or claim live health itself
- portable installation-authorization CLI that consumes only the preflight receipt and an externally
  supplied approval record, then emits a bounded plan or sanitized no-execution failure receipt
- portable observation/rollback CLI that revalidates the exact plan and consumes only bounded
  external operator observations, without executing or claiming installation success itself
- append-only handoff-chain verifier that recomputes the exact preflight, authorization plan,
  installation transition and live HEALTH receipt before admitting any benchmark execution
- two-track generic benchmark-admission gate that requires a fresh verified live handoff, binds both
  discovery commands to one build and health challenge, and cannot execute either command
- append-only benchmark discovery-evidence verifier that recomputes admission and both live responses,
  preserves explicit non-retrievable reasons and leaves retrieval and Draft traversal unclaimed

Still fail-closed / not implemented:

- direct native Google Drive adapter for unattended MCLENOVO operation
- live MCLENOVO health response observed through the trusted bridge transport
- approved Artifact Registry and SSOT proposal application
- CDP debugger fallback
- authorized authenticated live benchmark execution
- second-project generalization and v1.0 release-candidate receipt

The connector is therefore not `VERIFIED_FUNCTIONAL`.

## Offline handoff preflight

After extracting an attested installation bundle, run `CONTROL\\VERIFY_OFFLINE.cmd`. The command
only reads the extracted `PAYLOAD` and `CONTROL` trees, verifies every byte and emits one JSON
receipt. It does not install an extension, enable native messaging, open MySMIS or write a receipt
to disk. A pass status is `INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED`; any other status is
a stop condition.

An externally issued, exact-build authorization can then be validated without starting installation:

```sh
node native/install-authorization-cli.mjs \
  --preflight /path/to/preflight-receipt.json \
  --authorization /path/to/external-authorization.json
```

The command only reads those two JSON files. It emits a non-executing bounded plan on success or a
sanitized `INSTALL_AUTHORIZATION_REJECTED_NO_EXECUTION` receipt on failure; it does not write files,
load the extension, start the agent, enable native messaging or access MySMIS.

After an external operator acts, the observation can be validated separately:

```sh
node native/install-observation-cli.mjs \
  --current /path/to/authorized-plan.json \
  --observation /path/to/external-observation.json
```

This command also reads only two JSON files. It verifies the plan ID, exact-build bindings, expiry,
zero-write controls and observation shape before emitting an allowed state transition. It cannot
perform the observed action or turn an installation observation into live MySMIS evidence.

The final live handoff evidence can be checked as one immutable ordered chain:

```sh
node native/handoff-chain-cli.mjs --chain /path/to/ordered-handoff-chain.json
```

The command reads exactly one JSON file and recomputes all derived receipts. It accepts only an
eight-record exact-build chain ending in authenticated `LIVE_BRIDGE_TOOL` HEALTH. A valid result is
still `PENDING_BENCHMARKS`; it cannot perform installation, traverse a project or claim functional
acceptance.

After live handoff verification, a separate non-executing admission CLI can prepare the two generic
benchmark commands:

```sh
node native/benchmark-admission-cli.mjs \
  --chain /path/to/ordered-handoff-chain.json \
  --benchmarks /path/to/two-track-spec.json
```

The spec supplies one opaque project selector and nonce for each of `IMPLEMENTATION` and `WRITING`.
Project identifiers are data, not runtime code. The CLI rejects stale HEALTH, mixed builds, duplicate
tracks/selectors and sensitive fields, and emits commands only; it cannot dispatch or traverse them.

The Drive contract never directly edits an Artifact Registry or SSOT. It persists a
`PENDING_HUMAN_REVIEW` proposal only after the uploaded bytes have been read back in full and match
the local SHA-256 and size. WRITING and IMPLEMENTATION proposals have distinct targets.

## External Drive exchange

The bridge-facing CLI emits a create-only request when no response exists, then resumes the same
Drive state machine after the external orchestrator supplies the observed file ID, credential-free
Drive URL and complete raw readback bytes:

```sh
node native/external-drive-cli.mjs \
  --receipt /path/to/spool/receipts/event.json \
  --spool /path/to/spool \
  --exchange /path/to/spool/external-drive-exchange
```

The persisted request contains a spool-relative object path, never the absolute local path. It
contains no browser/session material and authorizes no MySMIS action.

## Bridge health contract

The health challenge is short-lived, nonce-bound and tied to the exact connector Git SHA. A valid
response may declare only the known read-only or observation capabilities and must prove Manifest
V3 extension plus native-agent readiness. It cannot request a remote shell or any MySMIS write.
Offline fixtures validate the contract but never set `liveVerified`; only a caller-observed
`LIVE_BRIDGE_TOOL` response can do so.

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
