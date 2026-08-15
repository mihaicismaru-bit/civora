# VÂLCEA CLAR — CIVORA site engine

Verticală CIVORA pentru știri locale, restaurante, cafenele, puburi, terase, evenimente, investigații și distribuție editorială în județul Vâlcea.

## Stare

`INTEGRATED_V0.7 — SITE_ENGINE_AND_MULTI_NETWORK_SOCIAL_ENGINE_OWNED` — ingestia, monitorizarea, generarea edițiilor, proiecția publică, validarea și publicarea socială rulează din repository prin GitHub Actions, cu stare persistentă și politici fail-closed.

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
- **Social Publication Engine:** verifică Facebook, Instagram și TikTok la fiecare 15 minute;
- **Quality gate:** la modificările relevante;
- **Ownership guard:** zilnic și la schimbarea codului de automatizare.

Orele, workflow-urile și proprietarul sunt definite machine-readable în `engine/automation_registry.json`. Configurația canalelor este definită separat în `social/channel_registry.json`; documentația nu este schedulerul.

## Social Publication Engine

Workflow-ul unic este `.github/workflows/valcea-clar-social-publishing.yml`. Acesta pregătește copy nativ pentru fiecare canal din aceeași ediție verificată, verifică proveniența imaginilor, consultă cozile, publică prin adaptorul platformei și persistă starea și deduplicarea în repository.

Starea canalelor:

- **Facebook:** adaptor direct Meta API activ și verificat;
- **Instagram:** adaptor direct Meta Graph API activ; publicarea se oprește controlat până când sunt configurate ID-ul contului profesional și tokenul autorizat pentru content publishing;
- **TikTok:** adaptor Content Posting API activ, dar fail-closed până la auditul aplicației pentru publicare publică, verificarea domeniului media și consimțământul explicit per post în administrarea `valceaclar.ro`;
- **Threads, LinkedIn, YouTube Shorts, Telegram și WhatsApp:** rămân blocate fail-closed până la existența unui adaptor și a unor credențiale verificate.

Înregistrările istorice fără rutare pe platforme rămân Facebook-only, astfel încât activarea Instagram și TikTok nu republică automat backlogul. Fostul workflow `.github/workflows/valcea-clar-facebook.yml` a fost eliminat; există un singur scheduler social.

## Arhitectură

- `engine/automation_registry.json` — registrul canonic al joburilor, proprietarului și politicilor runtime;
- `.github/workflows/valcea-clar-*.yml` — programarea și execuția server-side;
- `social/channel_registry.json` — registrul canalelor, adaptoarelor, stării și secretelor de runtime;
- `social/channels/*.json` — configurația editorială și operațională per canal;
- `social/validate_social_engine.py` — controlul fail-closed al proprietății publicării sociale;
- `social/social_common.py` — reguli comune pentru linkuri canonice, fotografii reale, drepturi, programare și rutare;
- `social/facebook_publish.py` — adaptor Facebook;
- `social/instagram_publish.py` — adaptor Instagram `media` → verificare container → `media_publish`;
- `social/tiktok_publish.py` — adaptor TikTok cu creator-info, privacy gate, audit, consimțământ și status tracking;
- `social/build_social_media_assets.py` — proiecția deterministă a fotografiilor aprobate sub `valceaclar.ro/media/social/`;
- `social/facebook_outbox.json` — coada comună compatibilă istoric, cu rutare explicită per platformă pentru materialele noi;
- `social/facebook_state.json`, `instagram_state.json`, `tiktok_state.json` — jurnale și deduplicare independente;
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
- Lipsa adaptorului, credențialelor, aprobării platformei, consimțământului sau aprobării editoriale blochează numai canalul afectat, fără fallback în ChatGPT.

## Verificări pentru dezvoltare

Aceste comenzi sunt teste locale facultative; nu sunt și nu pot deveni scheduler de producție.

```bash
python valcea-clar/scripts/validate_site_engine_ownership.py
python valcea-clar/social/validate_social_engine.py
python valcea-clar/social/facebook_publish.py --self-test
python valcea-clar/social/instagram_publish.py --self-test
python valcea-clar/social/tiktok_publish.py --self-test
python valcea-clar/social/build_social_media_assets.py --self-test
python valcea-clar/scripts/validate_data.py
python valcea-clar/scripts/reconcile_ingest.py --check
python valcea-clar/ingest/venue_ingest.py --no-network
python valcea-clar/validation/validate.py
python valcea-clar/scripts/build_public_data.py
python valcea-clar/scripts/build_sites_export.py
```

Fluxurile păstrează ultimul rezultat bun, sunt idempotente unde publică extern și persistă starea în repository. Credențialele externe există numai ca secrete sau variabile ale runtime-ului GitHub Actions.
