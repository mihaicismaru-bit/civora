# VÂLCEA CLAR — UNDE IEȘIM

Verticală editorială și motor de ingestie pentru restaurante, cafenele, puburi,
terase și locuri de relaxare din județul Vâlcea.

## Ce conține v1

- registru de 30 de surse, clasificate T1–T3;
- primul lot de 19 localuri și 3 candidați de monitorizare pentru creatorii locali;
- două deschideri 2026 identificate: Spartan Shopping City și L'Osteria di Ștefan;
- meniuri/prețuri capturate numai când există o sursă datată;
- câmpuri distincte pentru operator, legături publice, dovezi și nivelul de verificare;
- generare de fișe WordPress exclusiv ca **drafturi**;
- validări care blochează promovarea automată a surselor de tip agregator.

## Flux

1. `source_registry.json` definește autoritatea fiecărei surse.
2. `seed_catalog.json.part-*` păstrează faptele curate și dovezile; motorul le reasamblează determinist la citire.
3. `venue_ingest.py` verifică sănătatea surselor și hash-urile semantice.
4. `state/venues.json` păstrează ultimul rezultat canonic.
5. `web/unde-iesim.json` conține numai fișe eligibile pentru review editorial.
6. `wordpress_draft_publish.py` face upsert numai cu `status=draft`.
7. `validation/validate.py` verifică regulile editoriale și integritatea datelor.

## Rulare locală

```bash
python valcea-clar/ingest/venue_ingest.py --no-network
python valcea-clar/validation/validate.py
python valcea-clar/ingest/wordpress_draft_publish.py
```

Pentru probe HTTP reale:

```bash
python valcea-clar/ingest/venue_ingest.py
```

Pentru drafturi WordPress:

```bash
export VALCEA_WP_BASE="https://valceaclar.ro"
export VALCEA_WP_USER="..."
export VALCEA_WP_APP_PASSWORD="..."
python valcea-clar/ingest/wordpress_draft_publish.py --apply
```

Lipsa secretelor nu produce eroare și nu publică nimic.

## Reguli editoriale

- T3 înseamnă descoperire, nu fapt publicabil.
- Proprietarul/operatorul se publică numai cu dovadă.
- O legătură publică are nevoie de sursă și de explicația relevanței.
- Recenzia separă faptele de opinie și declară invitațiile sau beneficiile.
- Programul și prețurile au întotdeauna dată de verificare.
- Nicio fișă nu ajunge automat în starea `publish`.
