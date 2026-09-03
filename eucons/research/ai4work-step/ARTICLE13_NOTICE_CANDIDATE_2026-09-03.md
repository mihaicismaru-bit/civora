# Informare privind prelucrarea datelor — cercetarea AI4WORK STEP

**Versiune candidat pre-producție — colectarea reală este dezactivată.**

## Operator și contact

Operatorul acestei cercetări este **EUROCONSULT SRL, CUI 14250864**.

Pentru întrebări privind protecția datelor și pentru exercitarea drepturilor prevăzute de GDPR puteți utiliza adresa dedicată **privacy@eucons.ro**.

Această adresă este separată ca scop de fluxurile comerciale. Solicitările privind drepturile persoanelor vizate nu sunt folosite pentru marketing și nu sunt legate de CRM la răspunsurile din cercetare.

## Scopul cercetării

Răspunsurile sunt utilizate exclusiv pentru fundamentarea și validarea unei analize de nevoi privind competențele digitale și utilizarea responsabilă a inteligenței artificiale în muncă, în contextul AI4WORK STEP.

Răspunsurile nu sunt utilizate pentru marketing, profil comercial, înscriere automată într-un proiect, selectarea participanților, evaluarea performanței unei persoane sau luarea unei decizii individuale cu efect juridic ori similar semnificativ.

Participarea la cercetare este voluntară. Refuzul de a participa sau necompletarea formularului nu afectează locul de muncă, accesul la servicii ori formare și nu influențează eligibilitatea într-un proiect.

## Temeiul juridic și interesul legitim

Temeiul juridic aprobat de EUROCONSULT SRL pentru designul actual al cercetării este **art. 6 alin. (1) lit. (f) GDPR — interes legitim**.

Interesul legitim urmărit este realizarea unei analize de nevoi proporționale, documentate și verificabile, prin completarea dovezilor secundare oficiale cu răspunsuri directe ale adulților și angajatorilor. Evaluarea interesului legitim (LIA) a analizat scopul, necesitatea și echilibrul dintre interesul operatorului și drepturile persoanelor vizate și a fost aprobată pentru designul minimizat actual.

Confirmarea faptului că ați citit această informare arată numai că informarea a fost prezentată înainte de întrebări și că participarea este voluntară. Această confirmare **nu este folosită ca temei de consimțământ GDPR**.

## Ce date sunt solicitate

Formularele analitice nu solicită nume, prenume, CNP, adresă exactă, telefon, e-mail, semnătură, fotografie, conturi sociale, numele angajatorului, CUI sau documente. Nu solicită categorii speciale de date și nu conțin câmpuri analitice de text liber.

Sunt utilizate numai categorii prestabilite și suficient de largi necesare analizei, cum ar fi regiunea, banda de vârstă, statutul și familia ocupațională pentru adulți, respectiv regiunea, sectorul agregat, dimensiunea organizației și rolul respondentului pentru angajatori, împreună cu răspunsuri controlate privind competențele, folosirea AI, barierele, formarea și tipurile de sarcini sau procese.

Absența identificatorilor direcți nu înseamnă că răspunsurile la nivel de respondent sunt declarate anonime. Pe durata păstrării lor, EUROCONSULT SRL le tratează conservator ca date cu caracter personal sau potențial identificabile. Numai ieșirile agregate care trec controalele documentate de divulgare și anonimizare pot fi tratate ulterior ca anonime.

## Date tehnice, tracking și separare

Formularele nu folosesc advertising pixels, fingerprinting, cross-site tracking, identificatori CRM sau analytics comerciale. Adresa IP și user-agent-ul nu sunt introduse în setul analitic și nu sunt exportate în NF06.

Răspunsurile sunt destinate unei stocări de cercetare separate de CRM și de fluxurile comerciale. Datele din formular nu trebuie introduse în query string, iar aplicația nu trebuie să logheze corpurile cererilor, răspunsurile sau cheia brută de idempotency.

Pentru retry tehnic, browserul generează un UUIDv4 aleator prin Web Crypto și îl transmite numai într-un header dedicat. Serverul derivă din acesta un `response_id` opac; UUIDv4-ul brut nu este introdus în setul analitic, NF06, CRM sau URL/query string și nu trebuie păstrat în logurile aplicației.

După acceptarea răspunsului, pagina afișează respondentului două valori pe care acesta le poate păstra: `response_id` și **codul privat de verificare** UUIDv4. Același UUIDv4 folosit pentru retry este reutilizat ca dovadă de posesie pentru eventualele cereri ulterioare privind răspunsul, fără colectarea unui nume, e-mail, IP, dispozitiv ori identificator CRM. Codul privat nu este păstrat în clar de aplicația de cercetare și nu poate fi recuperat ulterior de operator. Păstrarea lui de către respondent este opțională și are exclusiv scopul exercitării drepturilor asupra acelui răspuns.

