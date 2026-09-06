# CP41 — M07 QA minimal executable slice + media/editorial QA contract v1

CP41 reimplements M07 QA as canonical executable source. It consumes canonical M05 adaptation bundles and canonical M06 rendered visual bytes/manifests; PHOTO_FRAME additionally requires the exact M13 rights binding and a hash-bound semantic photo review. The slice is local-only and nonpublishing.

## Deterministic integrity gates

M07 verifies the M06 model/renderer versions, active platform, render state, exact SVG/PNG hashes and sizes, expected platform dimensions, render-key/asset-ID derivation, exact M05 bundle/adaptation binding, source URL binding, self-contained inactive SVG structure, static PNG decoding and exact PNG dimensions. Any byte, binding, dimension or authority mismatch fails closed.

TEXT_CARD uses the exact first non-empty source-bound M05 line as displayed text and deterministic alt text. Its SHA-256 must equal the M06 `displayed_text_sha256`; no photo/rights review may be attached to this mode.

PHOTO_FRAME requires a canonical M13 `RIGHTS_BOUND_VISUAL_INPUT_ONLY` record in `OWNED`, `LICENSED` or `PUBLIC_DOMAIN` state, exact platform/purpose binding, exact source media hash, and rendered attribution when rights require it. M07 rejects factual overlay on the photo frame.

## Semantic photo QA

Rights do not imply relevance. PHOTO_FRAME therefore requires a separate `PhotoSemanticReview` before semantic photo gates can pass. The review is bound to asset ID, rendered PNG hash and original source-media hash and carries its own evidence SHA-256. Accepted reviewer modes are `HUMAN_REVIEW` and `LOCAL_VISION_REVIEW`. Relevance passes only as `CONFIRMED_RELEVANT`; subject-safe-zone passes only as `PASS`; alt text is review-bound and limited to 500 characters. Missing or uncertain review evidence produces explicit HOLD reasons rather than inferred relevance.

## Identity-equivalence hold

CP40 preserved the historical blocker that exact CP29 font hashes are unavailable. M07 therefore does not treat the mutable `canonical_identity_equivalent` manifest boolean as sufficient authority. Every CP41 QA report preserves `HOLD_IDENTITY_EQUIVALENCE` / `HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED` until exact CP29 font evidence is recovered or a later explicit versioned identity decision supersedes it. This means M07 source can be executable and technically validate assets while pilot approval remains fail-closed.

## Output contract

M07 emits deterministic `VisualQAReport` records in state `VISUAL_QA_ONLY`. Reports include integrity, text, SVG, PNG, rights, alt-text, photo relevance, safe-zone and identity states plus explicit holds. M07 has visual-QA authority only. It has no approval, queue, publisher, network, account-connection, public-publish or deploy authority.

Active lanes remain Facebook Page, Instagram Professional and Threads. LinkedIn remains production-API-gated, X excluded while its API is paid, and Bluesky remains `HOLD_ROI`.

## Next

M12 APPROVAL should consume only hash-bound M07 reports and expose a local approval dashboard/state machine without granting queue or publisher authority. It must surface all HOLD reasons, especially the identity-equivalence blocker, and remain disconnected from real accounts and network publishing.
