# VÂLCEA CLAR — S6 Operations & Governance

S6 consolidates operations without adding another editorial engine.

## Control plane

- `governance/s6_governance_policy.json` — authority matrix, alert rules and rollback boundaries.
- `ops/governance_state.json` — current material governance state; changes only when the substantive fingerprint changes.
- `ops/audit_log.jsonl` — append-only log of material governance state transitions and explicit runtime rollback events.
- `ops/incidents.json` — explicit incident ledger. Publication holds remain in `editorial/publication_holds.json`.
- `ops/rollback_baselines.json` — executable runtime LKG baselines plus non-executable milestone history.

## Human / automation boundary

Automation may run existing verification rules, fail closed, publish items that already pass canonical gates, render, reconcile and persist deterministic runtime state.

Automation may not lower evidence standards, release a hold by exception, force a blocked story, silently rewrite a material fact, change credentials/spend, erase durable publication history or roll back automatically.

## Alerts

The hourly governance workflow is deliberately quiet. Warnings such as known visual/channel backlog do not fail the run. The check fails only for material conditions such as an open P0/P1 incident, broken governance invariant, missing rollback baseline or S1–S5 regression.

The persistent audit state/log is updated only when the material fingerprint changes.

## Rollback

There are two different rollback classes:

1. **Runtime rollback** — executable only through manual GitHub `workflow_dispatch`, to a registered `rollback_eligible` baseline, after typing the exact confirmation phrase `ROLLBACK_RUNTIME`. It restores only generated/public runtime surfaces and aborts if `main` moved after the dispatch started.
2. **Code/configuration rollback** — never automated by S6. Use a reviewed Git revert or pull request.

Runtime rollback explicitly does **not** restore facts registry, story archive, corrections, publication holds, credentials or secrets.

## Incident severities

- P0 — active public integrity/safety failure;
- P1 — material publication/distribution/governance failure;
- P2 — degraded noncritical functionality with safe fallback;
- P3 — maintenance/improvement.

Only open P0/P1 incidents block the S6 gate.
