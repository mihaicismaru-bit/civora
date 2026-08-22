# VÂLCEA CLAR — Owned Photo Drive Ingest v1

Status: `SEMANTIC_BARRIER_1_CLOSED_FOR_CURRENT_48_PHOTO_SNAPSHOT`

## Scope

Adds the Google Drive → CIVORA bridge for VÂLCEA CLAR's curated photo archive, fail-closed story candidate matching, exact semantic identity for the current owned-photo snapshot, and an explicit-only materialization gate. None of these layers grants autonomous publication authority.

Pipeline:

`GOOGLE DRIVE CURATED FOLDERS -> METADATA SNAPSHOT -> OWNED PHOTO REGISTRY -> EXACT SEMANTIC IDENTITY -> CATEGORY/STORY RETRIEVAL -> STORY-LEVEL VISUAL SUBJECT CONFIRMATION -> RIGHTS/PRIVACY/EDITOR GATES -> EXPLICIT MATERIALIZATION REQUEST -> story_visuals.json`

## Current curated inventory

The connected Drive snapshot contains 48 JPEG photographs across 7 curated categories:

- `01_RAU_OLANESTI_PROMENADA`: 6
- `02_CENTRU_RIVER_PLAZA_URBAN`: 15
- `03_INSTITUTII_ADMINISTRATIE`: 9
- `04_BUSINESS_BANCI_SERVICII`: 10
- `05_UNDE_IESIM`: 5
- `06_SANTIERE_DEZVOLTARE`: 2
- `07_PARKING_MOBILITATE`: 1

The committed snapshot is a bootstrap/fallback. The workflow remains PR/manual-only until a read-only Drive credential is configured.

## Semantic identity layer

`owned_photo_semantic_labels.json` is the curated semantic source for the current 48-photo snapshot. `owned_photo_semantic_registry.py` resolves those labels against the Drive snapshot and requires a one-to-one filename → `drive_file_id` binding.

Current acceptance target and validated source state:

- 48/48 snapshot photographs have a semantic label;
- 48 are `confirmed`;
- 0 are `ambiguous`;
- 0 are `reject`;
- every confirmed asset has confidence ≥ 0.85;
- every asset retains `subject_match=false`, `editor_approved=false`, `publication_eligible=false`, `publication_authority=NONE`.

The semantic registry distinguishes exact entities, exact places/scenes, scene types, editorial uses, privacy-review status, quality tier and owned-rights basis. Evidence must include both visual review and raw JPEG/EXIF review. Additional evidence may include visible signage, distinctive facade, cross-frame landmark confirmation, public-address cross-check or visible project/business signage.

Examples now represented at exact-asset level include the Râul Olănești promenade, River Plaza Mall, Primăria Râmnicu Vâlcea, Consiliul Județean Vâlcea, Prefectura Vâlcea, Tribunalul/Palatul de Justiție, AJPIS, UniCredit, Banca Transilvania, Romprest, Camera de Comerț, RAZ Tower/Ramada, Carrefour Market, Arbusto Coffee, D’AMICI, Street Pub, Hotel Castel, Cash Pot, NOVA Luxury Apartments and central public parking.

Semantic identity is **not** event identity. A photograph confirmed as the Primăria building may be retrieved for a Primăria story, but it does not automatically become the photograph of a specific council meeting or event. Story-level subject match remains a separate explicit gate.

`owned_photo_ambiguous_review_queue.json` is generated from the semantic source when `--write` runs. For the current curated snapshot the expected queue size is zero. Any future Drive file without a semantic label fails closed rather than entering story matching silently.

## Candidate matching

`owned_photo_story_matcher.py` compares published story identity/headline/dek/section against conservative category rules in `owned_photo_match_policy.json`.

A category match is retrieval assistance only. Every candidate remains:

- `subject_match=false`
- `editor_approved=false`
- `publication_eligible=false`
- `publication_authority=NONE`
- `requires_visual_confirmation=true`
- `rights_reconfirmation_required=true`

The matcher avoids article-body/source text for scoring so a source citation cannot make an unrelated story look like an institutional-photo match. Known false-positive patterns are penalized, e.g. a Buila/Băile Olănești accident must not inherit the Râul Olănești/promenadă category merely because “Olănești” appears.

