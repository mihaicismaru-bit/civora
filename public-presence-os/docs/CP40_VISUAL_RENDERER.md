# CP40 — M06 visual minimal executable slice + deterministic SVG/PNG social card v1

CP40 reimplements M06 as canonical executable source without reconstructing unavailable CP29 source bytes. It consumes only canonical M05 native adaptations and, for photo frames, canonical M13 rights-bound visual inputs. It performs no network fetch, account connection, queue mutation, publisher write, public publish or deploy.

## Canon carried forward

The renderer preserves the CP29 `EDITORIAL_LEDGER_V1` grammar: paper `#F4F0E8`, ink `#171717`, muted ink `#62605B`, signal `#B33A2B`, annotation blue `#2F5D8A`, rule `#A79F93`, photo matte `#E3DDD2`; square geometry; zero-radius surfaces; source/folio structure; and procedural Marginalia only. Active visual lanes are Facebook Page, Instagram Professional and Threads. LinkedIn remains production-API-gated, X excluded while paid, and Bluesky `HOLD_ROI`.

Canonical CP29 typography roles remain Inter Display SemiBold, Noto Serif Regular, Noto Serif Italic and Noto Sans Mono Medium. Font files are never bundled. Every render uses exact local SHA-256 font binding. Because the historical CP29 executable archive and its exact four font hashes remain unavailable, CP40 does **not** claim byte-equivalence with the original CP29 production font binding. `canonical_identity_equivalent` remains false unless a later evidence recovery supplies all four exact hashes and the exact CP29 family/style bindings match.

## TEXT_CARD

`TEXT_CARD` consumes the exact source-bound M05 title line and never truncates, paraphrases or invents replacement copy. Local font metrics drive deterministic wrapping. Unbreakable tokens, overflow and invalid geometry fail closed. The renderer adds only structural Marginalia and source-host metadata.

## PHOTO_FRAME

`PHOTO_FRAME` requires a valid M13 `RIGHTS_BOUND_VISUAL_INPUT_ONLY` binding plus exact local source bytes whose SHA-256 equals the M13 asset hash. PNG/JPEG/WEBP are accepted, capped at 20 MB and 40 million decoded pixels, normalized to RGB and stripped of source metadata. Crop is deterministic centered fit/crop. Factual text overlay is prohibited. Rights-required credit is placed outside the photograph. Semantic subject-safe-zone remains `PENDING_VISUAL_QA` for M07.

## Output contract

Facebook uses 1080×1080. Instagram Professional and Threads use 1080×1350. Each successful render returns deterministic SVG and PNG bytes plus a manifest bound to renderer version, renderer environment, identity profile, exact local font hashes, M05 bundle/adaptation hashes and M13 binding/source hashes where applicable. SVG is self-contained; photo SVG embeds normalized raster bytes as a data URI. Reusing an exact deterministic output path verifies identical bytes; divergent bytes fail closed as conflict/tamper.

All outputs remain `MEDIA_PREVIEW_READY`, `visual_qa_input_ready=true`, `alt_text_status=REQUIRED_AFTER_RENDER`, `publish_eligible=false`, `queue_authority=false`, and `publish_authority=false`.

## Safety and deferred gate

No real media is acquired by M06. No credentials or account identifiers are accepted. No social API call exists in this slice. No network client is introduced. Pillow is the only new runtime dependency and is local/open-source; no paid renderer or Canva dependency is introduced.

The missing exact historical CP29 font hashes are preserved as `HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED`. This does not block clean-room M06 source execution or M07 QA development, but pilot production identity equivalence remains fail-closed until exact evidence is recovered or a later explicit versioned identity decision replaces that requirement.

## Next

M07 QA should consume M06 manifests and bytes, validate text/media integrity, dimensions, self-contained SVG, alt text, subject-safe-zone/photo relevance and identity-equivalence state, and keep all outputs pre-pilot/nonpublishing.