Configurația efectivă a infrastructurii de producție trebuie verificată înainte de activarea colectării reale. Colectarea rămâne blocată până când sunt demonstrate separarea efectivă a stocării de cercetare, controalele de acces și politica de logare/retenție pe contul real.

## Destinatari și furnizori

Accesul la răspunsurile la nivel de respondent este limitat la personalul autorizat pentru cercetare și la furnizorii tehnici strict necesari, numai după validarea rolurilor, contractelor și configurației aplicabile.

Răspunsurile la nivel de respondent nu sunt comunicate angajatorilor, nu sunt copiate în CRM și nu sunt folosite pentru marketing. Răspunsurile brute la nivel de respondent nu trebuie trimise către servicii externe de AI generativ/LLM.

Lanțul efectiv de procesatori/subprocesatori și orice transfer relevant trebuie verificat și documentat înainte de activarea PROD. Niciun transfer internațional la nivel de respondent nu este autorizat implicit de această informare.

## Perioada de păstrare

Răspunsurile brute și normalizate la nivel de respondent se păstrează în stocarea live numai cât este necesar pentru validarea analizei și înghețarea pachetului de dovezi, dar nu mai mult de **180 de zile după închiderea colectării** și, în lipsa unui hold juridic/audit documentat, nu mai târziu de **31 martie 2027**.

Logurile de acces relevante pentru infrastructura cercetării au o limită aprobată de **maximum 7 zile** și nu trebuie să conțină răspunsurile din chestionar sau codul privat de verificare. Respectarea efectivă a acestei limite pe contul real trebuie demonstrată înainte de colectarea PROD.

După ștergerea din stocarea live, orice copie reziduală din backup poate persista numai prin ciclul tehnic preexistent, nereînnoit, și pentru **maximum 92 de zile de la ștergerea live**. Configurația reală a furnizorului trebuie să demonstreze această limită înainte de colectare. Restaurările obișnuite nu trebuie să readucă date șterse în procesarea activă.

Un eventual marker tehnic anti-replay creat după o ștergere aprobată poate conține numai identificatorul opac și metadate tehnice de expirare și trebuie șters în maximum **24 de ore**.

După eliminarea datelor la nivel de respondent pot fi păstrate rezultatele agregate care au trecut controlul de divulgare/anonimizare, registrul surselor și hash-urile de integritate care nu permit reconstruirea răspunsurilor individuale.

## Drepturile persoanei vizate

În condițiile GDPR puteți solicita, după caz, **acces, rectificare, ștergere, restricționare** și puteți formula **opoziție** la prelucrarea întemeiată pe interes legitim, potrivit art. 21 GDPR.

Întrucât temeiul juridic actual este interesul legitim, dreptul la portabilitate prevăzut de art. 20 și retragerea consimțământului nu sunt drepturile aplicabile acestei prelucrări. Dacă temeiul juridic s-ar schimba, matricea drepturilor și informarea trebuie revalidate înainte de continuarea colectării.

Solicitările se transmit la **privacy@eucons.ro**.

Cercetarea este proiectată să nu creeze un registru de identitate. Pentru o cerere legată de un răspuns, respondentul poate furniza `response_id` împreună cu codul privat de verificare afișat după transmitere. Perechea este verificată criptografic ca dovadă de control asupra credentialului aleator folosit la trimiterea inițială; nu reprezintă o verificare a identității civile și nu este legată de CRM, IP, user-agent ori dispozitiv. `response_id` singur nu este tratat ca dovadă suficientă pentru divulgarea sau modificarea unui răspuns.

După verificarea perechii, operatorul confirmă separat dacă acel `response_id` mai există în stocarea izolată și aplică procedura corespunzătoare. Pentru acces, răspunsul include copia controlată a propriului record și informațiile de context cerute de art. 15 GDPR. Nu se divulgă metadate interne de stocare, alte răspunsuri, loguri brute sau date comerciale.

Dacă respondentul nu mai deține codul privat și operatorul poate demonstra că nu poate identifica în mod rezonabil răspunsul fără informații suplimentare, se aplică regulile GDPR relevante, inclusiv art. 11. Nu se creează un registru identitate–răspuns și nu se caută în CRM, IP, user-agent sau date de dispozitiv doar pentru a înlocui codul pierdut.

Aveți dreptul de a depune o plângere la **Autoritatea Națională de Supraveghere a Prelucrării Datelor cu Caracter Personal (ANSPDCP)** și dreptul la o cale de atac în condițiile GDPR.

## Decizii automatizate

Răspunsurile nu sunt utilizate pentru profilare individuală și nu fac obiectul unor decizii automatizate care să producă efecte juridice sau efecte similare semnificative asupra respondentului.

---

**Control de activare:** acest text este un candidat pre-producție și nu dovedește publicarea live. Colectarea reală rămâne dezactivată până când suprafața exactă afișată înainte de întrebări este validată, sunt închise verificările account-specific/provider-bound (logging, retenție, separare storage, backup, procesatori, rights/incident bindings) și este înregistrată separat aprobarea explicită finală `collection-only v0.2`.
