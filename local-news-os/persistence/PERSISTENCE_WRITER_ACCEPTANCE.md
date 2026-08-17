# CIVORA Persistence Writer V1 — PRS-038 acceptance

Scope: `CORE_GENERIC`.

The persistence writer is an adapter-independent contract. Product runtime success is not coupled to persistence transport success, and no instance-specific value, source, route, brand, credential value, or provider API is embedded in the writer.

Acceptance invariants:

1. Every active-state write request carries an explicit persistence namespace, target identity, `required_revision_id`, holder identity, and runtime lease token.
2. A write is attempted only when current lease ownership is proven by exact holder/token match and a non-expired observed lease.
3. The supplied `required_revision_id` is passed unchanged to the transport adapter. A revision conflict is fail-closed and never retried against stale state inside the writer.
4. Transport unavailability does not crash or roll back the product runtime. The writer returns `PERSISTENCE_STALE`, `synchronized=false`, and `runtime_may_continue=true`.
5. A successful transport write is not synchronization. Synchronization is true only after an immediate readback returns the exact written revision and exact expected content.
6. Missing write revision, readback failure, revision mismatch, or content mismatch returns `PERSISTENCE_STALE` and never claims synchronization.
7. Missing or foreign lease ownership returns `PERSISTENCE_BLOCKED` and performs zero target writes.
8. The writer receipt contains no credential values and does not assert external LIVE state.
9. The implementation remains generic across instances; instance-specific configuration and namespace selection stay outside the writer.

Regression evidence is executable through:

`python local-news-os/persistence/persistence_writer.py --self-test`

The self-test covers exact revision propagation, successful write + exact readback, unavailable persistence transport, revision conflict, readback mismatch, and foreign-lease zero-write behavior.
