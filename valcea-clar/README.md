# VÂLCEA CLAR — Unde ieșim

Verticală CIVORA pentru restaurante, cafenele, puburi, terase, localuri de noapte și locuri de relaxare din județul Vâlcea.

## Stare

`FOUNDATION_V0.2` — nucleu de date, reguli editoriale, proiecție publică, prototip mobil și radar automat de surse. Site-ul public `valceaclar.ro` este servit prin ChatGPT Sites; acest director este stratul canonic CIVORA și produce un export determinist pentru sincronizare, fără a afecta deploymentul PARTENER.EU din același depozit.

## Reguli nenegociabile

- Publicăm fapte, nu presupuneri: fiecare afirmație importantă are sursă și dată de verificare.
- Operatorul juridic, administratorii sau asociații apar numai din surse publice adecvate și cu relevanță editorială.
- Prețurile sunt publice doar dacă provin dintr-un meniu oficial verificat recent.
- Recenzia editorială este separată de publicitate, invitații și gratuități.
- Creatorii locali nu sunt numiți „influenceri culinari” până nu există dovadă de conținut alimentar local, audiență relevantă și transparență comercială.
- O listare comercială nu cumpără clasamentul, nota sau verdictul editorial.

## Structură

- `data/` — registrul canonic de localuri, surse și creatori;
- `schemas/` — contractele de date;
- `scripts/validate_data.py` — quality gate fără dependențe externe;
- `scripts/build_public_data.py` — proiecție fail-closed pentru frontend;
- `scripts/probe_sources.py` — radar de sănătate și schimbări semantice, fără actualizare automată a faptelor;
- `scripts/build_sites_export.py` — pachet determinist pentru site-ul existent din ChatGPT Sites;
- `web/` — prototip static, responsive, pregătit pentru integrarea în CMS;
- `editorial/` — produse editoriale gata de adaptat în CMS;
- `ops/` — coada de verificare, inclusiv task-uri generate când o sursă se schimbă;
- `state/` — registrul persistent de sănătate și hash-uri al surselor;
- `docs/` — standardul editorial și regulile de transparență.

## Comenzi locale

```bash
python valcea-clar/scripts/validate_data.py
python valcea-clar/scripts/build_public_data.py
python valcea-clar/scripts/probe_sources.py --self-test
python valcea-clar/scripts/build_sites_export.py
```

Validatorul blochează publicarea dacă lipsesc sursele, dacă un preț este expirat sau dacă o afirmație despre proprietate nu este documentată.

Radarul rulează programat la șase ore după integrarea în `main`. O modificare semantică a unei surse materiale deschide un task de reverificare și nu schimbă automat nicio adresă, oră, companie sau preț.
