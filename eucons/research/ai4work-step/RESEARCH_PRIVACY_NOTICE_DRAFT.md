# Informare privind protecția datelor — cercetarea AI4WORK STEP

**Stare:** DRAFT / NU SE PUBLICĂ ȘI NU SE ACTIVEAZĂ COLECTAREA până la completarea contactului de confidențialitate, aprobarea temeiului juridic, verificarea procesatorilor/logurilor, legarea retenției/ștergerii, acceptarea screening-ului DPIA și aprobarea procedurii de exercitare a drepturilor.

## Cine prelucrează datele

Operator: **EUROCONSULT SRL, CUI 14250864**. Determinarea operatorului pentru această cercetare și faptul că EUROCONSULT SRL deține `eucons.ro` sunt consemnate first-party în `CONTROLLER_DETERMINATION_DRAFT.json`. Această determinare închide identitatea operatorului, dar nu autorizează colectarea și nu dovedește configurația efectivă a contului de găzduire, accesul la loguri, retenția tehnică, ștergerea din backup sau rolurile operaționale ale furnizorilor.

Calitatea de solicitant/lider al proiectului, titular de facturare a unui serviciu de hosting sau implementator tehnic nu este tratată automat ca rol de operator GDPR. Orice persoană împuternicită/subîmputernicită și orice entitate cu acces la date la nivel de respondent trebuie legate separat prin documentele și configurația aplicabile înainte de go-live.

Contact pentru întrebări și exercitarea drepturilor privind protecția datelor: **[PRIVACY_CONTACT_REQUIRED_BEFORE_GO_LIVE]**.

Dacă EUROCONSULT SRL are desemnat un responsabil cu protecția datelor (DPO) sau desemnează un canal dedicat pentru această prelucrare, datele aplicabile vor fi publicate aici înainte de colectare. Existența unui DPO nu este presupusă prin acest document.

## De ce facem cercetarea

Chestionarele sunt folosite exclusiv pentru fundamentarea unei analize de nevoi privind competențele digitale și folosirea responsabilă a inteligenței artificiale în muncă, în contextul AI4WORK STEP. Răspunsurile nu sunt folosite pentru marketing, profil comercial, înscriere automată într-un proiect, selectarea participanților, evaluarea performanței unei persoane sau luarea unei decizii individuale cu efect juridic ori similar semnificativ.

## Ce date solicităm

Formularele analitice nu solicită nume, CNP, adresă exactă, telefon, e-mail, semnătură, fotografie, cont social, numele angajatorului, CUI sau documente. Nu solicităm categorii speciale de date.

Sunt colectate numai categorii prestabilite și largi necesare analizei, precum regiunea, banda de vârstă/statutul și familia ocupațională pentru adulți, respectiv sectorul agregat, dimensiunea organizației și tipul respondentului pentru angajatori, împreună cu răspunsuri controlate la întrebările despre competențe, utilizarea AI, formare, bariere și tipuri de sarcini/procese.

În designul pre-producție curent **nu există câmpuri de text liber în formularele analitice**. Răspunsurile sunt limitate la opțiuni prestabilite, scale, booleene și matrici. Aceasta reduce riscul introducerii accidentale a numelor, angajatorilor, datelor de contact sau altor identificatori prin text liber. Celulele statistice foarte mici sunt suprimate sau agregate în raportare.

## Temeiul juridic

**Propunere supusă aprobării EUROCONSULT SRL înainte de colectare:** art. 6 alin. (1) lit. (f) GDPR — interes legitim pentru realizarea unei analize de nevoi documentate și proporționale. Evaluarea interesului legitim este păstrată separat în `GDPR_LIA_DRAFT.json`; determinarea operatorului este închisă, însă LIA și temeiul juridic final rămân neaprobate până la confirmarea faptului că toate măsurile de minimizare, separare, transparență, drepturi și retenție sunt menținute și operaționale.

Bifarea faptului că ați citit informarea confirmă că informarea a fost afișată și participarea este voluntară; această bifă **nu este tratată automat ca temei de consimțământ GDPR**.

