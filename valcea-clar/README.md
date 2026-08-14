# VÂLCEA CLAR — Unde ieșim

Verticală CIVORA pentru restaurante, cafenele, puburi, terase, localuri de noapte și locuri de relaxare din județul Vâlcea.

## Stare

`INTEGRATED_V0.4` — secțiunea publică, motorul de ingestie, reconcilierea editorială, radarul de surse, contractul de integrare în site și distribuția Facebook funcționează ca un flux fail-closed.

## Arhitectură

- `data/` — catalogul editorial public și sursa paginilor vizibile;
- `ingest/` — 30 de surse și primul lot de 19 localuri urmărite;
- `scripts/reconcile_ingest.py` — potrivește ingestia cu catalogul și deschide coada editorială, fără publicare automată;
- `ops/ingest_aliases.json` — identități cunoscute între cele două straturi;
- `site/integration.json` — navigația principală, modulul de homepage și legăturile cu celelalte secțiuni;
- `web/` — interfața mobilă și proiecția publică;
- `scripts/build_sites_export.py` — pachetul determinist pentru site-ul existent `valceaclar.ro`;
- `social/` — outbox Facebook curatat editorial, distribuit direct prin Meta Graph API și jurnal de deduplicare;
- `investigations/` — dosarele de anchetă, separate de verticala comercială/editorială.

## Reguli nenegociabile

- Publicăm fapte, nu presupuneri: fiecare afirmație importantă are sursă și dată de verificare.
- Operatorul juridic, administratorii sau asociații apar numai din surse publice adecvate și cu relevanță editorială.
- Prețurile sunt publice doar dacă provin dintr-un meniu oficial verificat recent.
- Recenzia editorială este separată de publicitate, invitații și gratuități.
- Creatorii locali nu sunt numiți „influenceri culinari” până nu există dovadă de conținut alimentar local, audiență relevantă și transparență comercială.
- O listare comercială nu cumpără clasamentul, nota sau verdictul editorial.
- Ingestia, potrivirile de nume și sursele T3 nu pot schimba direct catalogul public.
- Nicio descoperire din ingestie nu ajunge direct pe Facebook; numai elementele marcate explicit `ready` în outbox sunt eligibile.

## Comenzi locale

```bash
python valcea-clar/scripts/validate_data.py
python valcea-clar/scripts/reconcile_ingest.py --check
python valcea-clar/ingest/venue_ingest.py --no-network
python valcea-clar/validation/validate.py
python valcea-clar/scripts/build_public_data.py
python valcea-clar/scripts/build_sites_export.py
python valcea-clar/social/facebook_publish.py --self-test
python valcea-clar/social/facebook_publish.py
```

Fluxul de ingestie rulează la șase ore, păstrează ultimul rezultat bun și produce o coadă editorială cu `publication_effect=NONE`. Distribuția Facebook este un flux separat și idempotent; publică numai elemente aprobate în outbox și numai când credențialele Meta sunt disponibile ca secrete de runtime.
