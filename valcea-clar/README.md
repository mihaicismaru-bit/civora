# VÂLCEA CLAR — CIVORA site engine

Verticală CIVORA pentru știri locale, restaurante, cafenele, puburi, terase, evenimente, investigații și distribuție editorială în județul Vâlcea.

## Stare

`INTEGRATED_V0.5 — SITE_ENGINE_OWNED` — ingestia, monitorizarea, generarea edițiilor, proiecția publică, validarea și distribuția rulează din repository prin GitHub Actions, cu stare persistentă și politici fail-closed.

## Proprietatea execuției

Sursa tehnică unică este `mihaicismaru-bit/civora`, directorul `valcea-clar/`. Toate joburile recurente sunt înregistrate în `engine/automation_registry.json` și sunt executate numai de runner-e GitHub-hosted.

ChatGPT are exclusiv rol de consolă de administrare și dezvoltare. Nu este scheduler, runtime editorial, depozit de stare sau motor de generare. Sunt interzise pentru producție:

- taskuri sau monitoare recurente ChatGPT;
- execuția dintr-o conversație sau de pe calculatorul utilizatorului;
- runner-e `self-hosted` ori cron-uri locale;
- chei și endpointuri OpenAI, Anthropic sau Gemini în fluxurile VÂLCEA CLAR;
- orice dependență de API LLM plătit pentru monitorizare, generare sau publicare.

`validate_site_engine_ownership.py` verifică fail-closed această regulă, iar workflow-ul `valcea-clar-engine-guard.yml` rulează la fiecare modificare relevantă, în pull request și zilnic. Monitorul extern `VC-INV-2026-001` și toate monitoarele ChatGPT VÂLCEA CLAR sunt declarate retrase și înlocuite de workflow-urile site-ului.

## Joburi canonice

- **Ediții autonome:** 07:45 și 18:30, ora Europe/Bucharest;
- **Radar surse:** la fiecare șase ore;
- **„Unde ieșim” ingest:** la fiecare șase ore;
- **Investigația Olănești–Omniasig:** de două ori pe zi;
- **Distribuție Facebook:** verificarea cozii la fiecare 15 minute;
- **Quality gate:** la modificările relevante;
- **Ownership guard:** zilnic și la schimbarea codului de automatizare.

Orele și workflow-urile sunt definite machine-readable în `engine/automation_registry.json`; documentația nu este schedulerul.

## Arhitectură

- `engine/automation_registry.json` — registrul canonic al joburilor, proprietarului și politicilor runtime;
- `.github/workflows/valcea-clar-*.yml` — programarea și execuția server-side;
- `data/` — catalogul editorial public și sursa paginilor vizibile;
- `ingest/` — surse și motorul de descoperire pentru localuri;
- `scripts/discover_news_facts.py` — descoperire deterministă din surse primare;
- `scripts/generate_edition.py` — generatorul `deterministic_zero_llm_v2`;
- `scripts/reconcile_ingest.py` — potrivește ingestia cu catalogul și deschide coada editorială, fără publicare automată;
- `site/runtime/` — runtime-ul public și feedul actualizat de engine;
- `scripts/build_sites_export.py` — payload de prezentare pentru site-ul existent; nu programează și nu generează conținut;
- `social/` — outbox Facebook curatat editorial și jurnal de deduplicare;
- `investigations/` — dosarele de anchetă și starea monitoarelor server-side;
- `ops/` și `state/` — registre de sănătate, reconciliere și reluare.

## Reguli nenegociabile

- Publicăm fapte, nu presupuneri: fiecare afirmație importantă are sursă și dată de verificare.
- Operatorul juridic, administratorii sau asociații apar numai din surse publice adecvate și cu relevanță editorială.
- Prețurile sunt publice doar dacă provin dintr-un meniu oficial verificat recent.
- Recenzia editorială este separată de publicitate, invitații și gratuități.
- Creatorii locali nu sunt numiți „influenceri culinari” până nu există dovadă de conținut alimentar local, audiență relevantă și transparență comercială.
- O listare comercială nu cumpără clasamentul, nota sau verdictul editorial.
- Ingestia, potrivirile de nume și sursele T3 nu pot schimba direct catalogul public.
- Nicio descoperire din ingestie nu ajunge direct pe Facebook; numai elementele marcate explicit `ready` în outbox sunt eligibile.
- Schimbarea unei surse nu publică automat fapte materiale; se păstrează ultimul rezultat bun și se deschide o sarcină de reverificare.

## Verificări pentru dezvoltare

Aceste comenzi sunt teste locale facultative; nu sunt și nu pot deveni scheduler de producție.

```bash
python valcea-clar/scripts/validate_site_engine_ownership.py
python valcea-clar/scripts/validate_data.py
python valcea-clar/scripts/reconcile_ingest.py --check
python valcea-clar/ingest/venue_ingest.py --no-network
python valcea-clar/validation/validate.py
python valcea-clar/scripts/build_public_data.py
python valcea-clar/scripts/build_sites_export.py
python valcea-clar/social/facebook_publish.py --self-test
python valcea-clar/social/facebook_publish.py
```

Fluxurile păstrează ultimul rezultat bun, sunt idempotente unde publică extern și persistă starea în repository. Credențialele externe, precum tokenul Meta, există numai ca secrete ale runtime-ului GitHub Actions.
