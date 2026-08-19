# CLAR Core

**CLAR Core** is the generic runtime extracted from the lessons of CIVORA without inheriting CIVORA's accumulated orchestration by default.

Its stable public contract is intentionally limited to four objects:

1. `SourceItem`
2. `FactPacket`
3. `Story`
4. `PublicationReceipt`

A city/county publication belongs outside the core. `clar_core/` must not contain source URLs, locality names, article titles or one-off story logic.

The first consumer is `craiova-clar/`.

Legacy components may be reused only after they pass this test: they must shorten the path from a fresh source item to a live publication and remain generic across instances.
