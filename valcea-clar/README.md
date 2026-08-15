# VÂLCEA CLAR — CIVORA site engine

Verticală CIVORA pentru știri locale, restaurante, cafenele, puburi, terase, evenimente, investigații și distribuție editorială în județul Vâlcea.

## Stare

`INTEGRATED_V0.6 — SITE_ENGINE_AND_SOCIAL_ENGINE_OWNED` — ingestia, monitorizarea, generarea edițiilor, proiecția publică, validarea și publicarea socială rulează din repository prin GitHub Actions, cu stare persistentă și politici fail-closed.

## Proprietatea execuției

Sursa tehnică unică este `mihaicismaru-bit/civora`, directorul `valcea-clar/`. Toate joburile recurente sunt înregistrate în `engine/automation_registry.json` și sunt executate numai de runner-e GitHub-hosted.

ChatGPT are exclusiv rol de consolă de administrare și dezvoltare. Nu este scheduler, runtime editorial, depozit de stare, motor de generare sau instrument de publicare socială. Sunt interzise pentru producție:

- taskuri sau monitoare recurente ChatGPT;
- publicarea directă ori programată pe rețele din ChatGPT;
- accesul ChatGPT la credențialele platformelor sociale;
- execuția dintr-o conversație sau de pe calculatorul utilizatorului;
- runner-e `self-hosted` ori cron-uri locale;
- chei și endpointuri OpenAI, Anthropic sau Gemini în fluxurile VÂLCEA CLAR;
- orice dependență de API LLM plătit pentru monitorizare, generare sau publicare.

`validate_site_engine_ownership.py` și `social/validate_social_engine.py` verifică fail-closed aceste reguli. Workflow-ul `valcea-clar-engine-guard.yml` rulează la fiecare modificare relevantă, în pull request și zilnic.

## Joburi canonice

- **Ediții autonome:** 07:45 și 18:30, ora Europe/Bucharest;
- **Radar surse:** la fiecare șase ore;
- **„Unde ieșim” ingest:** la fiecare șase ore;
- **Investigația Olănești–Omniasig:** de două ori pe zi;
- **Social Publication Engine:** verifică toate cozile sociale la fiecare 15 minute;
- **Quality gate:** la modificările relevante;
- **Ownership guard:** zilnic și la schimbarea codului de automatizare.

Orele, workflow-urile și proprietarul sunt definite machine-readable în `engine/automation_registry.json`. Configurația canalelor este definită separat în `social/channel_registry.json`; documentația nu este schedulerul.

## Social Publication Engine

Workflow-ul unic este `.github/workflows/valcea-clar-social-publishing.yml`. Acesta pregătește conținutul nativ pe canal, verifică proveniența imaginilor, consultă coada, publică prin adaptorul platformei și persistă starea și deduplicarea în repository.

Starea actuală a canalelor:

- **Facebook:** adaptor direct Meta API activ și verificat;
- **Instagram, Threads, LinkedIn, TikTok, YouTube Shorts, Telegram și WhatsApp:** blocate fail-closed până la existența unui adaptor și a unor credențiale verificate;
- pentru canalele blocate, engine-ul poate păstra pachete durabile de outbox, dar nu poate publica și nu poate delega publicarea către ChatGPT.

Fostul workflow dedicat `.github/workflows/valcea-clar-facebook.yml` este retras. Toată distribuția socială intră prin workflow-ul social unic.

## Arhitectură

- `engine/automation_registry.json` — registrul canonic al joburilor, proprietarului și politicilor runtime;
- `.github/workflows/valcea-clar-*.yml` — programarea și execuția server-side;
- `social/channel_registry.json` — registrul canalelor, adaptoarelor, stării și secretelor de runtime;
- `social/validate_social_engine.py` — controlul fail-closed al proprietății publicării sociale;
- `social/facebook_publish.py` — adaptorul direct Meta API;
- `social/facebook_outbox.json` și `social/facebook_state.json` — coada și jurnalul de publicare/deduplicare;
- `data/` — catalogul editorial public și sursa paginilor vizibile;
- `ingest/` — surse și motorul de descoperire pentru localuri;
- `scripts/discover_news_facts.py` — descoperire deterministă din surse primare;
- `scripts/generate_edition.py` — generatorul `deterministic_zero_llm_v2`;
- `scripts/reconcile_ingest.py` — potrivește ingestia cu catalogul și deschide coada editorială, fără publicare automată;
- `site/runtime/` — runtime-ul public și feedul actualizat de engine;
- `scripts/build_sites_export.py` — payload de prezentare pentru site-ul existent; nu programează și nu generează conținut;
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
- Nicio descoperire din ingestie nu ajunge direct pe o rețea; numai elementele eligibile din outboxul canalului pot fi publicate.
- Fiecare canal are copy, format, stare și deduplicare proprii; cross-postarea verbatim nu este fluxul normal.
- Schimbarea unei surse nu publică automat fapte materiale; se păstrează ultimul rezultat bun și se deschide o sarcină de reverificare.
- Lipsa adaptorului, credențialelor sau aprobării editoriale blochează publicarea fără fallback în ChatGPT.

## Verificări pentru dezvoltare

Aceste comenzi sunt teste locale facultative; nu sunt și nu pot deveni scheduler de producție.

```bash
python valcea-clar/scripts/validate_site_engine_ownership.py
python valcea-clar/social/validate_social_engine.py
python valcea-clar/social/facebook_publish.py --self-test
python valcea-clar/scripts/validate_data.py
python valcea-clar/scripts/reconcile_ingest.py --check
python valcea-clar/ingest/venue_ingest.py --no-network
python valcea-clar/validation/validate.py
python valcea-clar/scripts/build_public_data.py
python valcea-clar/scripts/build_sites_export.py
```

Fluxurile păstrează ultimul rezultat bun, sunt idempotente unde publică extern și persistă starea în repository. Credențialele externe, precum tokenul Meta, există numai ca secrete ale runtime-ului GitHub Actions.
