# PARTENER.EU — Protocol de analiză și publicare a dosarelor (DAPP v1, propunere)

**Status: DRAFT / REVIEW — fără modificarea motorului sau a site-ului.** Data: 11 octombrie 2026.
**Principiu:** autoritatea finanțatoare este sursa canonică. ChatGPT este analistul editorial al dosarului; PARTENER.EU validează și publică fail-closed. Separăm acest produs de dosarele client/MySMIS din EU PROJECT FACTORY.

## 0. Problema reală din repo

Snapshotul dossier_enrichment_queue.json, generat la 2026-10-11T12:28:25Z, raportează 192 de dosare: 16 complete, 27 avansate, 123 în construcție și 26 de identificare; 182 sunt încă în coada de îmbogățire și 4 necesită revizia tipului de entitate.

Scriptul score_dossier_depth.py verifică 12 dimensiuni (status, termen, finanțare, proveniență și opt secțiuni). O secțiune nevidă poate crește scorul fără ca fiecare afirmație să aibă dovezi la nivel de pasaj/pagină. Scorul de profunzime NU reprezintă eligibilitatea, corectitudinea sau probabilitatea de aprobare.

**Obiectiv:** mai puține dosare superficiale și mai multe dosare în care beneficiarul poate lua o decizie argumentată, fără să citească singur toate anexele.

## 1. Răspunderea operațională

- **SURFACEMC:** doar achiziția MIPE din România, cu URL, fetched_at, hash, parser_version, run_id; nici analiză materială, nici publish.
- **PARTENER ingest:** FETCH → HASH → PARSE → NORMALIZE → DEDUP → version map; corpus oficial, LKG și audit.
- **ChatGPT, analist editorial:** citește ghidurile, anexele, ordinele și grilele; verifică afirmațiile în document; reconstruiește eligibilitate, costuri, criterii, documente, obligații, riscuri și acțiuni; întoarce dosar structurat + registrul afirmațiilor și sursele pentru fiecare fapt.
- **Validator determinist PARTENER:** verifică schema, identitatea apelului, proba per fapt, statusul OPEN, versiuni, conflicte, non-halucinație, test, replay și rollback. Nu publică propuneri care nu trec.
- **Generator/Pages:** publică atomic card, dosar, istoric material, canonical și sitemap, apoi verifică public readback.
- **Utilizator:** intervenție numai la blocaj autentic de acces, aprobare de mediu protejat sau decizie pe care documentele oficiale nu o permit.

Analiza ChatGPT trebuie integrată într-un job/orchestrare explicită cu acces la documentele reale. Nu presupunem că ChatGPT face parte din runtime-ul actual al site-ului sau că execută automat în absența unei astfel de integrări.

## 2. Flux unic

DISCOVER → FETCH → HASH → PARSE → NORMALIZE → DEDUP → RECONCILE VERSIONS → CLAIM LEDGER → CHATGPT ANALYST PASS → CONTRADICTION CHECK → QUALITY GATE → PUBLISH → PUBLIC READBACK → CHECKPOINT → ALERT.

**G0 — Entitatea:** deosebește PROGRAMME / CALL / GUIDE_DRAFT / GUIDE_FINAL / CORRIGENDUM / ANNEX / CALENDAR / RESULT / ADMIN_NOTICE. Fiecare dosar aparține unui apel cu identificator stabil, program și autoritate. Un document generic sau anunț administrativ nu poate deveni CALL.

**G1 — Corpusul:** verifică existența și versiunea aplicabilă a anunțului, ghidului, anexelor, grilei, modelului cererii/bugetului, calendarului, clarificărilor, ordinelor și legislației. Fiecare fișier este AVAILABLE / NOT_PUBLISHED / NOT_APPLICABLE / FETCH_FAILED / MISSING; un ZIP enumerat nu înseamnă anexe analizate.

**G2 — Fact ledger:** extrage afirmații atomice cu valori, unități, domeniu de aplicare, calificatori și dovezi exacte. Păstrează pagina, articolul, tabelul sau anexa, citatul scurt, URL-ul, hash-urile, fetched_at, parser_version, run_id, versiunea și data verificării.

**G3 — Analyst Pass:** ChatGPT confruntă tot corpusul cu facts extrase, produce interpretări etichetate ANALYSIS (niciodată OFFICIAL_FACT), justificări, necunoscute, contradicții, o matrice de eligibilitate și pașii concreți. Include o recitire adversarială: ce afirmație ar putea infirma un evaluator consultând ghidul?

