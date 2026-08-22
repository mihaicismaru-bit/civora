# VÂLCEA CLAR — Owned Photo Drive Ingest v1

Status: `IMPLEMENTED_CANDIDATE_LAYER`

## Scope

Adds the missing Google Drive → CIVORA bridge for VÂLCEA CLAR's curated photo archive without granting publication authority.

Pipeline:

`GOOGLE DRIVE CURATED FOLDERS -> METADATA SNAPSHOT -> OWNED PHOTO REGISTRY -> SUBJECT/RIGHTS/EDITOR GATES -> EXPLICIT STORY MATERIALIZATION -> story_visuals.json`

## Current bootstrap inventory

The connected Drive snapshot contains 48 JPEG photographs across 7 curated categories:

- `01_RAU_OLANESTI_PROMENADA`: 6
- `02_CENTRU_RIVER_PLAZA_URBAN`: 15
- `03_INSTITUTII_ADMINISTRATIE`: 9
- `04_BUSINESS_BANCI_SERVICII`: 10
- `05_UNDE_IESIM`: 5
- `06_SANTIERE_DEZVOLTARE`: 2
- `07_PARKING_MOBILITATE`: 1

The committed snapshot is a bootstrap/fallback. When a Drive read credential is configured, the canonical workflow refreshes the inventory hourly and persists only material changes.

## Safety and rights model

Discovery is candidate-only. Every Drive asset enters with:

- `subject_match=false`
- `editor_approved=false`
- `publication_eligible=false`
- `publication_authority=NONE`
- `rights_reconfirmation_required=true`

The category/folder placement is useful retrieval metadata, not evidence that a photograph depicts a specific story event. No automatic story assignment is permitted.

The original binary remains in Google Drive. CIVORA stores metadata first; a photo is copied/materialized for a story only after a separate explicit approval step. This avoids repository bloat and prevents unreviewed Drive files from leaking into publication.

## Runtime

Canonical implementation:

- `valcea-clar/social/owned_photo_drive_config.json`
- `valcea-clar/social/owned_photo_drive_snapshot.json`
- `valcea-clar/social/owned_photo_registry.json`
- `valcea-clar/social/drive_owned_photo_ingest.py`
- `.github/workflows/valcea-clar-owned-photo-ingest.yml`

Authentication supports either:

- `VALCEA_DRIVE_SERVICE_ACCOUNT_JSON` (preferred, read-only scope), or
- `VALCEA_DRIVE_BEARER_TOKEN` (temporary/manual fallback).

If neither secret exists, the workflow validates and retains the committed snapshot rather than failing or inventing access.

## Acceptance

`OWNED_PHOTO_DRIVE_INGEST_V1 = OPERATIONAL_CANDIDATE_LAYER` when:

1. the 48-photo bootstrap snapshot deterministically builds the registry;
2. self-test and registry validation pass offline;
3. live Drive sync can replace the snapshot when read credentials are configured;
4. unchanged live inventory causes no repository churn;
5. every discovered asset remains candidate-only;
6. no automatic story assignment or publication authority is introduced.

The next layer is explicit candidate → story materialization with subject-match, rights confirmation, crop/alt-text and final editor approval.
