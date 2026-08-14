# VÂLCEA CLAR — Unde ieșim

Verticală CIVORA pentru restaurante, cafenele, puburi, terase, localuri de noapte și locuri de relaxare din județul Vâlcea.

## Stare

`FOUNDATION_V0.1` — nucleu de date, reguli editoriale, proiecție publică și prototip mobil. Nu există încă o livrare automată spre `valceaclar.ro`; ținta de hosting/CMS trebuie conectată fără a afecta site-ul PARTENER.EU deja publicat din același depozit.

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
- `web/` — prototip static, responsive, pregătit pentru integrarea în CMS;
- `editorial/` — produse editoriale gata de adaptat în CMS;
- `ops/` — coada de verificare și următoarele acțiuni;
- `docs/` — standardul editorial și regulile de transparență.

## Comenzi locale

```bash
python valcea-clar/scripts/validate_data.py
python valcea-clar/scripts/build_public_data.py
```

Validatorul blochează publicarea dacă lipsesc sursele, dacă un preț este expirat sau dacă o afirmație despre proprietate nu este documentată.
