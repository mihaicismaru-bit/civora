# Integrarea „Unde ieșim” în VÂLCEA CLAR

## Arhitectura canonică

Verticala are trei straturi care nu se confundă:

1. **Catalogul editorial public** — `data/places.json`, validat și proiectat în `web/data/places.json`. Numai înregistrările cu `publication_status=public` intră în site și în payloadurile de prezentare.
2. **Motorul de descoperire și ingestie** — `ingest/`, care urmărește surse, deschideri, meniuri și operatori. Rezultatele lui nu modifică direct catalogul public.
3. **CIVORA site engine** — workflow-urile GitHub Actions, registrul `engine/automation_registry.json`, validările și starea persistentă din repository. Acesta este singurul scheduler și runtime de producție.

`reconcile_ingest.py` este puntea dintre catalog și ingestie. Identifică duplicatele, conflictele și localurile noi, apoi generează o coadă editorială. Fiecare element are `publication_effect=NONE` și `auto_publish=false`.

## Proprietatea execuției

Monitorizarea, ingestia, generarea, validarea și distribuția rulează exclusiv în engine-ul site-ului. Conversațiile ChatGPT, taskurile ChatGPT, cron-urile locale și runner-ele `self-hosted` nu fac parte din runtime. ChatGPT poate fi folosit numai ca interfață de administrare și dezvoltare la cerere.

`validate_site_engine_ownership.py` verifică joburile, cron-urile, runner-ele și absența dependențelor LLM. `valcea-clar-engine-guard.yml` rulează în pull request, la schimbările relevante și zilnic.

## Integrarea în site

`site/integration.json` definește:

- intrarea principală „Unde ieșim”, după „Evenimente”;
- subnavigația secțiunii;
- modulul de homepage;
- legăturile contextuale cu Evenimente, Oraș și Investigații;
- regulile de separare dintre editorial și publicitate.

`build_sites_export.py` include acest contract și un modul de homepage cu maximum patru fișe publice. Exportul este numai un payload de prezentare: nu creează un site paralel, nu schimbă DNS-ul și nu execută procese editoriale.

## Flux operațional

1. Ingestia rulează la șase ore în GitHub Actions.
2. Sursele sunt verificate, iar ultimul rezultat bun este păstrat.
3. Reconcilierea produce `ops/ingest_reconciliation.json` și `ops/ingest_review_queue.json`.
4. Un editor confirmă identitatea, adresa, operatorul, programul și meniul atunci când sunt necesare fapte materiale.
5. Numai catalogul public validat alimentează site-ul.
6. Engine-ul reconstruiește proiecția publică, runtime-ul și feedurile.
7. Stratul de prezentare consumă payloadul sau feedul fără a deveni scheduler ori sursă de stare.

## Regula de siguranță

Nicio apariție într-un agregator, nicio schimbare de hash și nicio potrivire de nume nu poate transforma automat un candidat într-o fișă publică. Nicio conversație și niciun task extern engine-ului nu poate publica, monitoriza sau modifica starea canonică.
