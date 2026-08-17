# PRS-040 — Readback-verified latest-state promotion

Contract: `CIVORA_PERSISTENCE_LATEST_STATE_PROMOTION_V1`

A transport write cannot become the durable latest current state merely because the provider accepted it. Promotion is allowed only when the caller presents the exact `CIVORA_PERSISTENCE_WRITER_V1` receipt for the same namespace, target and payload, with `outcome=SYNCED`, `persistence_health=PERSISTENCE_FRESH`, `synchronized=true`, non-empty written/readback revision IDs, equal written/readback revisions, and the writer's exact-readback success reason.

Fail-closed acceptance cases:

- payload hash differs from the write receipt → no promotion;
- namespace or target differs → no promotion;
- write is stale/blocked or `synchronized=false` → no promotion;
- readback revision is absent or differs from the written revision → no promotion;
- readback content mismatch in the writer produces a non-synchronized receipt, which the promotion gate rejects;
- provider/network identity, instance identity, geography and brand are not embedded in the generic contract.

The gate performs no external writes and grants no external LIVE/publication authority. It is a CORE_GENERIC persistence boundary intended to be called immediately before changing any durable latest-current-state pointer or equivalent active-state designation.