**G4 — Reconciliere:** tratează corrigenda și actele de modificare în funcție de aplicabilitate și interval. Ultimul link nu este automat autoritativ. Divergențele T1 între versiuni/surse sunt CONFLICT până la dovada de rezolvare.

**G5 — Quality gates:** două axe independente: EVIDENCE_QUALITY (adevăr/proveniență/versiune) și DECISION_UTILITY (claritate/utilitate/exhaustivitate relevantă). Nu folosim un scor unic ca permis automat de publicare.

**G6 — Release atomic:** se generează card, dosar și alerte doar din aceeași versiune validată. La eșec se păstrează LKG; fără delta materială nu se emite alertă.

## 3. Matricea analitică obligatorie

| Domeniu | Ce trebuie să primească vizitatorul |
| --- | --- |
| Identificare | autoritate, program, apel/ID, tip apel, teritoriu, versiune ghid și data verificării |
| Lifecycle | deschis / în pregătire / consultare / închis, date și ore oficiale, suspendări, condiții de închidere anticipată |
| Solicitant | forme juridice, dimensiune, vechime, CAEN, condiții financiare, parteneriate, teritoriu, excluderi; separat de grupul țintă |
| Proiect | activități și investiții eligibile, limite tehnice, condiții de amplasament, categorii neeligibile |
| Finanțare | buget total apel versus grant pe proiect; grant minim/maxim, intensitate, contribuție, TVA, ajutor de stat/de minimis, cheltuieli, avans/rambursare |
| Evaluare | praguri eliminatorii, criterii și punctaj, selecție, departajare; fără probabilități de succes inventate |
| Depunere | portal, cerere, buget, anexe, documente obligatorii/condiționale, semnături, termene de pregătire |
| Implementare | durată, indicatori, achiziții, durabilitate, monitorizare, obligații și riscuri |
| Decizie | condiții blocante, capcane, 3 acțiuni prioritare, lucruri de verificat înainte de cheltuirea banilor |
| Proveniență | document + versiune + pasaj/pagină + URL + hash + verificat la + explicit UNKNOWN/CONFLICT |

NU convertim lipsa unei informații în răspuns afirmativ. NOT_APPLICABLE necesită justificare, nu completează mecanic scorul.

## 4. Claim contract

Fiecare fapt material trebuie să aibă: dossier_id, fact_class, value, unit, scope (apel/proiect/solicitant/regiune/schemă), qualifiers, evidence_state (CONFIRMED/UNKNOWN/CONFLICT/SUPERSEDED/NOT_APPLICABLE), authority, document_type, official_url, document_version, page_or_section, evidence_excerpt, raw_sha256, semantic_sha256, fetched_at, parser_version, run_id, last_verified_at și analyst_note.

Status CONFIRMED este respins dacă are numai URL-ul paginii generale sau dacă nu există o dovadă relevantă pentru exact acel fapt. Pentru un document imposibil de extras folosim UNKNOWN/FETCH_FAILED, nu deducții.

## 5. Trei niveluri editoriale și un release gate separat

**A — Identificat:** entitate și sursă recunoscute; un record public poate descrie ce știm, dar nu apare la „Deschise acum” fără status și termen confirmate.

**B — Fișă decizională:** cine poate aplica, ce finanțează, repere financiare, lifecycle și „ce faci acum” — toate câmpurile efectiv afișate au suport oficial. Lipsurile sunt vizibile, nu ascunse.

**C — Dosar analizat complet:** criterii, buget/costuri, checklist, grila, riscuri, obligații, scenarii explicit ilustrative, proveniență, modificări; nivelul este certificat doar după evidență și analiză, nu prin numărul de secțiuni.

Publicabilitatea tehnică rămâne PUBLISHABLE versus PROVISIONAL_FAIL_CLOSED, independentă de nivelul editorial. CURRENT/DEGRADED/STALE/FAIL/QUARANTINED descriu sănătatea dovezilor, nu nivelul de profunzime.

## 6. Șablonul public de dosar

1. **Verdict în 30 de secunde:** status, deadline, finanțare, solicitant și data verificării, plus „Ce faci acum”.
2. **Pot aplica?** DA / NU / DE VERIFICAT, cu toate condițiile cumulative și excluderile, fiecare cu dovadă.
3. **Ce finanțează și cât?** Activități, costuri, ajutor de stat/cofinanțare și un scenariu de buget etichetat clar ca exemplu, nu ca fapt de apel.
4. **Cum sunt selectate proiectele?** Grilă, praguri, punctaj, departajare, riscuri de respingere.
5. **Ce documente și obligații?** Checklist de depunere, apoi implementare/monitorizare.
6. **Primele trei acțiuni utile acum.** Nu mai mult de trei, prioritate după impact și urgență.
7. **Surse și istoricul dosarului.** Pagini/paragrafe, versiuni, corrigenda, delta materială și necunoscute.