`owned_photo_story_candidates.json` distinguishes `missing_visual_candidate` from `replacement_candidate`. No queue entry mutates `story_visuals.json`.

## Explicit materialization gate

`materialize_owned_photo_story.py` is the only owned-photo path that may create a real story visual assignment, and it is inactive unless an explicit request row has status `approved_for_materialization`.

Every active request must independently confirm exact story/asset identity, story-level subject match, editor approval, rights reconfirmation, privacy review, approved alt text, and explicit replacement approval when a story already has a visual.

The selected story/asset pair must already appear in the candidate queue unless a written explicit override is supplied. An override never bypasses subject, rights, privacy or editor approval.

When eventually run with `--apply`, the materializer downloads the exact Drive JPEG using a read-only Drive credential, validates the binary, writes it under `valcea-clar/social/photos/approved/`, records SHA-256 provenance, and creates the normal `story_visuals.json` entry with `rights_basis=owned`.

No active materialization requests are committed in this PR, so current validation performs no publication or binary materialization.

## Safety and rights model

The Drive archive and semantic registry are metadata/candidate layers. Owned-rights status does not bypass privacy or story relevance review. Original binaries remain in Google Drive until an explicit materialization request clears all gates.

The semantic source and validator deliberately enforce:

- semantic identity ≠ story subject match;
- exact place/entity ≠ exact event;
- owned rights ≠ automatic publishability;
- category match ≠ exact asset match;
- no photo is better than false relevance.

## Runtime

Implementation:

- `valcea-clar/social/owned_photo_drive_config.json`
- `valcea-clar/social/owned_photo_drive_snapshot.json`
- `valcea-clar/social/owned_photo_registry.json` (generated ingest output)
- `valcea-clar/social/owned_photo_semantic_labels.json`
- `valcea-clar/social/owned_photo_semantic_registry.py`
- `valcea-clar/social/owned_photo_semantic_registry.json` (ephemeral/generated validation output)
- `valcea-clar/social/owned_photo_ambiguous_review_queue.json` (ephemeral/generated validation output)
- `valcea-clar/social/owned_photo_match_policy.json`
- `valcea-clar/social/owned_photo_story_candidates.json` (generated output)
- `valcea-clar/social/owned_photo_materialization_requests.json`
- `valcea-clar/social/drive_owned_photo_ingest.py`
- `valcea-clar/social/owned_photo_story_matcher.py`
- `valcea-clar/social/materialize_owned_photo_story.py`
- `.github/workflows/valcea-clar-owned-photo-ingest.yml`

Authentication supports either `VALCEA_DRIVE_SERVICE_ACCOUNT_JSON` (preferred, read-only scope) or `VALCEA_DRIVE_BEARER_TOKEN` (temporary/manual fallback). If neither secret exists, PR validation rebuilds the registry from the committed snapshot and validates semantics/matching/materialization without inventing Drive runtime access.

## Acceptance

`SEMANTIC_BARRIER_1 = CLOSED_FOR_CURRENT_48_PHOTO_SNAPSHOT` when:

1. the 48-photo bootstrap snapshot deterministically builds the owned registry;
2. semantic labels cover exactly the same 48 unique files/Drive IDs;
3. all 48 semantic identities are confirmed and the ambiguous queue is empty;
4. semantic validation proves no asset inherits story subject match, editor approval or publication authority;
5. ingest, matching and materialization-gate self-tests pass;
6. current site-engine ownership, quality, canonical export and social acceptance gates remain green.

After this barrier, first owned-photo replacements may be proposed at exact-asset level, but each still needs story-specific visual confirmation and the existing explicit materialization gate.

## Next barrier

`SEMANTIC_BARRIER_2 = LIVE_DRIVE_READ_ONLY_RUNTIME_ACCESS`.

GitHub Actions currently has no usable `VALCEA_DRIVE_SERVICE_ACCOUNT_JSON` or `VALCEA_DRIVE_BEARER_TOKEN`, so live Drive refresh stays explicit/manual and unscheduled. The next activation task is to configure a least-privilege read-only Drive credential, prove live snapshot parity, and only then register a bounded hourly refresh. No merge or autonomous activation is implied by this document.
