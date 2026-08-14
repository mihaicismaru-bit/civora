# Integrarea „Unde ieșim” în VÂLCEA CLAR

## Arhitectura canonică

Verticala are două straturi care nu se confundă:

1. **Catalogul editorial public** — `data/places.json`, validat și proiectat în `web/data/places.json`. Numai înregistrările cu `publication_status=public` intră în site și în exportul ChatGPT Sites.
2. **Motorul de descoperire și ingestie** — `ingest/`, care urmărește surse, deschideri, meniuri și operatori. Rezultatele lui nu modifică direct catalogul public.

`reconcile_ingest.py` este puntea dintre ele. Identifică duplicatele, conflictele și localurile noi, apoi generează o coadă editorială. Fiecare element are `publication_effect=NONE` și `auto_publish=false`.

## Integrarea în site

`site/integration.json` definește:

- intrarea principală „Unde ieșim”, după „Evenimente”;
- subnavigația secțiunii;
- modulul de homepage;
- legăturile contextuale cu Evenimente, Oraș și Investigații;
- regulile de separare dintre editorial și publicitate.

`build_sites_export.py` include acest contract și un modul de homepage cu maximum patru fișe publice. Nu creează un site paralel și nu schimbă DNS-ul.

## Flux operațional

1. Ingestia rulează la șase ore și la schimbarea codului/surselor.
2. Sursele sunt verificate, iar ultimul rezultat bun este păstrat.
3. Reconcilierea produce `ops/ingest_reconciliation.json` și `ops/ingest_review_queue.json`.
4. Un editor confirmă identitatea, adresa, operatorul, programul și meniul.
5. Numai catalogul public validat alimentează site-ul.
6. Exportul pentru site conține ruta `/unde-iesim/`, fișele localurilor și modulul de homepage.

## Regula de siguranță

Nicio apariție într-un agregator, nicio schimbare de hash și nicio potrivire de nume nu poate transforma automat un candidat într-o fișă publică.
