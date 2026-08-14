# VÂLCEA CLAR — Unde ieșim

Verticală CIVORA pentru restaurante, cafenele, puburi, terase, localuri de noapte și locuri de relaxare din județul Vâlcea.

## Stare

`INTEGRATED_V0.3` — secțiunea publică, motorul de ingestie, reconcilierea editorială, radarul de surse și contractul de integrare în site funcționează ca un singur flux fail-closed.

## Arhitectură

- `data/` — catalogul editorial public și sursa paginilor vizibile;
- `ingest/` — 30 de surse și primul lot de 19 localuri urmărite;
- `scripts/reconcile_ingest.py` — potrivește ingestia cu catalogul și deschide coada editorială, fără publicare automată;
- `ops/ingest_aliases.json` — identități cunoscute între cele două straturi;
- `site/integration.json` — navigația principală, modulul de homepage și legăturile cu celelalte secțiuni;
- `web/` — interfața mobilă și proiecția publică;
- `scripts/build_sites_export.py` — pachetul determinist pentru site-ul existent `valceaclar.ro`;
- `investigations/` — dosarele de anchetă, separate de verticala comercială/editorială.

## Reguli nenegociabile

- Publicăm fapte, nu presupuneri: fiecare afirmație importantă are sursă și dată de verificare.
- Operatorul juridic, administratorii sau asociații apar numai din surse publice adecvate și cu relevanță editorială.
- Prețurile sunt publice doar dacă provin dintr-un meniu oficial verificat recent.
- Recenzia editorială este separată de publicitate, invitații și gratuități.
- Creatorii locali nu sunt numiți „influenceri culinari” până nu există dovadă de conținut alimentar local, audiență relevantă și transparență comercială.
- O listare comercială nu cumpără clasamentul, nota sau verdictul editorial.
- Ingestia, potrivirile de nume și sursele T3 nu pot schimba direct catalogul public.

## Comenzi locale

```bash
python valcea-clar/scripts/validate_data.py
python valcea-clar/scripts/reconcile_ingest.py --check
python valcea-clar/ingest/venue_ingest.py --no-network
python valcea-clar/validation/validate.py
python valcea-clar/scripts/build_public_data.py
python valcea-clar/scripts/build_sites_export.py
```

Fluxul programat rulează la șase ore. El verifică sursele, păstrează ultimul rezultat bun, generează drafturi numai dacă există credențiale WordPress și produce o coadă de review cu `publication_effect=NONE`.