Cardul din catalog prezintă doar esențialul și trimite către dosarul cu URL canonic.

## 7. Trierea cozii și prevenirea buclelor

P0 = apel confirmat OPEN cu termen apropiat ori modificare materială în ghid/termene/eligibilitate, cu impact imediat asupra aplicanților.

P1 = consultare/expected cu ghid publicat și acțiuni de pregătire, dosare cu relevanță ridicată și dovezi disponibile.

P2 = arhivă, pagini de program, anunțuri generale fără apel exact.

Când lipsește un câmp, coada cere next_evidence_action precis (ce document, ce anexă, ce pagină, ce fapt), nu „caută mai mult”. Căutările se opresc după încercări bounded, se lasă blocker și se trece la următorul dosar. Nu se reciclează știri vechi.

## 8. Contractul de execuție pentru ChatGPT

Input: ID stabil, snapshot canonic, manifest de documente oficiale, texte/extrageri cu hash și versiune, facts existente, lipsuri și deadline-uri de actualitate.

Eu analizez documentele originale, nu doar outputul parserului; verific eligibilitate versus grup țintă; reconstruiesc plafon, costuri, punctaje, documente și obligații; scriu verdict/explicații, completez claim ledger, semnalez contradicții și fac adversarial review.

Output: analysis_candidate.json + claim_evidence_ledger.json + editorial_review.md + run_id + verdict PASS/DEGRADED/FAIL + next_evidence_action. Nu se persistă duplicate nejustificate ale corpusului, nu se scriu date de client și nu se face publicare directă dintr-un text al modelului.

## 9. Gate-uri de oprire

Refuzăm promovarea unui fapt dacă: documentul nu este oficial/aplicabil; codul apelului este ambiguu; OPEN nu are status + deadline confirmate; beneficiarul final este confundat cu solicitantul; bugetul programului cu grantul proiectului; nu există sursă exactă pentru fact CONFIRMED; grila este estimată; există conflict de versiune; extracția e slabă; public readback ori testul eșuează.

Gata = analiza + fact ledger + diff material + gate PASS + checkpoint + public readback + replay/rollback. La FAIL: păstrează LKG.

## 10. Implementare incrementală după curățenia CIVORA

**Sprint S0 — pilot/benchmark:** 5 dosare reale, câte unul din clasele apel OPEN urgent, consultare, AFIR, MIPE complex și apel cu corrigenda. Înghețăm sursele și constatăm lipsurile reale. 1–2 zile estimate.

**Sprint S1 — evidence ledger:** adăugăm dovada per fapt la structurile deja existente și un validator claim-level, fără rescriere de pipeline. Refactor minim al build_decision_products, finalize_decision_products, score_dossier_depth și quality_gate. 2–4 zile estimate.

**Sprint S2 — ChatGPT Analyst Pass:** execuție explicit orchestrată, bazată pe corpus oficial, cu candidate și adversarial pass; 5/5 piloti. 3–5 zile estimate.

**Sprint S3 — prezentare:** card + fișă + dosar complet + checklist + istoric + source mapping; teste cu IMM, ONG, UAT, fermieri, consultant și mobil. 2–3 zile estimate.

**Sprint S4 — autonomie:** triere zilnică pe diferențe materiale, batch mic de enrichment, gate, readback; un singur checkpoint pentru fiecare schimbare reală. Fără noi workflow-uri per apel. 1–2 zile estimate.

## 11. Criterii de acceptare

- 100% din material facts afișate drept CONFIRMED au dovadă oficială exactă și versiune; zero promovări OPEN fără status/termen oficial actual.
- 5/5 piloti au condiții eliminatorii, bani/cofinanțare, documente, obligații, riscuri și „Ce faci acum”, sau UNKNOWN justificat.
- Zero confuzii între solicitant/grup-țintă și între buget apel/grant proiect în regresii.
- 100% din delta materială publicată are diff, QA, commit, checkpoint, replay/rollback și readback.
- Crește fracția de dosare utile decizional, fără umflarea artificială a scorului, a numărului de workflow-uri sau a notificărilor.

**Status final al acestui fișier:** doar propunere. Nu schimbăm încă motorul, sursele, paginile sau numărul de apeluri publicate.


## 12. Hourly — Dossier Analyst v1 (activat la 2026-10-11)

