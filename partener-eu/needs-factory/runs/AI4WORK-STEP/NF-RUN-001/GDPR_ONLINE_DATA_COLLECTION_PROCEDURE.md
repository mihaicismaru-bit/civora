# AI4WORK STEP — Procedură GDPR pentru colectarea online a datelor primare

**Run:** AI4WORK-STEP / NF-RUN-001  
**Scop:** colectarea datelor primare necesare analizei de nevoi, prin două formulare online distincte: adulți și angajatori/organizații.  
**Principiu:** privacy by design / data minimisation. Analiza statistică nu trebuie să conțină identificatori direcți și nu se folosește pentru recrutare, marketing, profilare sau luarea unor decizii individuale.

## 1. Regula de bază

Formularele se proiectează astfel încât baza analitică să nu conțină nume, prenume, CNP, serie/număr CI, adresă exactă, telefon, e-mail, cont online, fotografie, semnătură, numele angajatorului, CUI, numele persoanelor sau alte elemente care permit identificarea directă.

Nu se colectează categorii speciale de date: origine rasială/etnică, opinii politice, convingeri religioase, apartenență sindicală, date genetice/biometrice, date privind sănătatea, viața sexuală sau orientarea sexuală.

Datele necesare cercetării sunt colectate pe categorii largi: regiune, statut, bandă de vârstă, domeniu ocupațional, sector economic, dimensiunea organizației și răspunsurile la întrebările de cercetare.

## 2. Două formulare separate

### Formular A — Adulți

Se implementează conținutul din `QUESTIONNAIRE_ADULTS.md`.

Metadatele permise sunt:
- regiune: Sud-Vest Oltenia / Sud-Muntenia / Centru;
- statut: șomer înregistrat / persoană ocupată potențial eligibilă / alt statut de verificat;
- bandă de vârstă: 30–39 / 40–49 / 50–59 / 60+;
- domeniu ocupațional / familie de posturi, numai categorie largă.

`respondent_id` nu se solicită persoanei. El se generează automat de platformă sau se atribuie la export, fără tabel de corespondență cu identitatea persoanei.

### Formular B — Angajatori / organizații

Se implementează conținutul din `QUESTIONNAIRE_EMPLOYERS.md`.

Metadatele permise sunt:
- regiune;
- sector / CAEN agregat;
- dimensiune: 1–9 / 10–49 / 50–249 / 250+;
- tip respondent: management / HR / operațional-tehnic / altul.

Nu se solicită denumirea organizației, CUI-ul sau numele persoanei care răspunde. `organisation_id` se generează automat sau se atribuie la export.

Întrebarea privind disponibilitatea pentru focus-grup / expresie de interes rămâne în formular, dar orice date de contact se colectează printr-un formular separat, cu scop, informare GDPR și perioadă de păstrare distincte. Baza de contacte nu se unește cu baza analitică.

## 3. Configurarea obligatorie a platformei online

Platforma aleasă trebuie să permită cel puțin următoarele setări:

1. **Nu colectează automat adresa de e-mail.**
2. **Nu solicită autentificarea respondentului.** Opțiunea „limit one response” nu se activează dacă presupune login sau stocarea identității.
3. **Nu include câmpuri de tip upload.**
4. **Nu include tracking publicitar, analytics de marketing sau fingerprinting.**
5. **IP-ul nu se colectează de operator**, dacă platforma permite dezactivarea. Dacă platforma păstrează inevitabil IP/device metadata, formularul se tratează ca prelucrare pseudonimizată și se aplică varianta de consimțământ explicit de la pct. 5.
6. **Accesul la răspunsuri este limitat** la persoanele desemnate pentru cercetare/analiză, pe principiul need-to-know.
7. **Autentificare cu MFA** pentru conturile care administrează formularul și rezultatele.
8. **Criptare în tranzit** și stocare securizată.
9. Furnizorul platformei trebuie verificat contractual; dacă acționează ca persoană împuternicită, trebuie să existe condiții conforme art. 28 GDPR / DPA și să fie cunoscuți subprocessatorii și eventualele transferuri în afara SEE.
10. Se preferă găzduirea în UE/SEE sau o soluție self-hosted/enterprise cu control contractual și tehnic suficient.

## 4. Prima pagină a fiecărui formular — informare înainte de întrebări

Titlu: **Cercetare pentru fundamentarea analizei de nevoi AI4WORK STEP**

