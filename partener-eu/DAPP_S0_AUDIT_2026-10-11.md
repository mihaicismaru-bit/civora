# PARTENER.EU — DAPP S0: audit pe cinci dosare reale

**Data verificării:** 2026-10-11. **Stare:** S0 AUDIT / BASELINE, nu dosare finale, nu publicare.  
**Snapshot surse interne:** \`validation/dapp_s0_pilot_20261011.json\`.  
**Protocol propus:** PR #1389 (\`DOSSIER_ANALYSIS_PUBLICATION_PROTOCOL_V1.md\`), încă Draft.  
**Scope:** exclusiv produs public PARTENER.EU; fără date de clienți, credențiale sau MySMIS privat.

## 1. Ce am măsurat

\`ingest/state/dossier_enrichment_queue.json\` din 2026-10-11T12:28:25Z: 192 dosare (16 complete, 27 avansate, 123 în construcție, 26 identificare); 182 în coada de îmbogățire, 4 în verificare de tip entitate. Acest scor măsoară **prezența unor secțiuni**, nu demonstrarea fiecărui fapt din ghid.

Pentru S0 am înghețat **identitatea + sursele + lacunele + starea internă**, folosind hashul blobului Git pentru fiecare sursă de date. Nu confundăm Git blob SHA cu hashul raw al ghidului. Niciun original PDF/ZIP nou nu a fost arhivat și hashuit în acest sprint; lipsa este explicită și blochează declararea \`CONFIRMED\` în pipeline-ul final.

## 2. Cele cinci dosare și verdictul de triere

| Pilot | ID existent | Baseline | Problema prioritară | Verdict S0 |
| --- | --- | --- | --- | --- |
| P01 FAMI AM22N | \`mai-fami-am22n-2026\` | P11 OPEN, PUBLISHABLE; profunzime 50/100 | conflict **RON/EUR** în pagina autorității; sumarele de beneficiari nu concordă; lipsesc grile/documente/activități din analiza curentă | \`P0_ANALYST_REVIEW_REQUIRED\`, fără modificare de site |
| P02 POCIDIF Acțiunea 1.2 | \`mipe-e62eeffb2413dc306c\` | \`PUBLIC_CONSULTATION\` intern, profunzime 33/100 | dovezi găsite de consultare 2023/2024 și lansări de apel distincte în 2024; nu avem probă pentru consultare *curentă* în 2026 | \`P0_ENTITY_VERSION_RECONCILE\`; nu declara „consultare curentă” |
| P03 AFIR Schema Energie | \`afir-energy-2026\` | P11 \`DISCOVERED\`, PUBLISHABLE | AFIR listează ghidul V7 (iunie 2026); lipsesc hashul documentului și verificarea sesiunii/versiunii actuale | \`P1_OFFICIAL_GUIDE_ANALYSIS\`; nu promova OPEN |
| P04 PDD Management riscuri | \`mipe-3b3ab4d9361706669b\` | \`OPEN\` intern, profunzime 50/100, fără deadline în queue | actualizarea ghidului și modificările nu sunt reconciliate; sursa oficială directă a eșuat la citirea S0 | \`P0_LIFECYCLE_UNCONFIRMED\`; nu promova OPEN |
| P05 FM Stocare standalone | \`me-fm-storage-standalone-2026\` | P11 OPEN, PUBLISHABLE, mulți fact classes verificate intern | control pozitiv pentru costuri, condiții tehnice, punctaj, buget și versiune; P11 sursă cu \`asOf 2026-09-27\` | \`P1_POSITIVE_CONTROL_REVERIFY\`, nu recertificare automată |

**Important:** un status intern \`OPEN\` din coada de enrichment nu reprezintă starea live autoritativă a apelului. Gate-ul public actual este separat și mai strict.

## 3. Prima analiză reală — P01 AM22N

**Surse oficiale:**
- https://fed.mai.gov.ro/11317/lansare-apel-am22n-dezvoltarea-de-resurse-educationale-si-programe-de-formare-pentru-specializarea-cadrelor-didactice-in-vederea-predarii-limbii-romane-ca-limba-straina/
- https://fed.mai.gov.ro/wp-content/uploads/2026/09/Ghid-specific-AM22N-semnat.pdf

**Verificări din documentul semnat**, nu inventar automat:
- Bugetul FEN și moneda: **2.000.000 RON**, în sumarul ghidului, pagina tipărită 3, și în secțiunea E, pagina tipărită 14. Anunțul oficial text principal confirmă lei. **În sumarul HTML al aceleiași pagini oficiale apare însă 2.000.000 EUR**. Nu tratăm sumarul HTML ca dovadă suficientă pentru EUR. Conflictul trebuie păstrat în evidence ledger pentru audit.
- Termen: **16.10.2026, ora 16:00**, ghidul, sumar și secțiunea F. Cu doar câteva zile rămase, acest dosar are prioritate mare.
- Eligibilitate: în secțiunea G, pagina tipărită 15, sunt menționate **instituții publice din România; asociații/fundații române cu personalitate juridică; instituții de învățământ/cercetare autorizate în România; organizații internaționale** — cu condiții suplimentare și reguli despre cobeneficiari. Sumarul HTML al paginii spune doar „Organizații non-guvernamentale”. Nu extrapolăm eligibilitatea unui caz particular fără ghidul general, lista condițiilor și verificarea documentelor.
- Grilă: ghidul indică prag total **70 din 100** și praguri pe secțiuni A, B, C (secțiunea H, paginile tipărite 16–17). Lista documentelor justificative apare în secțiunea G/I. Coada actuală indică aceste două dimensiuni ca insuficient dezvoltate editorial.
- Cofinanțare: ghidul menționează **CFN 100%**, defalcat 90% FEN / 10% FNN; această valoare este diferită de procentul de grant pentru orice alt program și necesită etichetare corectă.

**Verdict:** versiunea de date P11 are deja 2.000.000 **RON** și deadline 16.10.2026, deci nu afirmăm că site-ul afișează neapărat cifra greșită. Riscul rămas este că un cititor ori un parser care ia **sumarul paginii oficiale** ar putea produce EUR sau ar restrânge artificial solicitantul la ONG. Protocolul trebuie să privilegieze ghidul semnat cu pagină/versiune și să marcheze conflictul oficial; nu trebuie să schimbe automat o valoare deja corectă în P11.

**Următorul pas P01:** descărcare autorizată + hash pentru ghid, ghid general, anexe, clarificări, cerere și grilă; legarea fiecărei condiții la pagina sa; compunere analiză de 30 de secunde + 3 acțiuni urgente, după validator.

## 4. P02 — Acțiunea 1.2: fenomenul de „consultare veșnică”

Corpusul intern al dosarului MIPE conține pagina de consultare și status \`PUBLIC_CONSULTATION\`, dar fără termen, grant și eligibilitate verificate. Am identificat prin pagini ale **Organismului Intermediar pentru Cercetare**:
- consultarea inițială 02.08–24.08.2023;
- relansarea consultării **11–13.09.2024** (pagina Autorității Naționale pentru Cercetare);
- anunțuri ale unor **apeluri distincte** în Acțiunea 1.2, inclusiv apeluri pentru proiecte predefinite, ulterior în 2024.

Surse:
- https://www.poc.mcid.gov.ro/ro/articol/4417/solicitantului-aferent-ac-iunii-1-2-sprijin-pentru-proiecte-in-domeniul-tehnologiilor-avansate-si-crearea-de-hub-uri-de-inovare-i-transfer-tehnologic-in-domenii-prioritare-din-cadrul-pocidif
- https://www.research.gov.ro/s-a-relansat-in-consultare-publica-ghidul-solicitantului-aferent-actiunii-1-2-sprijin-pentru-proiecte-in-domeniul-tehnologiilor-avansate-si-crearea-de-hub-uri-de-inovare-si-transfer-tehnologic-in-dome-21438/
- https://poc.research.gov.ro/ro/articol/4428/apeluri-de-proiecte-pocidif-prioritatea-1

**Verdict:** istoria surselor este clară, însă identitatea exactă a apelului, versiunea ghidului și ciclul curent sunt încă \`UNKNOWN\`. Nu putem afirma, doar dintr-o pagină din 2024, existența unei consultări active în octombrie 2026. Acest dosar este un test de **entity mapping + lifecycle** înainte de analiza financiară.

## 5. P03 — AFIR Schema Energie: document versus sesiune

Sursa T1: https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-schema-energie/

AFIR confirmă pe pagina index:
- scop: investiții în producerea energiei electrice solare pentru autoconsum;
- beneficiari descriși sumar: întreprinderi din agricultură și industria alimentară, OUAI/FOUAI;
- ghidul **V7 – iunie 2026**, listat cu cerere de finanțare și note auxiliare.

**NU reprezintă** dovadă că sesiunea este deschisă acum. P11 o clasifică \`DISCOVERED\`, iar acesta rămâne nivelul intern de referință. Pentru \`CURRENT/OPEN\` trebuie anunț de sesiune sau registru oficial actual, nu doar existența ghidului. În S1 capturăm ghidul V7 și grilele și separăm eligibilitatea generală de tipurile CAEN, locurile de consum și condițiile tehnice.

## 6. P04 — PDD: corrigendum/ghid aplicabil și status eronat posibil

ID: \`mipe-3b3ab4d9361706669b\`. Coada arată \`OPEN\` intern, dar lipsesc deadline, grant/financing, solicitant, costuri, scoring și indicatori. Ghidul inițial și o actualizare din septembrie 2026 sunt **descoperite prin URL-uri din repo**:
- https://mfe.gov.ro/ghiduri_pdd/pdd-ghidul-solicitantului-conditii-de-accesare-a-finantarii-pentru-proiecte-noi-de-management-al-principalelor-tipuri-de-risc-identificate-in-planul-national-de-management-riscurilor-de-dezastre/
- https://mfe.gov.ro/pddtj-actualizeaza-ghidul-solicitantului-conditii-de-accesare-a-finantarii-pentru-proiecte-noi-de-management-al-principalelor-tipuri-de-risc-identificate-in-pnmrd/
- https://mfe.gov.ro/wp-content/uploads/2026/09/dc9ca8e9ca95998906c724742ea1bf23.pdf

Citirea directă a paginii oficiale a eșuat în sesiunea S0. Nu pretindem că am citit PDF-ul/ZIP-ul actualizat. Testul pentru S1: inventar documente și hash, diff punctual ghid-versiune/corrigendum, dovezi pentru status și termen, apoi eligibility/costs/scoring.

## 7. P05 — FM stocare: control pozitiv de granularitate

ID: \`me-fm-storage-standalone-2026\`. P11 asOf 2026-09-27 conține deja fact classes pentru status, deadline, budget, grant, beneficiaries, eligibility și scoring, plus detalii tehnice. Sursele oficiale indicate sunt:
- https://legislatie.just.ro/Public/DetaliiDocumentAfis/313994
- https://vn.prefectura.mai.gov.ro/oportunitati-de-finantare-societati-comerciale-septembrie-2026/

P11 include **150 mil. EUR** bugetul apelului, plafoane EUR/MWh și per întreprindere, eligibilitatea solicitantului, raportul C/P, tipul racordării, selecția și un termen 30.10.2026. Aceste date reprezintă **baseline-ul de test din P11**, nu o nouă confirmare a ghidului la 11.10.2026: actul oficial nu a putut fi deschis în această sesiune. În S1 folosim acest dosar pentru a măsura ponderea afirmațiilor deja existente care pot primi pagină/articol, versiune și hash fără schimbarea conținutului.

## 8. Metrici pe cinci piloți

- 5/5 au **ID stabil** în proiecția/queue existente.
- 3/5 au depth score în queue: AM22N 50, POCIDIF A1.2 33, PDD 50; 2/5 sunt dosare P11 care nu intră în coada actuală (AFIR energie și FM stocare).
- 1/5 are **ghid semnat citit direct și afirmații localizate la pagină**: AM22N.
- 1/5 are surse oficiale de istoric consultare/call events examinate: POCIDIF A1.2.
- 1/5 are pagină AFIR actuală de ghid verificată: AFIR energie.
- 2/5 au documentele aplicabile ori ciclul actual **neverificate prin lectură integrală**: PDD și FM stocare.
- 0/5 au în noul protocol claim ledger complet cu raw document hash, parser_version și run_id + audit complet al anexelor. Aceasta este sarcina **S1**, nu o „finalizare” inventată în S0.

Acesta este un baseline de cercetare **parțial, explicit**, nu evaluarea finală a celor cinci apeluri.

## 9. S1: execuție exactă, fără bloat

**Ordine P0:** AM22N (termen apropiat, contradictoriu sumar/ghid) → PDD (OPEN intern fără deadline) → POCIDIF A1.2 (consultare istorică versus apeluri ulterioare). **P1:** AFIR energie → FM stocare (control pozitiv).

1. Refolosește achiziția existentă. Pentru MIPE numai SURFACEMC poate achiziționa; motorul PARTENER consumă corpusul și analizează. Pentru celelalte surse, achiziție oficială existentă.
2. Construiește **un singur claim ledger** cu page/section/quote/hash/version/fetched_at/parser_version/run_id. Nu adăuga un bot per apel.
3. Analistul ChatGPT ia câte un dosar, citește toate sursele aplicabile, scrie \`analysis_candidate\` și \`editorial_review\`. Nu publică din chat.
4. Validatorul exclude statusuri vechi, bugete în monedă greșită, beneficiary-vs-target-group și material facts fără dovadă exactă. Conflictele duc la \`PROVISIONAL_FAIL_CLOSED\`, cu LKG.
5. Numai după 5/5 replay-uri și diffs verificate se discută schimbarea generatorului public.

**Checkpoint S0:** \`PARTENER-DAPP-S0-20261011-FIVE-PILOTS\`.  
**Rollback:** documentele/manifestul S0 sunt independente de motor; eliminarea PR-ului/branch-ului nu afectează datele, deploymentul sau P11.  
**Gate:** \`RESEARCH_BASELINE_PASS / ANALYST_FULL_REVIEW_PENDING / NO_PUBLICATION\`.
