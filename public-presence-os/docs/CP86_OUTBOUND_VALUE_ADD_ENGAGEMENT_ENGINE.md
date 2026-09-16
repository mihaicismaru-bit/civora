# CP86 / M55 — OUTBOUND VALUE-ADD ENGAGEMENT ENGINE v1

**State:** candidate implementation only / offline dry-run / human review required / no external write / live hold  
**Parent chain:** CP85 inbound reply → CP84 engagement radar → CP83 growth capability matrix  
**Global control:** CP58  
**Global kill switch:** ENGAGED  
**Next eligible unit after verified CP86 closure:** CP87 / M56 — RELATIONSHIP GRAPH v1

## Purpose

CP86 turns an already-eligible CP84 public-conversation candidate into a bounded, fact-bound outbound contribution candidate. It does not create broad commenting authority. It does not connect accounts, resolve secrets, perform OAuth, call a social API, probe a live surface, publish, comment, deploy, or use a paid service.

The engine is designed for organic participation that adds material value. It rejects actions that exist only to manufacture engagement.

## Canonical composer modes

- `CONTEXT`
- `DATA_POINT`
- `CLARIFICATION`
- `PRACTICAL_EXAMPLE`
- `GOOD_QUESTION`
- `RESPECTFUL_COUNTERPOINT`

Every candidate must add at least one of: information, context, clarification, a concrete question, or a useful perspective. Fact-bound evidence is mandatory. `GOOD_QUESTION` must contain a concrete question.

## Exact capability behavior

CP86 binds `OUTBOUND_COMMENT` to the verified CP83 matrix.

- **Facebook Page:** `MANUAL_ONLY`. Arbitrary external-object commenting is not assumed. A legitimate candidate produces `MANUAL_ACTION_PACKET`; automated dispatch remains false.
- **Instagram Professional:** `MANUAL_ONLY`. Arbitrary third-party media commenting is not assumed. A legitimate candidate produces `MANUAL_ACTION_PACKET`; automated dispatch remains false.
- **Threads:** `PASS_OFFLINE_CONTRACT` only for a specific readable post/reply. CP86 may produce `DRY_RUN_API_CANDIDATE_HUMAN_REVIEW`, but `HOLD_LIVE_PERMISSION`, pilot authorization, receipt-bound semantics and the engaged global kill switch still prevent any external write.

Unknown or drifted capability fails closed as `HOLD_CAPABILITY_UNVERIFIED`.

## Quality and safety gates

CP86 rejects generic compliments, engagement bait, repetitive praise, copy-paste replies, mass-commenting context, engagement pods, synthetic conversation farming, political microtargeting, sensitive-trait inference and sensitive relationship profiling.

The target is exact-bound to the CP84 conversation reference and source URL. Broad or mismatched targeting fails closed. Duplicate proposals for the same target deduplicate deterministically; conflicting payloads for the same target fail closed.

Rate budgets remain ceilings, not targets. No metric is invented; unavailable external metrics remain `UNKNOWN`.

## Authority invariant

All runtime-authority fields remain false. `posting_authority=false`, `external_write_allowed=false`, `external_write_attempted=false`, `network_allowed=false`, `network_attempted=false`, and human review is always required.

`MANUAL_ACTION_PACKET` is an operator packet only. It is not evidence of API support and it never means an automated write occurred.

## Validation target

The dedicated CP86 suite verifies exact CP83 route binding; CP58 + kill-switch invariants; all six composer modes; manual fallback for Facebook and Instagram; dry-run-only Threads behavior; material/fact-bound evidence requirements; rejection of non-eligible CP84 candidates; prohibited Growth safety signals; exact target/source binding; provenance gates; deterministic deduplication/conflict rejection; policy weakening fail-closed behavior; and `UNKNOWN` external metrics.

Repository exact-head CI is authoritative. This implementation must not be merged or promoted until exact-head PUBLIC PRESENCE OS CI is terminal `SUCCESS` and fresh-main overlap/mergeability is read back.

## Rollback

Before merge, close the CP86 PR without merge if exact-head CI is terminal non-success or a material invariant fails. This leaves `main` at verified CP85, with CP58 and the global kill switch unchanged.

## Next

After CP86 is independently integrated and closed in a later bounded unit, CP87 / M56 — RELATIONSHIP GRAPH v1 becomes eligible. CP87 is not implemented here.
