# PARTENER.EU — roadmap de producție

Actualizat: 27 septembrie 2026

## Stare curentă

- site public funcțional și monitorizat, cu Funding Concierge ca intrare principală;
- fluxul canonic rămâne DISCOVER → FETCH → HASH → PARSE → NORMALIZE → DEDUP → RECONCILE → QUALITY GATE → PUBLISH → CHECKPOINT → ALERT;
- AFIR este operat pe corpus autoritativ curent, iar PEO calendar este curent; faptele materiale rămân fail-closed în lipsa reconcilierii;
- MySMIS direct este separat de canalul MIPE legacy: un incident al corpusului legacy nu poate bloca ori autoriza automat fapte MySMIS independente;
- sursele discovery-only sunt separate de autoritatea pentru fapte materiale, astfel încât un transport WAF/403 pe o suprafață de discovery nu degradează artificial readiness-ul editorial;
- frontend-ul nu mai poate prezenta un apel ca OPEN numai dintr-un snapshot static vechi: OPEN cere status verificat și termen verificat neexpirat;
- dosarele sunt construite universal pentru apelurile identificate și sunt prioritizate OPEN → PUBLIC_CONSULTATION → EXPECTED/UPCOMING → rest;
- schimbările de hash rămân candidate până la reconciliere; niciun score de completeness/depth nu este interpretat drept probabilitate de aprobare;
- public readback-ul curent confirmă 13 apeluri OPEN, 25 oportunități în pregătire și 1 consultare, cu manifestul public reconciliat.

## Situație MAI / FED — 27.09.2026

- cele șapte apeluri FAMI lansate la 16.09.2026 — AM41D, AM22M, AM22L, AM22N, AM11I, AM11H și AM2A1G — sunt deja reprezentate PUBLISHABLE în dosare/lifecycle, cu termen 16.10.2026 ora 16:00 și alocările în RON reconciliate din ghidurile specifice semnate;
- două apeluri IMFV cu termen apropiat sunt de asemenea acoperite și publicate din evidență oficială MAI/FED: BV23A și BV10B, ambele cu termen 30.09.2026 ora 16:00; alocările verificate sunt 1.000.000 RON pentru BV23A și 13.203.953 RON pentru BV10B;
- taskurile de hash pentru indexul de calendare, registrul de apeluri și Ghidul general sunt din nou OPEN pe hashurile observate la 27.09.2026. Ele trebuie reconciliate pe starea curentă și nu autorizează automat modificarea statusului, termenului, bugetului, eligibilității sau altor fapte materiale;
- existența unui nou hash task nu invalidează automat faptele deja reconciliate pe paginile/ghidurile exacte ale apelurilor; LKG și provenance rămân păstrate până la o dovadă materială contrară;
- auditul public a identificat un defect de prezentare: unele bugete verificate sunt afișate cu etichete interne de schemă precum Amount / Currency / Basis în loc de o formulare umană. Corecția trebuie să fie strict de prezentare, fără schimbarea valorii, monedei sau provenance-ului.

## Ordine de execuție

1. Corectarea prezentării publice a bugetelor structurate, cu test de regresie și readback public, fără mutarea vreunei fapte materiale.
2. Reconcilierea taskurilor MAI/FED curente pe hashurile observate la 27.09.2026; niciun receipt vechi nu se reutilizează ca dovadă a unui hash nou fără readback autoritativ.
3. Enrichment-ul apelurilor FAMI și IMFV deja publicate: beneficiari → activități → costuri → cofinanțare → criterii → indicatori, exclusiv din ghidurile specifice semnate și anexele oficiale.
4. Reducerea blocajelor materiale de freshness/transport rămase, fără relaxarea fail-closed.
5. Continuarea enrichment-ului dosarelor OPEN, apoi PUBLIC_CONSULTATION și EXPECTED/UPCOMING.
6. Extinderea coverage cu surse oficiale lipsă și generarea de dosar pentru fiecare apel identificat.
7. Audit UX continuu: căutare → rezultate → filtre → dosar → sursa oficială, desktop + mobil + keyboard/focus.
8. Curățarea incrementală a driftului/telemetriei legacy, numai cu teste și rollback clar.
9. Matching solicitant–apel și checklist explicabil, fără scoruri prezentate ca probabilitate de aprobare.
10. Watchlist și alerte fără duplicate.
11. Știri, modificări de ghid și analize numai din kernel factual verificat.

## Reguli de închidere

Nicio consultare, dată de calendar sau valoare dintr-un draft nu devine automat
apel deschis, termen, buget, grant, eligibilitate ori punctaj. Oportunitățile fără
dovezi suficiente rămân vizibile numai ca monitorizate/în verificare.

Un incident este închis numai după test + dovadă + checkpoint + replay/rollback +
ieșire verificată. Pentru frontend este obligatoriu lanțul reproducere → fix →
regression test → CI/deploy → readback public. Pentru ingestie sunt obligatorii
dovada de fetch/hash/parse/reconcile/QG și starea finală.
