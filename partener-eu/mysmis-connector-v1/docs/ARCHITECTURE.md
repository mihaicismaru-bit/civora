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

No project code appears in the discovery implementation. Project numbers occur only in fixtures and
acceptance evidence.
