# VÂLCEA CLAR — Owned Photo Drive Ingest v1

Status: `BARRIER_2_CLOSED_VIA_CONNECTED_HOURLY_RUNTIME`

## Scope

Implements the Google Drive → CIVORA bridge for VÂLCEA CLAR owned photography as a fail-closed metadata/candidate pipeline. It includes exact semantic identity for the current archive, exact-asset ranking, a dedicated new-photo inbox, hourly Drive discovery through the connected Google Drive runtime, and an explicit-only story materialization gate. None of these layers grants autonomous publication authority.

Pipeline:

`GOOGLE DRIVE INBOX/CURATED FOLDERS -> HOURLY CONNECTED READ -> METADATA SNAPSHOT -> OWNED PHOTO REGISTRY -> EXACT SEMANTIC IDENTITY -> BROAD CATEGORY RETRIEVAL -> EXACT-ASSET SEMANTIC RANKING -> STORY-LEVEL CONFIRMATION -> RIGHTS/PRIVACY/EDITOR GATES -> EXPLICIT MATERIALIZATION -> story_visuals.json`

## Drive layout and live parity

A dedicated `00_INBOX_NEW_PHOTOS` folder is registered under the curated archive. New photographs may be dropped there without being published or assigned automatically.

Current connected Drive parity was re-read on 2026-08-22:

- `00_INBOX_NEW_PHOTOS`: 0
- `01_RAU_OLANESTI_PROMENADA`: 6
- `02_CENTRU_RIVER_PLAZA_URBAN`: 15
- `03_INSTITUTII_ADMINISTRATIE`: 9
- `04_BUSINESS_BANCI_SERVICII`: 10
- `05_UNDE_IESIM`: 5
- `06_SANTIERE_DEZVOLTARE`: 2
- `07_PARKING_MOBILITATE`: 1
- curated JPEG total: 48

The live connected counts match the committed curated snapshot. The Drive objects remain private/not-shared; public-link exposure is not required by the current runtime.

## Barrier 1 — semantic identity

`SEMANTIC_BARRIER_1 = CLOSED_FOR_CURRENT_48_PHOTO_SNAPSHOT`.

`owned_photo_semantic_labels.json` is the curated semantic source and `owned_photo_semantic_registry.py` resolves it one-to-one against the Drive snapshot.

Validated state:

- 48/48 photographs have semantic identities;
- 48 confirmed;
- 0 ambiguous;
- 0 rejected;
- 31 exact-entity labels;
- 17 exact-place/scene labels;
- each confirmed asset has confidence >= 0.85;
- semantic identity never implies event identity, story subject-match, editor approval or publication eligibility.

Examples represented at exact-asset level include Râul Olănești/promenadă, River Plaza Mall, Primăria Râmnicu Vâlcea, Consiliul Județean Vâlcea, Prefectura, Tribunal/Palatul de Justiție, AJPIS, UniCredit, Banca Transilvania, Romprest, Camera de Comerț, RAZ Tower/Ramada, Carrefour Market, Arbusto Coffee, D’AMICI, Street Pub, Hotel Castel, Cash Pot, NOVA Luxury Apartments and central public parking.

Any future snapshot asset without a semantic label fails closed and cannot silently enter publication.

## Barrier 2 — live read-only Drive runtime

`SEMANTIC_BARRIER_2 = CLOSED_VIA_CONNECTED_HOURLY_RUNTIME`.

The production-safe runtime does not require a committed credential, a public Drive folder or a Google service-account key. Instead, an hourly connected runtime uses the already-authorized Google Drive connection strictly for metadata discovery.

Runtime contract is recorded in `valcea-clar/social/owned_photo_runtime_contract.json`:

- hourly cadence, minimum 60 minutes;
- read-only Drive discovery;
- no binary copy during discovery;
- no-change = no GitHub write and no notification;
- while PR #619 is open, snapshot changes are limited to its head branch;
- direct writes to `main` are forbidden;
- after merge, changes must use a dedicated sync branch/draft PR;
- allowed GitHub write path is only `valcea-clar/social/owned_photo_drive_snapshot.json`;
- no writes to `story_visuals.json`, materialization requests or site publication state;
- new unlabeled assets remain fail-closed for semantic review.

This closes the live-access barrier operationally. Native GitHub Actions Drive authentication through `VALCEA_DRIVE_SERVICE_ACCOUNT_JSON` or `VALCEA_DRIVE_BEARER_TOKEN` remains supported as an optional future implementation optimization, not a prerequisite for hourly discovery.

## Candidate matching and exact-asset ranking

`owned_photo_story_matcher.py` has two separate layers:

1. conservative category rules create broad retrieval candidates from story identity/headline/dek/section;
2. the exact semantic registry ranks individual assets inside that set.

Current validated output on the PR merge ref scans 32 published stories and 48 owned assets. It returns 20 stories with candidates: 19 missing-visual candidates and 1 replacement candidate. There are 147 broad retrieval links, including 23 exact semantic text-match links.

Exact semantic text match is still not event-level subject approval. Every candidate retains:

- `subject_match=false`
- `editor_approved=false`
- `publication_eligible=false`
- `publication_authority=NONE`
- `requires_visual_confirmation=true`
- `rights_reconfirmation_required=true`

## Explicit materialization gate

`materialize_owned_photo_story.py` is the only owned-photo path that may create a story visual assignment. It remains inactive unless an explicit request has status `approved_for_materialization`.

Every active request independently requires exact story/asset identity, story-level subject confirmation, editor approval, rights reconfirmation, privacy review, approved alt text and explicit replacement approval when an existing visual would be replaced.

Original binaries remain in Google Drive until an approved materialization request clears all gates.

## Safety invariants

The system enforces:

- semantic identity != story subject match;
- semantic text match != event identity;
- exact place/entity != exact event;
- owned rights != automatic publishability;
- broad category retrieval != exact asset approval;
- new inbox file != publishable file;
- no photo is better than false relevance.

## Runtime files

- `valcea-clar/social/owned_photo_drive_config.json`
- `valcea-clar/social/owned_photo_runtime_contract.json`
- `valcea-clar/social/owned_photo_drive_snapshot.json`
- `valcea-clar/social/owned_photo_registry.json` (generated)
- `valcea-clar/social/owned_photo_semantic_labels.json`
- `valcea-clar/social/owned_photo_semantic_registry.py`
- `valcea-clar/social/owned_photo_match_policy.json`
- `valcea-clar/social/owned_photo_story_candidates.json` (generated)
- `valcea-clar/social/owned_photo_materialization_requests.json`
- `valcea-clar/social/drive_owned_photo_ingest.py`
- `valcea-clar/social/owned_photo_story_matcher.py`
- `valcea-clar/social/materialize_owned_photo_story.py`
- `.github/workflows/valcea-clar-owned-photo-ingest.yml`

## Acceptance

`OWNED_PHOTO_RUNTIME = READY_WITH_BARRIERS_1_AND_2_CLOSED` when:

1. current Drive metadata parity equals the 48-photo curated snapshot;
2. the inbox exists and is included in config with zero initial items;
3. the connected hourly runtime is enabled with no direct-main write authority;
4. all 48 current assets retain confirmed semantics and the ambiguous queue is empty;
5. a new unlabeled asset fails closed before story matching/materialization;
6. exact semantic ranking never grants subject-match or publication authority;
7. ingest, semantics, matcher, ownership, quality, canonical export and social guards remain green.

No merge is implied by this runtime activation. PR #619 remains subject to explicit owner merge approval.
