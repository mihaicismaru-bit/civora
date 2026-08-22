# VÂLCEA CLAR — Owned Photo Drive Ingest v1

Status: `IMPLEMENTED_CANDIDATE_AND_MATCHING_LAYER`

## Scope

Adds the missing Google Drive → CIVORA bridge for VÂLCEA CLAR's curated photo archive and a fail-closed story candidate matcher, without granting publication authority.

Pipeline:

`GOOGLE DRIVE CURATED FOLDERS -> METADATA SNAPSHOT -> OWNED PHOTO REGISTRY -> CATEGORY/STORY CANDIDATE MATCHING -> VISUAL SUBJECT CONFIRMATION -> RIGHTS/EDITOR GATES -> EXPLICIT STORY MATERIALIZATION -> story_visuals.json`

## Current bootstrap inventory

The connected Drive snapshot contains 48 JPEG photographs across 7 curated categories:

- `01_RAU_OLANESTI_PROMENADA`: 6
- `02_CENTRU_RIVER_PLAZA_URBAN`: 15
- `03_INSTITUTII_ADMINISTRATIE`: 9
- `04_BUSINESS_BANCI_SERVICII`: 10
- `05_UNDE_IESIM`: 5
- `06_SANTIERE_DEZVOLTARE`: 2
- `07_PARKING_MOBILITATE`: 1

The committed snapshot is a bootstrap/fallback. The workflow is PR/manual-only until a read-only Drive credential is configured. After that gate is satisfied, the same runtime can be registered for hourly refresh without changing the candidate or publication-safety contract.

## Candidate matching

`owned_photo_story_matcher.py` compares published story identity/headline/dek/section against conservative category rules in `owned_photo_match_policy.json`.

A category match is only retrieval assistance. It is explicitly **not** a claim that any specific image depicts the story. Every candidate remains:

- `subject_match=false`
- `editor_approved=false`
- `publication_eligible=false`
- `publication_authority=NONE`
- `requires_visual_confirmation=true`
- `rights_reconfirmation_required=true`

The matcher avoids using article body/source text for scoring so that a source citation such as HCL/Primăria does not make an unrelated story look like an institutional-photo match. It also carries negative terms for known false-positive patterns, e.g. a Buila/Băile Olănești accident must not inherit the Râul Olănești/promenadă photo category merely because the word “Olănești” appears.

The output `owned_photo_story_candidates.json` distinguishes:

- `missing_visual_candidate` — published story has no known visual;
- `replacement_candidate` — an owned-photo category may be more appropriate than an existing visual, but replacement still requires explicit review.

No queue entry mutates `story_visuals.json`.

## Safety and rights model

Discovery and matching are candidate-only. Every Drive asset enters with:

- `subject_match=false`
- `editor_approved=false`
- `publication_eligible=false`
- `publication_authority=NONE`
- `rights_reconfirmation_required=true`

The category/folder placement is useful retrieval metadata, not evidence that a photograph depicts a specific story event. No automatic story assignment is permitted.

The original binary remains in Google Drive. CIVORA stores metadata first; a photo is copied/materialized for a story only after a separate explicit approval step. This avoids repository bloat and prevents unreviewed Drive files from leaking into publication.

## Runtime

Implementation:

- `valcea-clar/social/owned_photo_drive_config.json`
- `valcea-clar/social/owned_photo_drive_snapshot.json`
- `valcea-clar/social/owned_photo_registry.json` (generated output)
- `valcea-clar/social/owned_photo_match_policy.json`
- `valcea-clar/social/owned_photo_story_candidates.json` (generated output)
- `valcea-clar/social/drive_owned_photo_ingest.py`
- `valcea-clar/social/owned_photo_story_matcher.py`
- `.github/workflows/valcea-clar-owned-photo-ingest.yml`

Authentication supports either:

- `VALCEA_DRIVE_SERVICE_ACCOUNT_JSON` (preferred, read-only scope), or
- `VALCEA_DRIVE_BEARER_TOKEN` (temporary/manual fallback).

If neither secret exists, PR validation rebuilds the registry and candidate queue from the committed snapshot rather than failing or inventing access.

## Acceptance

`OWNED_PHOTO_DRIVE_INGEST_V1 = OPERATIONAL_CANDIDATE_AND_MATCHING_LAYER` when:

1. the 48-photo bootstrap snapshot deterministically builds the registry;
2. ingest and matching self-tests pass offline;
3. candidate queue validation proves category match never becomes subject match;
4. live Drive sync can replace the snapshot when read credentials are configured;
5. unchanged live inventory causes no repository churn;
6. every discovered/matched asset remains candidate-only;
7. no automatic story assignment or publication authority is introduced.

The next layer is **asset-level semantic labeling + explicit candidate → story materialization** with visual subject confirmation, rights confirmation, crop/alt-text and final editor approval. Hourly registration remains a separate activation step after Drive credentials exist.
