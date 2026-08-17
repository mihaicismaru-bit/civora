# PRS-041 — Persistence health signal acceptance

Contract: `CIVORA_PERSISTENCE_HEALTH_SIGNAL_V1`

The persistence layer exposes exactly four canonical states, independent of product/runtime health:

- `PERSISTENCE_FRESH` — latest durable state is synchronized and readback-verified.
- `PERSISTENCE_STALE` — durable latest state is not proven synchronized, including transport/readback staleness.
- `RECONCILIATION_REQUIRED` — authoritative repository/external/persistence inputs changed and must be reconciled before freshness can be claimed.
- `PERSISTENCE_BLOCKED` — persistence transport, ownership, lease or required write safety cannot be proven.

Fail-closed precedence is `PERSISTENCE_BLOCKED > RECONCILIATION_REQUIRED > PERSISTENCE_STALE > PERSISTENCE_FRESH`.

Acceptance invariants:

1. `PERSISTENCE_FRESH` is impossible without positive synchronization evidence.
2. Reconciliation need cannot be hidden by a successful write/readback.
3. A blocked persistence path cannot degrade into a weaker `STALE` or `RECONCILIATION_REQUIRED` claim.
4. Persistence health never grants publication, deployment or external `LIVE` authority.
5. Product runtime may continue while persistence is stale, reconciliation-required or blocked; downstream current-state promotion remains independently gated by PRS-040.
6. The contract is `CORE_GENERIC`: no instance identity, geography, provider-specific API, credential value or Vâlcea hardcoding.
7. Unknown health labels fail closed in validation.

Executable acceptance: `python local-news-os/persistence/persistence_health.py --self-test`.