Dacă EUROCONSULT SRL nu aprobă temeiul propus sau dacă designul se schimbă material, colectarea rămâne oprită până la stabilirea și documentarea unui temei juridic adecvat și revalidarea controalelor afectate.

## Cine poate avea acces

Accesul la răspunsurile la nivel de respondent trebuie limitat la personalul desemnat pentru cercetare și la furnizorii tehnici strict necesari, în baza rolurilor și contractelor verificate înainte de activare. Baza de cercetare trebuie să fie separată fizic/logic și prin credențiale de CRM și de infrastructura comercială.

EUROCONSULT SRL este operatorul cercetării. Rolurile titularului/administratorului tehnic al contului de găzduire, furnizorului Claus Web și ale oricărui alt furnizor activ în calea reală de procesare trebuie documentate separat înainte de lansare. Nici facturarea hostingului, nici accesul tehnic la cPanel nu sunt folosite singure pentru a deduce un rol GDPR mai larg decât cel demonstrat.

Lista procesatorilor/subprocesatorilor și orice transfer în afara SEE trebuie verificată și documentată înainte de lansare. Dacă această verificare nu este închisă, colectarea nu se activează.

Răspunsurile la nivel de respondent nu trebuie trimise către servicii externe de AI generativ/LLM. Orice utilizare AI în analiză se limitează la material suficient de de-identificat/agregat și necesită re-evaluare dacă această condiție se schimbă.

## Date tehnice și tracking

Formularele nu folosesc advertising pixels, fingerprinting, cross-site tracking, identificatori CRM sau analytics comerciale. Adresa IP și user-agent-ul nu intră în setul analitic sau în exportul NF06. Profilul generic de Raw Access furnizat first-party de Claus Web este documentat separat și poate include IP-ul vizitatorului, timestamp, metoda HTTP, URL-ul complet inclusiv query string, Referer și User-Agent; de aceea răspunsurile și identificatorii direcți sunt interziși în query string. Înainte de activare trebuie citită și legată configurația efectivă a contului `eucons.ro` pentru arhivare/retenție/acces, iar corpurile cererilor, răspunsurile și cheia brută de idempotency nu trebuie logate de aplicație.

Pentru evitarea dublării unui răspuns în cazul unui retry de rețea se folosește o cheie aleatoare UUIDv4 pentru o singură tentativă de trimitere. Cheia brută nu este stocată în setul analitic și nu este derivată din identitatea, IP-ul, dispozitivul sau conturile respondentului. Adaptorul de referință întoarce după trimitere un `response_id` opac, distinct de cheia brută, care poate fi păstrat de respondent ca receipt tehnic. Binding-ul live trebuie să păstreze această proprietate fără să creeze un registru identitate–răspuns.

## Cât timp păstrăm datele

Propunerea de retenție este documentată în `GDPR_RETENTION_SCHEDULE_DRAFT.json`. În designul curent, răspunsurile brute și normalizate la nivel de respondent se șterg după validarea analizei și înghețarea pachetului de dovezi, dar nu mai târziu de 180 de zile de la închiderea colectării și, în lipsa unui hold juridic documentat, nu mai târziu de **31 martie 2027**.

După ștergere pot fi păstrate pe termenul necesar proiectului numai rezultate agregate cu control de divulgare, registrul surselor/provenienței și hash-uri de integritate care nu permit reconstruirea răspunsurilor individuale. Datele opționale de contact, dacă vor exista într-un formular complet separat, nu pot fi legate de răspuns și au o retenție mai scurtă.

## Drepturile dumneavoastră

