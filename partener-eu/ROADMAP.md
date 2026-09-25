# PARTENER.EU — roadmap de producție

Actualizat: 23 septembrie 2026

## Stare curentă

- site public funcțional și monitorizat, cu Funding Concierge ca intrare principală;
- fluxul canonic rămâne DISCOVER → FETCH → HASH → PARSE → NORMALIZE → DEDUP → RECONCILE → QUALITY GATE → PUBLISH → CHECKPOINT → ALERT;
- AFIR este operat pe corpus autoritativ curent, iar PEO calendar este curent; faptele materiale rămân fail-closed în lipsa reconcilierii;
- MySMIS direct este separat de canalul MIPE legacy: un incident al corpusului legacy nu poate bloca ori autoriza automat fapte MySMIS independente;
- sursele discovery-only sunt separate de autoritatea pentru fapte materiale, astfel încât un transport WAF/403 pe o suprafață de discovery nu degradează artificial readiness-ul editorial;
- frontend-ul nu mai poate prezenta un apel ca OPEN numai dintr-un snapshot static vechi: OPEN cere status verificat și termen verificat neexpirat;
- dosarele sunt construite universal pentru apelurile identificate și sunt prioritizate OPEN → PUBLIC_CONSULTATION → EXPECTED/UPCOMING → rest;
- schimbările de hash rămân candidate până la reconciliere; niciun score de completeness/depth nu este interpretat drept probabilitate de aprobare.

## Situație MAI / FED — 23.09.2026

- driftul semantic al indexului oficial de calendare a fost revizuit: pagina continuă să indice calendarul IMFV v11.0, fără dovadă de versiune nouă; schimbarea este tratată ca non-materială și nu autorizează actualizări de termen/buget/status;
- driftul semantic al paginii Ghidului general a fost revizuit: versiunea curentă rămâne PNAI v4.0, 17.03.2026, Instrucțiunea AM 19; schimbarea este tratată ca non-materială;
- registrul oficial de apeluri are o schimbare materială deja reconciliată: șapte apeluri FAMI au fost lansate la 16.09.2026 — AM41D, AM22M, AM22L, AM22N, AM11I, AM11H și AM2A1G — cu termen 16.10.2026 ora 16:00;
- conflictul de monedă din sumarul paginilor de lansare a fost rezolvat prin ghidurile specifice semnate: alocările publicate sunt în RON/lei; overlay-ul canonic `RES-MAI-FED-FAMI-OPEN-CALLS-20260923` păstrează separat dovezile pentru status/termen și pentru buget;
- cele șapte apeluri sunt deja PUBLISHABLE în dosare și lifecycle, cu linkuri către paginile oficiale de lansare și ghidurile specifice semnate; următoarea muncă este enrichment-ul câmpurilor încă UNKNOWN, nu republicarea statusului sau a bugetului.

## Ordine de execuție

1. Enrichment-ul celor șapte apeluri MAI/FED deja publicate: beneficiari → activități → costuri → cofinanțare → criterii → indicatori, exclusiv din ghidurile specifice semnate și anexele oficiale.
2. Reducerea blocajelor materiale de freshness/transport rămase, fără relaxarea fail-closed.
3. Continuarea enrichment-ului dosarelor OPEN, apoi PUBLIC_CONSULTATION și EXPECTED/UPCOMING.
4. Extinderea coverage cu surse oficiale lipsă și generarea de dosar pentru fiecare apel identificat.
5. Audit UX continuu: căutare → rezultate → filtre → dosar → sursa oficială, desktop + mobil + keyboard/focus.
6. Curățarea incrementală a driftului/telemetriei legacy, numai cu teste și rollback clar.
7. Matching solicitant–apel și checklist explicabil, fără scoruri prezentate ca probabilitate de aprobare.
8. Watchlist și alerte fără duplicate.
9. Știri, modificări de ghid și analize numai din kernel factual verificat.

## Reguli de închidere

Nicio consultare, dată de calendar sau valoare dintr-un draft nu devine automat
apel deschis, termen, buget, grant, eligibilitate ori punctaj. Oportunitățile fără
dovezi suficiente rămân vizibile numai ca monitorizate/în verificare.

Un incident este închis numai după test + dovadă + checkpoint + replay/rollback +
ieșire verificată. Pentru frontend este obligatoriu lanțul reproducere → fix →
regression test → CI/deploy → readback public. Pentru ingestie sunt obligatorii
dovada de fetch/hash/parse/reconcile/QG și starea finală.
