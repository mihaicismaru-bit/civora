# VÂLCEA CLAR — VISUAL FACTORY CANON v1.0

Status: `CANONICAL_BASELINE`

## Scop

VÂLCEA CLAR reutilizează principiile bune din DAPE Books Cover Factory pentru a construi un motor vizual comun pentru toate suprafețele editoriale și de distribuție: site, Facebook, Instagram, TikTok/Shorts thumbnails, newsletter, push/social cards, investigații, evenimente, „Unde ieșim”, cultură și materiale speciale.

Nu se copiază mecanic logica unei coperți de carte. Se reutilizează componentele generalizabile: brief vizual, ierarhie, promisiune/comunicare într-o fracțiune de secundă, concept generation, varianting, scoring, QA, brand consistency, safe areas, crop resilience, packaging pe multiple formate și learning din performanță.

## Principii

1. **Story first, image second.** Vizualul trebuie să exprime clar subiectul și unghiul editorial, nu să fie decorativ.
2. **Thumbnail test.** Orice vizual trebuie să funcționeze și la dimensiuni mici pe telefon.
3. **One dominant idea.** O singură idee vizuală dominantă, maximum un headline scurt și un element secundar.
4. **Credibility over spectacle.** Pentru știri, justiție, administrație și investigații, realismul și proveniența au prioritate față de dramatizare.
5. **No fake documentary imagery.** Imaginile generate nu sunt prezentate ca fotografii reale ale unui eveniment, loc sau persoane reale.
6. **Evidence-aware visuals.** Pentru investigații se preferă fotografii reale, documente, hărți, diagrame, planșe, capturi de document și compoziții clar etichetate.
7. **Brand without template fatigue.** Identitatea VÂLCEA CLAR trebuie recognoscibilă, dar nu prin repetarea rigidă a aceleiași machete.
8. **Multi-format by design.** Master-ul se proiectează pentru adaptare automată, nu se reconstruiește separat pentru fiecare canal.
9. **Fail-closed rights.** Orice asset trebuie să aibă provenance/rights status înainte de distribuție.
10. **Learning loop.** Performanța vizuală influențează variantele viitoare, fără a transforma editorialul în clickbait.

## Pipeline

`STORY -> VISUAL BRIEF -> ASSET DISCOVERY -> CONCEPTS -> COMPOSITION -> VARIANTS -> VISUAL QA -> CHANNEL ADAPTATION -> PUBLISH -> PERFORMANCE LEARNING`

### 1. Visual Brief

Câmpuri obligatorii:

- `story_id`
- `section`
- `story_type`
- `editorial_angle`
- `primary_entity`
- `primary_place`
- `dominant_fact`
- `emotion_target` (informativ, urgent, util, cultural, aspirational etc.)
- `sensitivity_level`
- `available_real_assets`
- `rights_status`
- `must_not_imply`
- `headline_candidate`
- `brand_variant`

### 2. Asset Discovery

Ordinea implicită:

1. fotografie proprie / furnizată cu drepturi clare;
2. imagine oficială sau press-kit utilizabil conform drepturilor;
3. hartă, document, captură, diagramă sau infografic propriu;
4. imagine stock/licențiată, dacă este justificată;
5. imagine generată, numai când nu induce publicul în eroare și este potrivită editorial.

Pentru restaurante, evenimente și lifestyle, imagini oficiale și user-generated cu permisiune pot fi utile. Pentru știri sensibile, imaginile generate sunt puternic restricționate.

### 3. Concept Generator

Pentru fiecare material important se generează 3–5 concepte, de exemplu:

- `PHOTO_LED`
- `DOCUMENT_LED`
- `MAP_LED`
- `DATA_LED`
- `TYPOGRAPHIC`
- `PORTRAIT_LED`
- `VENUE_LED`
- `EVENT_POSTER_INSPIRED`
- `EXPLAINER_CARD`

Un concept este ales înainte de producerea variantelor finale.

## Scor vizual

Fiecare variantă primește 0–100 pentru:

- `clarity_score`
- `thumbnail_score`
- `story_fit_score`
- `credibility_score`
- `visual_hierarchy_score`
- `brand_fit_score`
- `crop_resilience_score`
- `text_legibility_score`
- `originality_score`
- `platform_fit_score`
- `rights_confidence_score`

Scor agregat implicit:

