# CP34 — Pipeline reimplementation priority map + M01 RADAR minimal executable slice v1

## Purpose

CP34 begins clean-room executable reconstruction of the missing M01–M14 pipeline without treating historical checkpoint descriptions as source code.

The first restored stage is **M01 RADAR**. It is deliberately a discovery-only intake boundary. It does not fetch the web, claim facts, authorize publication, connect an account, mutate a queue, call a publisher, or deploy.

## M01 contract

Input is a bounded batch (maximum 100) of `RadarObservation` values supplied by a local caller or local JSON file. Each observation carries:

- stable `external_ref`;
- `source_url`;
- `source_class`;
- observation kind;
- UTC observation time;
- title and bounded excerpt;
- topic and locality;
- explicit synthetic marker where applicable.

Public source classes require HTTPS. Synthetic fixtures require a `synthetic://` URL and cannot masquerade as public observations.

Output is a deterministic `RadarSignal` with:

- stable `signal_id` bound to source URL + external reference;
- `observation_hash` bound to the normalized observation bytes;
- normalized provenance fields;
- `state=DISCOVERY_ONLY`;
- `fact_authority=false`;
- `publish_authority=false`;
- `network_fetch_performed=false`.

Exact replay deduplicates. A content change creates a new observation hash while retaining signal identity.

## Reimplementation order

The canonical priority map is `config/reimplementation_priority.json`. Dependencies preserve the content pipeline and place rights before visual materialization:

M01 RADAR → M02 research → M03 scoring → M04 master draft → M05 native adaptations → M13 rights → M06 visual → M07 QA → M12 approval → M08 queue → M09 publisher → M10 analytics → M11 learning → M14 experiments.

## Pilot effect

CP33 rehearsal now recognizes M01 as `PASS_EXECUTABLE_SOURCE`. The pilot remains fail-closed because M02–M14 still lack canonical executable source. This reduces the executable gap from 14 stages to 13 without weakening the pre-pilot safety boundary.

## External boundary

No live network fetch, paid service, account connection, public publication or deployment is introduced by CP34.
