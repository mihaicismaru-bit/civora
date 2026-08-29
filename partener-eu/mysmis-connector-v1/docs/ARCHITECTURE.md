# Architecture and gates

1. The authenticated browser remains the MySMIS authentication boundary.
2. The content script serializes artifact-bearing DOM elements only and performs no click.
3. Core discovery inventories all exposed candidates and blocks write-intent controls.
4. The background worker observes browser-created downloads and response metadata. It never asks
   for request headers and persists no Authorization or Cookie material.
5. Acquisition chooses the least invasive viable strategy: safe direct binary URL, browser download
   observation, proven read-only UI download, route metadata, manual intake, then optional CDP.
6. POST and ambiguous actions fail closed. CDP and automated traversal remain disabled until the
   persisted authorization/compliance gate explicitly permits them.
7. The native intake agent accepts completed user-triggered/manual downloads, rejects symlinks and
   changing files, hashes bytes as a stream, validates MIME/magic/size, and commits a
   content-addressed object plus atomic restart checkpoint, receipt and index.
8. Same bytes deduplicate globally; changed bytes under the same logical artifact create a new
   version. The source download remains unchanged and its local path is not persisted.
9. The Drive-first contract calls an injected create-only adapter with the SHA-256 as an idempotent
   content key, records the returned file ID before readback, then verifies the complete remote bytes
   against SHA-256 and size. Its restart checkpoint prevents a second upload after an interrupted
   run; the production adapter must make the content-key operation idempotent across network faults.
10. Only a `PENDING_HUMAN_REVIEW` append-only proposal is created after successful readback. The
    connector never applies the proposal itself, never promotes project facts, and targets separate
    Artifact Registry and SSOT names for WRITING and IMPLEMENTATION.
11. When Drive runs outside the native process, a file exchange adapter emits a create-only plan
    with a spool-relative object path. The external response contains the observed Drive file ID and
    complete base64 readback; those bytes enter the same hash/checkpoint/proposal state machine.
    Absolute source paths and authentication material never enter the exchange.
12. Bridge health uses a short-lived nonce challenge bound to the exact connector and agent builds.
    The response is restricted to a fixed allowlist of read-only/observe capabilities and explicit
    MV3/native-agent readiness. Offline contract validation cannot be promoted to live health;
    arbitrary shell, write capabilities, stale responses and sensitive fields fail closed.
13. `DISCOVER_ARTIFACTS` is bound to the exact build, bridge-health challenge, benchmark track and
    current authenticated page. It accepts only current-page DOM plus observed download/response
    metadata for GET/HEAD. The local validator recomputes the inventory, requires the reported count
    to match, and records an explicit reason for every non-retrievable candidate. Clicks, route
    mutations, CDP attachment, shell actions and MySMIS writes fail closed. Offline fixtures exercise
    the same envelope but can never yield live evidence.
14. The bridge dispatcher has exactly two operations: `HEALTH` and `DISCOVER_ARTIFACTS`. It rejects
    arbitrary operation names, executable/script payload fields, remote-shell material, stale or
    premature commands, build mismatch and replayed IDs before invoking a handler. The dispatcher
    constructs all safety assertions itself; handlers can only return bounded health state or a
    current-page snapshot plus GET/HEAD observation metadata.
15. The MV3 internal transport accepts command messages only when `sender.id` equals the running
    extension ID. Replay claims contain only command ID and expiry and are serialized into
    `chrome.storage.session`, so service-worker restart cannot replay a command. The content script
    exposes a current-page snapshot responder only; it reads bounded attributes and contains no
    click, submit or navigation call. No native messaging, external-connect, debugger or CDP
    permission is introduced by this transport.
16. Build attestation is an external post-commit artifact, avoiding a circular self-hash. An explicit
    Git source head is bound to sorted runtime-file path, size and SHA-256 records for the extension
    and native agent separately. Both component attestations must use the same source head before
    they receive a pair ID. Placeholder heads, changed bytes, missing/extra paths and mixed builds
    fail closed. Tests, evidence and documentation are not silently packaged as runtime files.

No project code appears in the discovery implementation. Project numbers occur only in fixtures and
acceptance evidence.