`0.18 clarity + 0.14 thumbnail + 0.16 story_fit + 0.14 credibility + 0.10 hierarchy + 0.07 brand + 0.06 crop + 0.06 text + 0.04 originality + 0.03 platform + 0.02 rights`

Materialele sensibile cresc ponderea `credibility` și `rights_confidence`.

## Visual grades

- `A+` 92–100 — publish hero / campaign grade
- `A` 85–91 — publish
- `B` 75–84 — publish secondary / needs minor refinement
- `<75` — regenerate/refine

## Channel Packs

Din master se generează automat minimum:

- `SITE_HERO` — 16:9 / crop-safe
- `ARTICLE_SOCIAL` — Open Graph 1.91:1
- `FACEBOOK_FEED` — 1.91:1 și/sau 4:5 în funcție de test
- `INSTAGRAM_FEED` — 4:5
- `INSTAGRAM_STORY` — 9:16
- `TIKTOK_SHORTS_COVER` — 9:16 cu safe zone centrală
- `NEWSLETTER` — wide crop
- `THUMBNAIL_SQUARE` — 1:1

Headline-ul se adaptează ca lungime și line-break per format; imaginea nu se întinde mecanic.

## Facebook specific

Pentru fiecare material cu prioritate suficientă, Visual Factory poate produce două variante:

- `FB_A`: fotografie/asset dominant, text minim;
- `FB_B`: card editorial cu headline scurt și accent vizual.

A/B learning folosește CTR, dwell/referral quality și engagement quality, nu doar reacții brute. Nu se optimizează către titluri sau imagini înșelătoare.

## Vertical presets

### Breaking / Oraș
- fotografie reală prioritar;
- brand discret;
- headline foarte scurt;
- fără dramatizare artificială.

### Investigații
- documente, hartă, fotografie de teren, flux bani, relații sau timeline;
- etichete clare `DOCUMENT`, `HARTĂ`, `CRONOLOGIE` când este cazul;
- nicio compoziție care sugerează vinovăție înainte de dovezi.

### Unde ieșim
- food/venue imagery premium;
- accent pe atmosferă, preparat, spațiu și utilitate;
- prețurile doar dacă sunt verificate și datate;
- poate folosi carusele și colecții.

### Evenimente / Cultură
- identitate vizuală mai expresivă;
- se pot integra afișe/press-kit-uri cu drepturi clare;
- data, locul și ora au prioritate de lizibilitate.

### Business / Economie
- fotografie companie/persoană sau data-led card;
- grafice simple;
- fără imagini generic-corporate dacă există asset mai specific.

## Anti-AI-look rules

- evită compoziții hiper-lucioase, piele/plastic, pseudo-cinematic fără motiv;
- evită text generat în imagine; textul se compune separat;
- evită iconografie generică și decor fără legătură cu subiectul;
- pentru locuri reale preferă fotografii reale;
- imaginile generate trebuie să fie clar ilustrative când există risc de confuzie.

## Provenance Ledger

Fiecare asset are:

- `asset_id`
- `source_type`
- `source_url_or_origin`
- `creator_or_owner`
- `rights_basis`
- `license_or_permission`
- `captured_or_created_at`
- `edits_applied`
- `ai_generated`
- `ai_disclosure_required`
- `story_ids_used`
- `expiry_or_review_at`

## Adaptive Visual Learning

Sistemul învață pe secțiune și canal:

- ce raport fotografie/text funcționează;
- ce densitate de headline performează;
- ce tip de crop păstrează CTR și calitatea sesiunii;
- ce concepte produc engagement fără bounce ridicat;
- ce vizualuri sunt suprafolosite.

Learning-ul poate ajusta preferințele de concept și format, dar nu poate modifica regulile de credibilitate, rights sau sensitive-claim gates.

## Acceptance

`VISUAL_FACTORY_V1 = OPERATIONAL` când:

1. primește automat un `story_id` și produce un brief;
2. poate folosi real assets + generated/diagram assets în ordinea corectă;
3. produce minimum 3 concepte pentru materialele prioritare;
4. generează master + channel pack;
5. fiecare variantă trece prin scoring/QA;
6. provenance este obligatoriu;
7. investigațiile și știrile sensibile nu pot folosi fake documentary imagery;
8. rezultatele pot fi folosite pe site, Facebook, Instagram și newsletter din aceeași sursă canonică;
9. performanța se întoarce în learning loop fără a relaxa standardele editoriale.
