# VÂLCEA CLAR — CIVORA site and social engine

Verticală CIVORA pentru știri locale, restaurante, cafenele, puburi, terase, evenimente, investigații și distribuție editorială în județul Vâlcea.

## Stare

`INTEGRATED_V0.6 — SITE_AND_SOCIAL_ENGINE_OWNED` — ingestia, monitorizarea, generarea edițiilor, proiecția publică, validarea și publicarea pe rețele rulează din repository prin GitHub Actions, cu stare persistentă și politici fail-closed.

## Proprietatea execuției

Sursa tehnică unică este `mihaicismaru-bit/civora`, directorul `valcea-clar/`. Toate joburile recurente sunt înregistrate în `engine/automation_registry.json` și sunt executate numai de runner-e GitHub-hosted.

ChatGPT are exclusiv rol de consolă de administrare și dezvoltare. Nu este scheduler, runtime editorial, depozit de stare, motor de generare sau instrument de publicare socială. Sunt interzise pentru producție:

- taskuri, monitoare sau publicări recurente ChatGPT;
- execuția dintr-o conversație sau de pe calculatorul utilizatorului;
- runner-e `self-hosted` ori cron-uri locale;
- chei și endpointuri OpenAI, Anthropic sau Gemini în fluxurile VÂLCEA CLAR;
- orice dependență de API LLM plătit pentru monitorizare, generare sau publicare;
- păstrarea tokenurilor rețelelor sociale în cod sau în conversații.

`validate_site_engine_ownership.py` verifică fail-closed această regulă, iar workflow-ul `valcea-clar-engine-guard.yml` rulează la fiecare modificare relevantă, în pull request și zilnic. Toate monitoarele și publicările ChatGPT VÂLCEA CLAR sunt declarate retrase și înlocuite de workflow-urile engine-ului.

## Joburi canonice

- **Ediții autonome:** 07:45 și 18:30, ora Europe/Bucharest;
- **Radar surse:** la fiecare șase ore;
- **„Unde ieșim” ingest:** la fiecare șase ore;
- **Investigația Olănești–Omniasig:** de două ori pe zi;
- **Facebook, Instagram și TikTok:** coadă, validare și publicare verificate la fiecare 15 minute;
- **Quality gate:** la modificările relevante;
- **Ownership guard:** zilnic și la schimbarea codului de automatizare.

Orele și workflow-urile sunt definite machine-readable în `engine/automation_registry.json`; documentația nu este schedulerul.

## Social Distribution Engine

`valcea-clar-social.yml` este singurul workflow social. El:

1. creează pachete editoriale native pentru fiecare canal din aceeași ediție verificată;
2. acceptă numai fotografii reale, cu proveniență, drepturi de reutilizare și aprobare editorială;
3. verifică separat eligibilitatea Facebook, Instagram și TikTok;
4. publică direct prin adaptoarele oficiale ale platformelor atunci când acreditările sunt valide;
5. păstrează separat ID-urile publicate, erorile, retry-urile și deduplicarea fiecărei rețele;
6. persistă starea în repository și secretele numai în GitHub Actions;
7. nu apelează și nu reia nicio conversație ChatGPT.

Facebook și Instagram folosesc publicare directă din engine. TikTok rămâne fail-closed până când aplicația este aprobată pentru vizibilitate publică, domeniul media este verificat și fiecare postare primește consimțământul cerut prin administrarea `valceaclar.ro`. Acest control aparține site-ului, nu ChatGPT.

Înregistrările istorice fără obiectul `platforms` rămân Facebook-only. Astfel, activarea noilor adaptoare nu republică retrospectiv întregul backlog pe Instagram sau TikTok.

## Arhitectură

- `engine/automation_registry.json` — registrul canonic al joburilor și proprietarului runtime;
- `.github/workflows/valcea-clar-*.yml` — programarea și execuția server-side;
- `data/` — catalogul editorial public și sursa paginilor vizibile;
- `ingest/` — surse și motorul de descoperire pentru localuri;
- `scripts/discover_news_facts.py` — descoperire deterministă din surse primare;
- `scripts/generate_edition.py` — generatorul `deterministic_zero_llm_v2`;
- `scripts/reconcile_ingest.py` — reconciliere fail-closed, fără publicare automată a faptelor materiale;
- `site/runtime/` — runtime-ul public și feedul actualizat de engine;
- `social/social_channels.json` — registrul canalelor, adaptoarelor și condițiilor de activare;
- `social/social_common.py` — reguli comune de link, fotografie, drepturi și programare;
- `social/facebook_publish.py` — adaptor Facebook;
- `social/instagram_publish.py` — adaptor Instagram;
- `social/tiktok_publish.py` — adaptor TikTok cu creator-info, consimțământ și status tracking;
- `social/*_state.json` — stare și deduplicare independente per platformă;
- `social/build_social_media_assets.py` — proiecția publică deterministă a fotografiilor aprobate;
- `investigations/` — dosarele de anchetă și starea monitoarelor server-side;
- `ops/` și `state/` — registre de sănătate, reconciliere și reluare.

## Reguli nenegociabile

- Publicăm fapte, nu presupuneri: fiecare afirmație importantă are sursă și dată de verificare.
- Operatorul juridic, administratorii sau asociații apar numai din surse publice adecvate și cu relevanță editorială.
- Prețurile sunt publice doar dacă provin dintr-un meniu oficial verificat recent.
- Recenzia editorială este separată de publicitate, invitații și gratuități.
- O listare comercială nu cumpără clasamentul, nota sau verdictul editorial.
- Ingestia, potrivirile de nume și sursele T3 nu pot schimba direct catalogul public.
- Nicio descoperire din ingestie nu ajunge direct pe rețele; numai elementele marcate `ready` pentru platforma respectivă sunt eligibile.
- Copia Facebook nu este reutilizată automat ca text Instagram sau TikTok.
- Imaginile AI, cardurile sintetice și substituenții stock generici sunt respinși pentru știrile despre persoane, locuri sau evenimente reale.
- Schimbarea unei surse nu publică automat fapte materiale; se păstrează ultimul rezultat bun și se deschide o sarcină de reverificare.

## Verificări pentru dezvoltare

Aceste comenzi sunt teste locale facultative; nu sunt și nu pot deveni scheduler de producție.

```bash
python valcea-clar/scripts/validate_site_engine_ownership.py
python valcea-clar/scripts/validate_data.py
python valcea-clar/scripts/reconcile_ingest.py --check
python valcea-clar/scripts/build_public_data.py
python valcea-clar/social/build_social_media_assets.py --self-test
python valcea-clar/social/facebook_publish.py --self-test
python valcea-clar/social/instagram_publish.py --self-test
python valcea-clar/social/tiktok_publish.py --self-test
```

Fluxurile păstrează ultimul rezultat bun, sunt idempotente unde publică extern și persistă starea în repository. Credențialele externe există numai ca secrete sau variabile ale runtime-ului GitHub Actions.
