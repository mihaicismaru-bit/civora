# Informare privind protecția datelor — cercetarea AI4WORK STEP

**Stare:** DRAFT / NU SE PUBLICĂ ȘI NU SE ACTIVEAZĂ COLECTAREA până la completarea contactului de confidențialitate, aprobarea temeiului juridic, verificarea procesatorilor/logurilor și legarea retenției/ștergerii.

## Cine prelucrează datele

Operator: **EUROCONSULT SRL**, CUI **14250864**.

Contact pentru întrebări și exercitarea drepturilor privind protecția datelor: **[PRIVACY_CONTACT_REQUIRED_BEFORE_GO_LIVE]**.

Dacă EUROCONSULT are desemnat un responsabil cu protecția datelor (DPO), datele acestuia vor fi publicate aici înainte de colectare. Existența unui DPO nu este presupusă prin acest document.

## De ce facem cercetarea

Chestionarele sunt folosite exclusiv pentru fundamentarea unei analize de nevoi privind competențele digitale și folosirea responsabilă a inteligenței artificiale în muncă, în contextul AI4WORK STEP. Răspunsurile nu sunt folosite pentru marketing, profil comercial, înscriere automată într-un proiect, selectarea participanților, evaluarea performanței unei persoane sau luarea unei decizii individuale cu efect juridic ori similar semnificativ.

## Ce date solicităm

Formularele nu solicită nume, CNP, adresă exactă, telefon, e-mail, semnătură, fotografie, cont social, numele angajatorului, CUI sau documente. Nu solicităm categorii speciale de date și vă rugăm să nu introduceți astfel de informații în răspunsurile libere.

Sunt colectate numai categorii largi necesare analizei, precum regiunea, banda de vârstă/statutul și familia ocupațională pentru adulți, respectiv sectorul agregat, dimensiunea organizației și tipul respondentului pentru angajatori, împreună cu răspunsurile la întrebările despre competențe, utilizarea AI, formare și bariere.

Câmpurile de text sunt verificate pentru a respinge tipare uzuale de date de identificare. Celulele statistice foarte mici sunt suprimate sau agregate în raportare.

## Temeiul juridic

**Propunere supusă aprobării operatorului înainte de colectare:** art. 6 alin. (1) lit. (f) GDPR — interesul legitim al EUROCONSULT SRL de a realiza o analiză de nevoi documentată și proporțională. Evaluarea interesului legitim este păstrată separat în `GDPR_LIA_DRAFT.json` și devine valabilă numai după aprobarea operatorului și menținerea tuturor măsurilor de minimizare.

Bifarea faptului că ați citit informarea confirmă că informarea a fost afișată și participarea este voluntară; această bifă **nu este tratată automat ca temei de consimțământ GDPR**.

Dacă operatorul nu aprobă temeiul propus sau dacă designul se schimbă material, colectarea rămâne oprită până la stabilirea și documentarea unui temei juridic adecvat.

## Cine poate avea acces

Accesul la răspunsurile la nivel de respondent trebuie limitat la personalul desemnat pentru cercetare și la furnizorii tehnici strict necesari, în baza rolurilor și contractelor verificate înainte de activare. Baza de cercetare trebuie să fie separată fizic/logic și prin credențiale de CRM și de infrastructura comercială.

Lista procesatorilor/subprocesatorilor și orice transfer în afara SEE trebuie verificată și documentată înainte de lansare. Dacă această verificare nu este închisă, colectarea nu se activează.

Răspunsurile brute nu trebuie trimise către servicii externe de AI generativ/LLM. Orice utilizare AI în analiză se limitează la material suficient de de-identificat/agregat și necesită re-evaluare dacă această condiție se schimbă.

## Date tehnice și tracking

Formularele nu folosesc advertising pixels, fingerprinting, cross-site tracking, identificatori CRM sau analytics comerciale. Adresa IP și user-agent-ul nu intră în setul analitic sau în exportul NF06. Înainte de activare trebuie verificată însă politica reală de logare a hostingului/reverse-proxy-ului, astfel încât corpurile cererilor, răspunsurile și cheia brută de idempotency să nu fie logate, iar metadatele tehnice să aibă retenție minimă.

Pentru evitarea dublării unui răspuns în cazul unui retry de rețea se folosește o cheie aleatoare UUIDv4 pentru o singură tentativă de trimitere. Cheia brută nu este stocată în setul analitic și nu este derivată din identitatea, IP-ul, dispozitivul sau conturile respondentului.

## Cât timp păstrăm datele

Propunerea de retenție este documentată în `GDPR_RETENTION_SCHEDULE_DRAFT.json`. În designul curent, răspunsurile brute și normalizate la nivel de respondent se șterg după validarea analizei și înghețarea pachetului de dovezi, dar nu mai târziu de 180 de zile de la închiderea colectării și, în lipsa unui hold juridic documentat, nu mai târziu de **31 martie 2027**.

După ștergere pot fi păstrate pe termenul necesar proiectului numai rezultate agregate cu control de divulgare, registrul surselor/provenienței și hash-uri de integritate care nu permit reconstruirea răspunsurilor individuale. Datele opționale de contact, dacă vor exista într-un formular complet separat, nu pot fi legate de răspuns și au o retenție mai scurtă.

## Drepturile dumneavoastră

În condițiile GDPR, puteți solicita acces, rectificare, ștergere sau restricționare, după caz, și vă puteți opune prelucrării bazate pe interes legitim. Solicitările se trimit la contactul de confidențialitate care trebuie completat înainte de lansare.

Deoarece formularul este proiectat să nu colecteze identitatea, EUROCONSULT poate să nu poată identifica un anumit răspuns numai după numele persoanei. Dacă implementarea finală oferă un cod/receipt tehnic al răspunsului, păstrarea acelui cod de către respondent poate permite localizarea răspunsului fără introducerea unui registru de identitate.

Aveți dreptul de a depune o plângere la autoritatea competentă de protecție a datelor. Pentru România, autoritatea de supraveghere este Autoritatea Națională de Supraveghere a Prelucrării Datelor cu Caracter Personal (ANSPDCP).

## Participarea este voluntară

Puteți decide să nu completați sau să nu trimiteți formularul fără nicio consecință. Angajatorii, partenerii, furnizorii de formare sau orice alte entități care distribuie invitația nu trebuie să condiționeze un serviciu, loc de muncă, beneficiu sau acces la proiect de participarea la cercetare.

---

**GO-LIVE gate:** contact confidențialitate completat; LIA/temei juridic aprobat; informare finală publicată înainte de întrebări; procesatori/subprocesatori și transferuri verificate; logging verificat; retenție/ștergere executabilă; DPIA screening semnat; endpoint și research-only store validate; smoke TEST TWIN complet; producția rămâne `false` până la închiderea tuturor acestor condiții.
