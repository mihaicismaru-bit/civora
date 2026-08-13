# PARTENER.EU — roadmap de producție

Actualizat: 13 august 2026

## Stare curentă

- site public funcțional și monitorizat;
- P10.1 Data Plane implementat: contract, acoperire, prospețime, replay și izolare pe sursă;
- P11 integrat: 26 oportunități canonice, 44 dovezi, 26 taskuri de rezoluție;
- STEP-LLL, AFIR Energie 2026, Clustere inovative 1.2.2, PIDS – Servicii de asistență și suport în luarea deciziei și apelul rezidențial Nord-Est sunt publicabile pe baza faptelor materiale demonstrate; restul câmpurilor rămân blocate când nu sunt demonstrate;
- frontend conectat la P11: 4 apeluri OPEN și un apel EXPECTED cu fapte materiale verificate, 26 oportunități monitorizate;
- quality gate local: 18/18 PASS, inclusiv replay semantic fără scriere pentru rezoluții și proiecția publică;
- transportul securizat strict rămâne PENDING până când HTTP și originul Pages păstrează HTTPS;
- P10 rămâne deschis până la 30 de zile distincte de validare eligibilă.

## Ordine de execuție

1. Integrarea ramurii de producție și confirmarea CI/Pages.
2. Activarea HTTPS enforcement din setarea administrativă GitHub Pages.
3. Rezolvarea metodică a celor 21 taskuri P11 rămase, fără autopromovarea faptelor materiale.
4. Extinderea ingestiei MySMIS/MIPE/AFIR/ADR și regenerarea automată a indexului.
5. P12: matching solicitant–apel și checklist explicabil.
6. P13: watchlist și alerte fără duplicate.
7. P14: știri, fișe de apel și rezumate de ghid generate din fapte verificate.
8. P15: email, WordPress și rețele sociale numai după autorizare.
9. P16: pilot operațional complet, 30 de zile validate și CIVORA v1.0.

## Ultimul increment validat

- P11-R01 — poartă deterministă de drift pentru artefactele derivate;
- `apply_resolutions.py --check` recalculează overlay-urile și oprește CI dacă bundle-ul canonic diferă semantic;
- `build_public_projection.py --check` recalculează proiecția și oprește CI dacă payloadul public diferă semantic;
- verificările sunt read-only, raportează hash-uri canonice la abatere și nu schimbă autoritatea de publicare;
- corpusul rămâne la 26 oportunități, cinci publicabile și 21 taskuri deschise sau în review.

## Reguli de închidere

Nicio consultare, dată de calendar sau valoare dintr-un draft nu devine automat
apel deschis, termen, buget, grant, eligibilitate ori punctaj. Oportunitățile fără
dovezi suficiente rămân vizibile numai ca monitorizate/în verificare.