Text recomandat:

> Participarea la acest chestionar este voluntară. Scopul cercetării este fundamentarea unei analize de nevoi privind competențele digitale și utilizarea inteligenței artificiale în muncă. Formularul nu este o cerere de înscriere într-un proiect, nu reprezintă o ofertă de formare și răspunsurile nu vor fi folosite pentru decizii individuale privind respondentul.
>
> Operator: **[DENUMIRE OPERATOR]**, contact: **[E-MAIL GDPR/DPO]**.
>
> Formularul este proiectat pentru a nu colecta identificatori direcți precum nume, CNP, telefon, e-mail sau adresă exactă. Vă rugăm să nu introduceți asemenea informații în câmpurile de text liber.
>
> Datele vor fi analizate statistic și pe categorii agregate (de exemplu regiune, bandă de vârstă, statut, sector sau dimensiunea organizației). Rezultatele publicate/utilizate în analiza de nevoi vor fi agregate sau anonimizate.
>
> Răspunsurile sunt utilizate exclusiv pentru cercetarea și documentarea analizei de nevoi AI4WORK STEP și pentru justificarea metodologică/auditul aferent acesteia. Nu sunt utilizate pentru marketing.
>
> Dacă baza colectată este anonimă de la sursă, operatorul nu va putea identifica ulterior răspunsul unei persoane și, prin urmare, nu îl va putea localiza după identitate. Dacă platforma utilizată generează identificatori tehnici/pseudonimi, aceștia sunt separați de baza analitică și se elimină conform perioadei de retenție stabilite.
>
> Pentru întrebări privind protecția datelor sau exercitarea drepturilor, puteți utiliza: **[E-MAIL GDPR/DPO]**. Aveți dreptul de a depune o plângere la autoritatea competentă pentru protecția datelor.

La finalul acestei pagini se introduce o bifă obligatorie, nebifată implicit:

**„Am citit informațiile de mai sus și doresc să particip voluntar la cercetare.”**

Această bifă nu trebuie combinată cu marketing, recrutare sau alte scopuri.

## 5. Varianta dacă platforma prelucrează date personale/pseudonime

Dacă platforma colectează automat e-mail, login, IP, cookie identificator, token asociabil unei persoane sau alte date ce permit identificarea, acestea trebuie fie dezactivate, fie formularul se tratează ca prelucrare de date personale.

În această situație, înainte de lansare se stabilește în scris temeiul juridic. Pentru o cercetare voluntară de acest tip, dacă se alege consimțământul conform art. 6 alin. (1) lit. (a) GDPR, acesta trebuie să fie liber, specific, informat, neechivoc, separat de alte scopuri și la fel de ușor de retras pe cât a fost de acordat.

Bifa devine:

**„Sunt de acord cu prelucrarea datelor furnizate și a metadatelor tehnice strict necesare, exclusiv pentru cercetarea de fundamentare a analizei de nevoi AI4WORK STEP, conform Notei de informare.”**

Nu se utilizează căsuțe prebifate.

Dacă retragerea trebuie posibilă până la anonimizare, platforma trebuie să ofere un cod unic de răspuns/pseudonim pe baza căruia răspunsul poate fi localizat fără a colecta identitatea persoanei. După anonimizarea ireversibilă, respondentul trebuie informat că răspunsul individual nu mai poate fi identificat.

## 6. Câmpurile de text liber

Q12 adulți și E04/E09 angajatori sunt singurele zone cu risc de introducere accidentală a datelor personale.

Înaintea fiecărui câmp liber se afișează avertizarea:

**„Nu introduceți nume de persoane, numele angajatorului/organizației, clienți, adrese, e-mailuri, telefoane sau alte informații care pot identifica o persoană.”**

La export, câmpurile libere sunt verificate manual înainte de includerea în baza analitică. Dacă apar identificatori, copia analitică se redactează/anonimizează. Textul cu identificatori nu se introduce în Evidence Registry.

## 7. Distribuirea formularului

Pentru reducerea prelucrării de date personale, linkul se distribuie preferabil prin organizații partenere, rețele profesionale, AJOFM/structuri relevante, organizații de angajatori, camere de comerț, asociații și canale publice, fără importarea listelor de persoane în platforma de formulare.

