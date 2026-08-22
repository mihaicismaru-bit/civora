# VÂLCEA CLAR — Owned Photo Drive Ingest v1

Status: `IMPLEMENTED_CANDIDATE_MATCHING_AND_EXPLICIT_MATERIALIZATION_GATE`

## Scope

Adds the missing Google Drive → CIVORA bridge for VÂLCEA CLAR's curated photo archive, a fail-closed story candidate matcher, and an explicit-only materialization gate. None of these layers grants autonomous publication authority.

Pipeline:

`GOOGLE DRIVE CURATED FOLDERS -> METADATA SNAPSHOT -> OWNED PHOTO REGISTRY -> CATEGORY/STORY CANDIDATE MATCHING -> VISUAL SUBJECT CONFIRMATION -> RIGHTS/PRIVACY/EDITOR GATES -> EXPLICIT MATERIALIZATION REQUEST -> story_visuals.json`

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

## Explicit materialization gate

`materialize_owned_photo_story.py` is the only owned-photo path that may create a real story visual assignment, and it is deliberately inactive unless an explicit request row has status `approved_for_materialization`.

Every active request must independently confirm:

- exact `story_id` and `asset_id`;
- `subject_match_confirmed=true`;
- `editor_approved=true`;
- `rights_reconfirmed=true`;
- `privacy_reviewed=true` plus a review note;
- `alt_text_approved=true` plus non-trivial alt text;
- explicit replacement approval when a story already has a visual.

The selected story/asset pair must already appear in the candidate queue. A reviewer may override that retrieval gate only with `override_candidate_queue=true` **and** a written `override_reason`; the override still does not bypass subject, rights, privacy or editor approval.

When eventually run with `--apply`, the materializer downloads the exact Drive JPEG using a read-only Drive credential, validates the binary, writes it under `valcea-clar/social/photos/approved/`, records SHA-256 provenance, and creates the normal `story_visuals.json` entry with `rights_basis=owned`. No active requests are committed in this PR, so current validation performs no publication or binary materialization.

## Safety and rights model

Discovery and matching are candidate-only. Every Drive asset enters with:

- `subject_match=false`
- `editor_approved=false`
- `publication_eligible=false`
- `publication_authority=NONE`
- `rights_reconfirmation_required=true`

The category/folder placement is useful retrieval metadata, not evidence that a photograph depicts a specific story event. No automatic story assignment is permitted.

The original binary remains in Google Drive until an explicit materialization request clears all gates. This avoids repository bloat and prevents unreviewed Drive files from leaking into publication.

## Runtime

Implementation:

- `valcea-clar/social/owned_photo_drive_config.json`
- `valcea-clar/social/owned_photo_drive_snapshot.json`
- `valcea-clar/social/owned_photo_registry.json` (generated output)
- `valcea-clar/social/owned_photo_match_policy.json`
- `valcea-clar/social/owned_photo_story_candidates.json` (generated output)
- `valcea-clar/social/owned_photo_materialization_requests.json`
- `valcea-clar/social/drive_owned_photo_ingest.py`
- `valcea-clar/social/owned_photo_story_matcher.py`
- `valcea-clar/social/materialize_owned_photo_story.py`
- `.github/workflows/valcea-clar-owned-photo-ingest.yml`

Authentication supports either:

- `VALCEA_DRIVE_SERVICE_ACCOUNT_JSON` (preferred, read-only scope), or
- `VALCEA_DRIVE_BEARER_TOKEN` (temporary/manual fallback).

If neither secret exists, PR validation rebuilds the registry and candidate queue from the committed snapshot and validates the explicit materialization contract without attempting Drive access.

## Acceptance

`OWNED_PHOTO_DRIVE_INGEST_V1 = OPERATIONAL_CANDIDATE_MATCHING_WITH_EXPLICIT_MATERIALIZATION_GATE` when:

1. the 48-photo bootstrap snapshot deterministically builds the registry;
2. ingest, matching and materialization-gate self-tests pass offline;
3. candidate queue validation proves category match never becomes subject match;
4. the materializer rejects any request missing subject, rights, privacy, alt-text or editor approval;
5. live Drive sync can replace the snapshot when read credentials are configured;
6. unchanged live inventory causes no repository churn;
7. no automatic story assignment or autonomous materialization authority is introduced.

The remaining functional gap is **asset-level semantic labeling / visual confirmation of specific Drive files**. Once exact images are confirmed, approved request rows can be created and materialized without changing this safety architecture. Hourly Drive refresh remains a separate activation step after Drive credentials exist.
