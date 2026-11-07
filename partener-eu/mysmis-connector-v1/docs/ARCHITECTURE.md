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
17. The offline/native runtime bootstrap verifies both component byte sets against their
    attestations, recomputes the same-source-head pair, and validates the durable pair receipt before
    it creates a dispatcher or registers an MV3 listener. Missing receipts, changed bytes, mixed
    heads, forged pair IDs and unsafe acceptance claims fail before side effects. The resulting
    transport remains extension-internal and exposes only `HEALTH` and `DISCOVER_ARTIFACTS`; it does
    not enable native messaging or establish live MySMIS access.
18. The installation-bundle manifest is derived only after both exact-head component attestations
    and their durable pair receipt verify. It contains the deduplicated union of runtime allowlists,
    with path, size, SHA-256 and component targets. Offline preflight rejects missing, changed,
    duplicate, symbolic-link or extra payload files. Package construction performs no browser
    installation, native-messaging enablement, shell execution or MySMIS access and includes an
    explicit bounded-install gate and rollback procedure.
19. The portable installation-attempt preflight consumes only a freshly extracted bundle. It
    requires an exact six-file `CONTROL` set, rejects symbolic links and special files, rehashes the
    entire deduplicated payload, then separately revalidates the extension and native-agent
    attestations plus the pair receipt. Its CLI emits a bounded machine-readable receipt containing
    no absolute path or exception message. Success still records installation as `NOT_STARTED` and
    rollback as `NOT_REQUIRED`; failure cannot trigger installation, browser control, native
    messaging, MySMIS access or a retry with changed bytes.
20. Installation authorization is a separate, externally supplied record bound to the exact Git
    head, pair ID, manifest digest and preflight attempt. It expires within 30 minutes and permits
    only loading the unpacked extension, starting the local agent and running live HEALTH with an
    operator present. The validator cannot create approval evidence or execute these operations.
    State transitions accept only bounded local-operator observations, keep MySMIS access and
    native messaging disabled, never promote installation into live evidence, and require complete
    receipt-preserving rollback after a recorded failure.
21. The portable installation-authorization CLI accepts exactly two local JSON inputs: the bounded
    preflight receipt and externally supplied authorization. It performs no installation, browser
    control, agent start, native-messaging enablement, shell execution or MySMIS access. A valid
    record produces only an `AUTHORIZED_NOT_STARTED` plan; invalid arguments, inaccessible inputs,
    malformed JSON, expired approvals, binding errors and digest mismatches produce a sanitized
    no-execution receipt without paths, approval contents or exception messages.
22. The portable observation/rollback CLI revalidates the cryptographic plan ID, exact source head,
    pair, manifest, authorization digest, expiry and all zero-write controls before consuming one
    externally supplied operator observation. It accepts only observed bounded success, failure or
    complete receipt-preserving rollback. It has no mechanism to perform those actions and cannot
    promote any resulting state to live HEALTH or functional MySMIS acceptance.
23. The handoff-chain verifier accepts exactly eight append-only records in the prescribed order:
    preflight, external authorization, derived plan, external installation observation, derived
    installed state, HEALTH challenge, bridge response and live HEALTH receipt. It recomputes the
    plan, installation transition and HEALTH receipt against one exact source head, enforces
    monotonic bounded timestamps, authenticated MySMIS runtime presence and zero writes, and rejects
    offline, reordered, mixed-build, expired, sensitive or tampered evidence. Even a valid chain is
    only `PENDING_BENCHMARKS`; the verifier has no execution primitive and cannot claim functional
    acceptance.
24. Benchmark admission is a separate project-neutral step. It requires the verified handoff chain
    to end in fresh authenticated live HEALTH, then consumes exactly one opaque selector for each
    distinct `IMPLEMENTATION` and `WRITING` track. Both generated `DISCOVER_ARTIFACTS` commands share
    the same exact source head and health challenge and retain current-page, GET/HEAD, zero-click,
    zero-route-mutation, zero-write and no-shell restrictions. The gate emits commands but contains
    no dispatcher, browser or network primitive; project identifiers remain input data and never
    appear in runtime source.
25. Benchmark evidence verification is append-only and non-executing. It recomputes the exact
    handoff-bound admission and both `LIVE_BRIDGE_TOOL` discovery responses, requires one distinct
    track per response on the same build and health challenge, and locally rebuilds every candidate
    inventory with explicit non-retrievable reasons. Passing discovery remains pending artifact
    retrieval, Draft traversal, live resume, dedup/versioning and second-project generalization.
26. Representative implementation-artifact verification is also append-only and non-executing. It
    binds one externally observed `LIVE_BRIDGE_TOOL` retrieval to a safe retrievable GET/HEAD
    discovery candidate, the exact local intake receipt, the deterministic Drive sync receipt and
    untouched reconciliation proposal. It rehashes the complete raw Drive readback bytes and
    requires zero MySMIS, Registry and SSOT mutations. Passing this gate still leaves live restart,
    dedup/versioning, Draft traversal/export and both generalization branches pending.
27. Restart, replay, deduplication and versioning evidence is verified without execution. A live
    restart observation must bind to the exact representative artifact, source head and health
    challenge, prove recovered state and zero adapter calls during same-byte replay, and reproduce
    the original intake/sync identities and Drive file. Changed bytes must create exactly the next
    logical version, a distinct deterministic sync and a complete matching Drive readback while the
    Registry/SSOT proposal remains append-only and mutation-free. Passing still leaves WRITING
    Draft/export and second-project generalization pending.
28. The Drive-synced command mailbox is a bounded native-agent component. It recognizes only
    create-only SHA-256-named `HEALTH` and `DISCOVER_ARTIFACTS` files, atomically moves them into a
    processing queue, validates exact build, ID/filename binding, nonce, expiry and zero-write
    restrictions, then invokes only an injected fixed dispatcher. Durable claim files prevent two
    pollers from winning concurrently; a completed result suppresses replay and an expired
    in-flight claim is rejected as ambiguous instead of being dispatched again. Results are written
    create-only before archival and remain explicitly unaccepted as live evidence pending complete
    Drive readback and protocol validation. The component opens no port, starts no process, loads no
    dynamic adapter and contains no Drive credential handling. Binding it to an installed attested
    extension remains a separate persisted gate.

No project code appears in the discovery implementation. Project numbers occur only in fixtures and
acceptance evidence.