Pentru fiecare regiune se ține un `DISTRIBUTION_LOG` separat cu: regiune, canal/organizație de distribuire, data transmiterii, tip public țintă și numărul aproximativ de persoane/organizații cărora li s-a pus la dispoziție chestionarul, dacă acesta este cunoscut. Nu se înscriu numele destinatarilor în logul analitic.

Dacă se folosesc liste de e-mail/telefon existente pentru invitații, legalitatea utilizării acelor liste se verifică separat; existența formularului GDPR-compliant nu justifică automat folosirea oricărei baze de contacte.

## 8. Colectare, export și pseudonimizare

La închiderea colectării:

- se exportă un fișier RAW nemodificat;
- fișierului i se calculează hash SHA-256 și se înscriu data/ora exportului și operatorul exportului;
- se păstrează într-un folder cu acces restricționat;
- se creează o copie analitică separată;
- în copia analitică se atribuie `respondent_id` / `organisation_id` aleatoriu dacă platforma nu le-a generat;
- se elimină orice metadate tehnice care nu sunt necesare analizei;
- se anonimizează/redactează textul liber;
- se validează structura pe regiune și celelalte straturi cerute de metodologia NF06;
- numai copia curățată intră în Needs Factory / Evidence Registry.

Nu se păstrează un tabel de corespondență între ID-ul analitic și identitatea respondentului.

## 9. Retenția

Pentru datele tehnice sau pseudonime care pot permite identificarea se aplică principiul stocării minime: se păstrează numai până la validarea, curățarea și anonimizarea setului, cu termen operațional recomandat de maximum 90 de zile de la închiderea colectării, dacă nu există o obligație legală documentată care impune alt termen.

Setul final anonim/agregat, metodologia, instrumentele de cercetare, manifestele, hash-urile și rezultatele statistice pot fi păstrate pentru justificarea proiectului și audit conform obligațiilor aplicabile proiectului, întrucât nu trebuie să mai conțină date care identifică persoane.

## 10. Acces și securitate

Accesul la formular și exporturi se acordă nominal, minimului necesar de persoane. Nu se partajează linkuri publice către rezultate. Conturile administrative folosesc MFA. Exporturile brute se păstrează criptat / în storage cu control de acces și logging. Orice transmitere se face prin canale securizate.

În cazul unui incident care afectează date personale sau pseudonime, operatorul activează procedura internă de incident/breach și evaluează obligațiile de notificare conform GDPR, inclusiv termenul de 72 de ore atunci când art. 33 este aplicabil.

## 11. Control de calitate înainte de lansare — GO/NO-GO

Formularul este publicat numai dacă toate condițiile sunt `PASS`:

- operatorul și contactul GDPR/DPO sunt completate;
- scopul este limitat la analiza de nevoi;
- nu se colectează identificatori direcți;
- nu se colectează categorii speciale de date;
- e-mail/login/IP tracking sunt dezactivate sau tratate explicit prin varianta pseudonimizată;
- nota de informare este afișată înainte de întrebări;
- participarea este voluntară și nu este condiție pentru acces la servicii;
- câmpurile libere au avertizare anti-identificare;
- formularul de contact/follow-up este separat;
- rolurile operator / persoană împuternicită și condițiile platformei au fost verificate;
- accesul la rezultate este restricționat;
- există plan de retenție și ștergere;
- există un plan de export, hash, curățare și anonimizare;
- există `DISTRIBUTION_LOG` pe cele trei regiuni;
- instrumentele și structura întrebărilor coincid cu versiunea înghețată în NF-RUN-001.

Dacă unul dintre puncte nu este îndeplinit, colectarea nu începe.

## 12. Output pentru Needs Factory

La final se predau în NF06:

- `ADULT_RAW_EXPORT` + hash;
- `EMPLOYER_RAW_EXPORT` + hash;
- `ADULT_ANALYTIC_DATASET` anonim/pseudonimizat;
- `EMPLOYER_ANALYTIC_DATASET` anonim/pseudonimizat;
- `DISTRIBUTION_LOG` pe regiuni;
- `DATA_CLEANING_LOG`;
- `GDPR_FORM_CONFIGURATION_RECEIPT`;
- `RESEARCH_COVERAGE_REPORT` cu numărul de răspunsuri valide și denominatorul cunoscut / limitările de eșantionare.

Needs Factory nu poate promova concluzii la nivel regional dacă distribuția/coverage-ul nu susține acea inferență.