În condițiile GDPR, puteți solicita acces, rectificare, ștergere sau restricționare, după caz. Dacă temeiul juridic final este interesul legitim, vă puteți opune prelucrării în condițiile art. 21 GDPR. Aplicabilitatea dreptului la portabilitatea datelor depinde de temeiul juridic final: potrivit art. 20 GDPR, acest drept se aplică atunci când prelucrarea este bazată pe consimțământ sau contract, este efectuată prin mijloace automate și privește date furnizate de persoana vizată. Prin urmare, dacă EUROCONSULT SRL aprobă interesul legitim ca temei final, portabilitatea nu este dreptul aplicabil pentru această prelucrare; dacă temeiul se schimbă la consimțământ sau contract și sunt îndeplinite condițiile art. 20, înainte de colectare trebuie implementată și validată o cale separată de export într-un format structurat și prelucrabil automat. Dacă se ajunge la folosirea consimțământului ca temei, informarea și procedura vor include și mecanismul de retragere a consimțământului înainte de lansare.

Solicitările se trimit la contactul de confidențialitate al EUROCONSULT SRL care trebuie completat și verificat înainte de lansare. Procedura operațională este menținută separat în `GDPR_DATA_SUBJECT_RIGHTS_PROCEDURE_DRAFT.json` și rămâne neaprobată până la stabilirea temeiului juridic final și a binding-ului live.

Pentru dreptul de acces, implementarea de referință poate genera pe baza receipt-ului opac o copie numai a propriului răspuns analitic și a metadatelor de proveniență aprobate. Copia nu include hash-uri interne de stocare, digesturi de idempotency/transport, cheia brută de idempotency, starea internă a unui hold de restricționare/obiecție, markerul anti-replay după ștergere sau datele altor respondenți. Orice câmp nou introdus ulterior în stocare trebuie revizuit înainte de a putea fi inclus în această copie. Aceasta reprezintă numai componenta de copie a datelor: operatorul trebuie să aplice procedura aprobată de autentificare a solicitantului și să furnizeze separat confirmarea și informațiile despre prelucrare cerute de art. 15 GDPR.

Deoarece formularul este proiectat să nu colecteze identitatea, operatorul poate să nu poată identifica un anumit răspuns numai după numele persoanei. Nu vom colecta și păstra date suplimentare exclusiv pentru a construi un registru identitate–răspuns. Dacă păstrați receipt-ul tehnic `response_id` primit la trimitere, implementarea live aprobată trebuie să permită localizarea răspunsului în baza de cercetare și, pentru ștergere, eliminarea atomică a rândului analitic și a receipt-ului intern de idempotency, fără consultarea CRM, a contactelor opționale, a IP-ului sau a dispozitivului. Dacă receipt-ul nu mai este disponibil și operatorul poate demonstra că nu poate identifica răspunsul, solicitarea va fi tratată conform procedurii aprobate și regulilor GDPR aplicabile, fără a introduce identificare disproporționată.

Aveți dreptul de a depune o plângere la autoritatea competentă de protecție a datelor. Pentru România, autoritatea de supraveghere este Autoritatea Națională de Supraveghere a Prelucrării Datelor cu Caracter Personal (ANSPDCP).

## Participarea este voluntară

Puteți decide să nu completați sau să nu trimiteți formularul fără nicio consecință. Angajatorii, partenerii, furnizorii de formare sau orice alte entități care distribuie invitația nu trebuie să condiționeze un serviciu, loc de muncă, beneficiu sau acces la proiect de participarea la cercetare.

---

**GO-LIVE gate:** determinarea operatorului este închisă (`EUROCONSULT SRL`, CUI 14250864), dar activarea rămâne blocată până la: contact de confidențialitate verificat; LIA/temei juridic aprobat; matricea de aplicabilitate a drepturilor reconciliată cu temeiul final, inclusiv portabilitate/retragere consimțământ dacă devin aplicabile; informare finală publicată înainte de întrebări; procedură de exercitare a drepturilor aprobată și operațională; procesatori/subprocesatori și transferuri verificate; configurația efectivă `eucons.ro` pentru logging verificată; retenție/ștergere executabilă; screening DPIA acceptat; endpoint și research-only store validate; smoke TEST TWIN provider-bound complet; producția rămâne `false` până la închiderea tuturor acestor condiții.