Worker: **PARTENER Dossier Analyst Hourly**, la fiecare oră, cu un singur \`dossier_id\` activ; **nu** presupune finalizarea unui dosar complex într-o oră. \`PARTENER Site Keeper\` funcționează separat și are proprietatea pentru site/deploy/source health, nu pentru rescrierea candidatului editorial aflat în lucru.

**Selectarea exactă a unității:**
1. Citește ultimul checkpoint verificat, starea PR-urilor și current main.
2. Dacă există dosar \`ANALYSIS_IN_PROGRESS\` cu dovadă nouă accesibilă, continuă-l; altfel selectează cel mai mare impact dintre OPEN cu termen apropiat și confirmat, conflict material, corrigendum care schimbă o decizie, consultare/EXPECTED cu ghid aplicabil și backlogul cu depth scăzut.
3. Nu bloca toată coada pentru un PDF inaccesibil: două strategii oficiale distincte, încercări bounded, \`NEEDS_EVIDENCE\`, apoi alt dosar eligibil. Nu inventa text și nu ocoli restricțiile de acces.
4. Nu reactiva automat analizele finalizate fără dovadă nouă/version change.

**Stările de lucru (independente de publicarea datelor):**
\`SELECTED → ANALYSIS_IN_PROGRESS → NEEDS_EVIDENCE | ANALYZED_PENDING_GATE → PUBLISHABLE_VERIFIED → PUBLISHED_READBACK_PASS\`.
La eroare \`FAIL/QUARANTINED\`, fără publicare. \`ANALYZED_PENDING_GATE\` nu este \`PUBLISHABLE\`.

**Lease și idempotency:** identitate unică \`dossier_id + applicable_source_version_hash + analyst_protocol_version\`. Un singur writer pentru candidatul aferent acelei identități. Dacă există un PR/checkpoint curent pentru același dosar, actualizează numai acel candidat, fără fișiere sau PR-uri duplicate. Reconciliază din nou cu main înainte de orice write sau merge. Nu face commit doar pentru heartbeat.

**Pachetul de predare** (un singur folder/PR reutilizabil pentru o schimbare materială): \`analysis_candidate\`, \`claim_evidence_ledger\`, \`editorial_review\`, \`source_manifest\`, \`next_evidence_action\`, \`diff_before_after\`, \`run_id\`, \`candidate_base_sha\` și \`checkpoint\`. Nu păstrează texte brute duplicate sau date de client. Fiecare claim e \`OFFICIAL_FACT/ANALYSIS/SCENARIO\`; dovezile oficiale au URL, pagină/secțiune, versiune, hash, fetched_at, parser_version și run_id când sunt verificate.

**Publication handoff (separare a autorităților):**
- Analistul ChatGPT produce numai candidate. Nu are voie să modifice direct \`decision_products.json\`, \`p11-public-data.js\` ori pagina publică pe baza propriului text.
- \`DAPP_EVIDENCE_GATE\` este **un gate nou necesar**, nu presupunem că actualul \`quality_gate.py\` îl implementează deja: trebuie testat pentru sursă/versiune/document exact, pagină/citat, contradicții, unități, beneficiar vs. grup țintă, lifecycle, valid_to și hash. **Până la implementarea și trecerea demonstrată a acestui gate, Hourly rămâne ANALYSIS/STAGING-ONLY, fără autopublicare de fapte noi.**
- După implementarea gate-ului, PARTENER generează un material diff determinist, testează \`PUBLISHABLE\`/fail-closed, face review CI exact-head, PR collision-free, merge controlat, Pages și public readback. Automatizarea poate promova numai dacă TOATE gate-urile cerute sunt verzi, inclusiv orice aprobare obligatorie a mediului; nu ocolește GitHub environment. La eșec LKG rămâne servit și se păstrează motivul \`PROVISIONAL_FAIL_CLOSED\`.
- Un apel OPEN fără stare/termen confirmate și actuale, un buget RON/EUR contradictoriu ori eligibilitate nesusținută determină blocajul exact al schimbării materiale, nu dispariția întregului catalog.

**Demonstrația de performanță:** KPI principal = numărul de dosare cu fapte relevante și dovezi complete, nu numărul de rulări sau de cuvinte. Monitorizăm separat \`claims_confirmed_exact\`, \`claims_unknown\`, \`material_conflicts\`, \`application_decision_coverage\`, \`elapsed_to_published_readback\` și \`duplicate_or_stale_release_count=0\`. Fără delta materială, fără alertă.

**Checkpoint inițial:** \`PARTENER-DAPP-S0-20261011-FIVE-PILOTS\`, vezi PR #1390. Prioritate pentru prima analiză: \`mai-fami-am22n-2026\`, cu refacerea verificărilor oficiale și analiză a contradicției de monedă.
