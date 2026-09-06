# CP35 — M02 RESEARCH minimal executable slice + evidence-bound ResearchPacket v1

CP35 reimplements the second canonical pipeline stage as executable source. M02 accepts only fail-closed `RadarSignal` values from M01 and produces deterministic `ResearchPacket` artifacts. It performs no network fetch and grants no fact, scoring, drafting, publishing or deployment authority.

## Input boundary

M02 accepts only canonical M01 `RadarSignal` values with:

- `state=DISCOVERY_ONLY`;
- `fact_authority=false`;
- `publish_authority=false`;
- `network_fetch_performed=false`.

Any authorizing or non-RADAR input fails closed.

## Evidence binding

Evidence is supplied as local `ResearchEvidence` metadata only. CP35 never fetches the referenced resource. Every evidence item is bound by:

- stable evidence ID;
- normalized source URL;
- authority class (`PRIMARY_SOURCE` or `SECONDARY_CONTEXT`);
- evidence kind;
- capture timestamp;
- lowercase SHA-256 of the captured bytes;
- explicit synthetic marker.

Production evidence must use HTTPS. Synthetic evidence must use `synthetic://` and can never claim `PRIMARY_SOURCE` authority.

For `PRIMARY_PUBLIC` RADAR signals, at least one non-synthetic primary evidence record from the same host is required for `EVIDENCE_BOUND`. For `SECONDARY_DISCOVERY`, an independent non-synthetic primary evidence record is required. Synthetic RADAR fixtures always remain `SYNTHETIC_NON_EVIDENCE`.

## Research states

- `HOLD_PRIMARY_EVIDENCE`
- `HOLD_PRIMARY_CONFIRMATION`
- `SYNTHETIC_NON_EVIDENCE`
- `EVIDENCE_BOUND`

`EVIDENCE_BOUND` means only that a downstream scorer may consume the packet as an evidence-bound research input. It does not certify any material factual claim.

## ResearchPacket contract

The packet binds:

- `signal_id` and `radar_observation_hash`;
- RADAR source/topic/locality/title/excerpt metadata;
- sorted immutable evidence references;
- deterministic evidence requirements;
- deterministic unresolved research questions;
- research status;
- `evidence_bound` and `scoring_input_ready` flags;
- `packet_id` and `research_packet_hash`.

Every packet hard-codes:

- `state=RESEARCH_PACKET_ONLY`;
- `fact_authority=false`;
- `scoring_authority=false`;
- `draft_authority=false`;
- `publish_authority=false`;
- `network_fetch_performed=false`.

## Determinism and replay

Evidence is deduplicated by evidence ID, sorted deterministically and conflicts on the same ID fail closed. Exact replay produces the same packet/hash. A new RADAR observation revision preserves the stable `signal_id` but changes `radar_observation_hash`, `packet_id` and `research_packet_hash`.

## Safety posture

CP35 does not connect accounts, use OAuth, publish, deploy, mutate queues, write to publishers, reserve scheduler slots or use paid services. Active platform policy remains Facebook Page, Instagram Professional and Threads; LinkedIn remains production-API-gated, X excluded while paid and Bluesky HOLD_ROI.

## Next stage

After CP35, M03 SCORING becomes the next clean-room implementation target. M03 may consume only M02 packets whose `scoring_input_ready=true`; it must remain non-publishing and evidence-bound.
