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
- append-only representative implementation-artifact verifier that binds a safe live candidate to
  local intake, Drive readback bytes and an untouched reconciliation proposal without executing retrieval
- non-executing live restart/replay verifier that proves same-byte dedup without another upload and
  changed-byte next-version persistence with complete Drive readback and zero Registry/SSOT mutation
- Drive-synced command mailbox and bounded local poller with create-only command files, atomic claims,
  exact-build/expiry/nonce validation, restart ambiguity rejection and result-first replay deduplication
- installed-extension loopback binding with a fixed `127.0.0.1:43127` origin, exact installed extension
  identity, externally supplied exact-build configuration and a 30-second MV3 alarm wake-up
- live current-page dispatcher that reads only the active MySMIS DOM snapshot, visibly binds the opaque
  project selector, sanitizes all persisted URLs and reuses restart-safe session replay protection
- deterministic MCLENOVO runtime handoff plan and fixed local composition from Drive mailbox through
  the one-command loopback broker to the installed extension, with no persisted absolute mailbox path
- internal extension options page that stores a configuration only after exact extension/build/pair
  checks and a Web Crypto SHA-256 verification of its canonical configuration identity

Still fail-closed / not implemented:

- externally observed exact-build installation and runtime start on MCLENOVO
- live MCLENOVO health response observed through the trusted bridge transport
- approved Artifact Registry and SSOT proposal application
- CDP debugger fallback
- authorized authenticated live benchmark execution
- second-project generalization and v1.0 release-candidate receipt

The connector is therefore not `VERIFIED_FUNCTIONAL`.

## Drive command mailbox

`native/drive-command-mailbox.mjs` operates only inside an explicit absolute folder already synced by
Google Drive for desktop. It creates `COMMAND_INBOX`, `PROCESSING`, `RESULT_OUTBOX`, `ARCHIVE` and
`STATE`, then accepts create-only `<sha256>.command.json` files for `HEALTH` or
`DISCOVER_ARTIFACTS`. The command ID must match its filename and the configured Git source head,
nonce, five-minute expiry and zero-write restrictions must all validate before dispatch.

The poller accepts only an injected fixed dispatcher function; it cannot load an adapter path or
execute a process, script or shell. A claimed command is never replayed after an ambiguous restart.
Completed results remain `liveEvidenceAccepted: false` until their full Drive readback and protocol
evidence are independently validated. The mailbox remains a transport component rather than live
acceptance evidence until the installed MCLENOVO runtime is externally observed and its result is read
back from Drive.

## Installed extension loopback binding

The extension can poll only `http://127.0.0.1:43127`, using `chrome.alarms` at the fixed MV3 minimum
period of 30 seconds. The broker also binds only to `127.0.0.1`, permits one outstanding command and
requires the exact installed Chrome/Edge extension ID on both request and result. Neither side exposes
a general URL, process, script or shell primitive.

The binding is disabled by default. It performs zero broker requests until `chrome.storage.local`
contains the exact `mysmisLoopbackRuntimeV1` configuration produced by the external installation
handoff. That record must bind the same 40-character source head for extension and agent, the installed
extension ID, fixed broker origin, pair ID and configuration ID. Missing, broadened, mixed-build or
identity-mismatched records remain disabled and emit only a sanitized session status.

For an admitted command, the runtime reads only the active MySMIS tab through the existing content
script. It never clicks or navigates. `HEALTH` claims an authenticated context only when a non-login
page visibly contains a six-digit project code. `DISCOVER_ARTIFACTS` additionally requires the opaque
requested selector to be visible in the current snapshot, sanitizes page and element URLs again, and
returns only GET observation metadata. The loopback acknowledgement remains
`liveEvidenceAccepted: false` until the agent persists the result and an independent Drive readback
verifier accepts the complete chain.

`native/mclenovo-runtime.mjs` composes the existing mailbox and broker directly; it does not load a
module name from the plan or expose a command runner. Its handoff plan contains no mailbox path. At
runtime the absolute locally synced Drive path is supplied separately and is never returned by status
or result receipts. The fixed CLI accepts only `--plan` and `--mailbox-root`, starts no child process,
and shuts down the poller and loopback listener on SIGINT/SIGTERM.

The extension options page has one bounded manual action: paste the plan's `extensionConfig` object.
It performs no network request and stores nothing unless the canonical SHA-256 configuration ID,
source/agent head, pair ID, installed extension ID and fixed origin all verify. This offline composition
test is not an installation observation and cannot be promoted to live bridge evidence.

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
