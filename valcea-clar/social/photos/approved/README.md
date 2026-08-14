# VÂLCEA CLAR — fotografii aprobate pentru social media

Acest director conține exclusiv fotografii reale aprobate editorial pentru publicare.

## Condiții obligatorii

Fiecare fotografie trebuie să:

1. prezinte subiectul real al știrii sau un context direct, explicit și actual al acesteia;
2. nu fie generată, ilustrată, compozitată ori prezentată ca fotografie dacă este sintetică;
3. aibă sursa, autorul/creditul și temeiul de reutilizare documentate în `facebook_outbox.json`;
4. aibă drepturi clare: proprietate VÂLCEA CLAR, permisiune scrisă, press kit cu drept de utilizare, licență, domeniu public ori Creative Commons compatibil;
5. fie aprobată editorial înainte ca elementul să primească `status: ready`;
6. aibă text alternativ descriptiv;
7. nu fie o imagine generică de tip stock folosită ca substitut pentru eveniment, persoană, instituție sau loc.

## Structura metadata

```json
"image": {
  "kind": "photograph",
  "synthetic": false,
  "subject_match": true,
  "editor_approved": true,
  "source_type": "staff | reader | official_press | official_institution | licensed_agency | public_domain | creative_commons",
  "source_url": "https://...",
  "credit": "Nume autor / instituție",
  "rights_basis": "owned | written_permission | press_use | licensed | public_domain | creative_commons | official_reuse_permission",
  "rights_note": "dovada sau condiția concretă",
  "alt_text": "descriere accesibilă a fotografiei"
}
```

Publisherul este fail-closed: dacă lipsește oricare dintre condițiile obligatorii, postarea nu pleacă spre Facebook.
