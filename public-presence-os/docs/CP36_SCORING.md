# CP36 — M03 SCORING minimal executable slice + evidence-bound scorecard v1

## Scope

CP36 advances exactly one granular unit: clean-room executable reconstruction of M03 SCORING. It consumes only CP35 `ResearchPacket` objects that are `EVIDENCE_BOUND` and `scoring_input_ready=true` and produces a deterministic evidence-readiness scorecard.

M03 does not draft, queue, publish, connect accounts, perform network fetches or invent performance predictions.

## What the score means

`evidence_readiness_score` measures only the quality and operational readiness of the research evidence already bound by M02. It is not a newsworthiness score, political-value score, persuasion score, engagement forecast or virality prediction.

The frozen model `PPOS_EVIDENCE_READINESS_SCORE_V1` totals 100 points across:

- evidence quality — 30;
- source directness — 15;
- corroboration — 15;
- research timeliness — 20;
- provenance completeness — 20.

Bands:

- 85–100: `EVIDENCE_READY_STRONG`;
- 70–84: `EVIDENCE_READY_STANDARD`;
- 0–69: `EVIDENCE_READY_LIMITED`.

The fields `editorial_impact_score`, `virality_score` and `audience_fit_score` are explicitly `null`. No such value is inferred without an evidence-bearing future contract.

## Input gate

M03 accepts only a canonical M02 packet that simultaneously has:

- `state=RESEARCH_PACKET_ONLY`;
- `research_status=EVIDENCE_BOUND`;
- `evidence_bound=true`;
- `scoring_input_ready=true`;
- `synthetic=false`;
- no fact/scoring/draft/publish authority;
- `network_fetch_performed=false`;
- valid packet ID and exact `research_packet_hash`;
- production HTTPS evidence with valid SHA-256, UTC capture times and unique IDs.

A self-hash is not trusted alone: M03 revalidates the semantic evidence boundary and rejects a recomputed-but-invalid packet.

## Output authority

The `EvidenceScorecard` is `SCORING_ONLY` and grants only internal scoring authority. It always keeps:

- `fact_authority=false`;
- `draft_authority=false`;
- `queue_authority=false`;
- `publish_authority=false`;
- `network_fetch_performed=false`.

M03 does not authorize M04 execution. CP37 must define the M04 contract separately.

## Determinism

The scorecard ID binds M02 packet ID + research-packet hash + model version. The scorecard hash binds the full dimension breakdown and authority boundary. Exact replay returns identical bytes. Batch scoring deduplicates exact scorecards and sorts deterministically by evidence readiness and stable IDs.

## Pilot posture

M01, M02 and M03 now have executable canonical source in GitHub. M04–M14 remain fail-closed as executable-source gaps. Facebook Page, Instagram Professional and Threads remain the only active target lanes. No live account connection, network publishing or deploy is introduced by CP36.
