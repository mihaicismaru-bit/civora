# VÂLCEA CLAR — Politica surselor de semnale

## Principiu

Radarul editorial trebuie să aibă acoperire largă. O sursă de semnal nu este automat o sursă suficientă pentru publicare. Semnalul intră în coada de verificare, iar faptele publicabile sunt confirmate separat, preferabil din surse primare/oficiale și prin documente.

## Clase obligatorii de surse de semnale

### 1. Presa locală — acoperire exhaustivă

Radarul urmărește **toate ziarele și publicațiile locale din județul Vâlcea** identificate ca active: site, RSS/feed când există, pagini oficiale de Facebook/Instagram/YouTube/TikTok și secțiuni tematice relevante. Registrul nu se limitează la publicațiile mari și se actualizează prin discovery continuu.

Utilizare: breaking news, administrație, politică locală, economie, accidente, cultură, sport, horeca, evenimente, investigații și piste pentru documentare.

Regulă: materialul altui ziar este semnal și sursă atribuibilă; VÂLCEA CLAR nu copiază textul și verifică independent afirmațiile materiale.

### 2. Firme și economie locală

Radarul urmărește **site-urile oficiale ale firmelor locale** și, unde există, paginile lor oficiale de social media, comunicatele, secțiunile de noutăți/cariere, magazinele/meniurile și paginile juridice publice.

Priorități: angajatori mari, dezvoltatori, construcții, retail, horeca, turism, transport, energie, sănătate privată, industrie, servicii și firme care contractează cu sectorul public.

Semnale urmărite: deschideri/închideri, investiții, concedieri/angajări, schimbări de management, proiecte, autorizații, incidente, litigii, insolvență, contracte publice, rebranding și modificări de ofertă/preț.

### 3. Instituții administrative

Se urmăresc site-urile și canalele oficiale ale instituțiilor publice locale și județene: Consiliul Județean, prefectură, primării și consilii locale, servicii/deconcentrate, poliție/jandarmerie/ISU, spitale și instituții sanitare publice, instituții de mediu și ape, transport/utilități și alte autorități cu impact local.

Se prioritizează: hotărâri, proiecte de hotărâri, dispoziții, bugete, achiziții, urbanism, autorizații, consultări publice, comunicate, calendare, rapoarte, anunțuri și documente atașate.

### 4. Instituții culturale

Se urmăresc site-urile și canalele oficiale ale teatrelor, filarmonicii, muzeelor, bibliotecilor, caselor de cultură, centrelor culturale, galeriilor, organizatorilor publici de festivaluri și instituțiilor de patrimoniu relevante pentru Vâlcea.

Semnale: spectacole, concerte, expoziții, festivaluri, premiere, anulări, finanțări, concursuri, conduceri, achiziții și controverse documentabile.

### 5. Portalul instanțelor — portal.just.ro

`portal.just.ro` este sursă strategică de semnale pentru litigii și evoluții judiciare care au relevanță publică locală.

Monitorizarea se face după:
- instituții și UAT-uri;
- societăți locale și contractori publici;
- persoane publice numai când există interes public legitim;
- numere de dosar deja asociate unei investigații;
- termene, soluții pe scurt și schimbări de stadiu.

Reguli juridice:
- existența unui dosar nu dovedește vinovăția sau temeinicia unei acuzații;
- se diferențiază reclamant/pârât/inculpat/petent și natura cauzei;
- se verifică instanța, numărul dosarului, obiectul, stadiul și ultima soluție;
- pentru cauze penale se respectă explicit prezumția de nevinovăție;
- datele personale fără relevanță publică nu se reproduc;
- înainte de materiale sensibile se verifică documentele instanței și se solicită poziția părților relevante.

## Niveluri de încredere

- `T1` — document/sursă oficială primară;
- `T1B` — canal oficial al entității;
- `T2` — presă identificabilă și surse secundare reputabile;
- `T3` — agregatoare, directoare, repostări și semnale neverificate.

Orice clasă poate produce un `SIGNAL`; numai dovezile suficiente pot produce un `FACT_KERNEL` publicabil.

## Discovery continuu

Lista surselor este deschisă. Motorul caută periodic publicații, firme și instituții noi, domenii mutate, conturi oficiale și feed-uri noi. O sursă dispărută nu se șterge din istoric; se marchează `INACTIVE`, `MOVED` sau `FAILED` și se caută succesorul.

## Rutare editorială

Semnalele sunt clasificate automat în: `BREAKING`, `ORAȘ`, `JUDEȚ`, `ADMINISTRAȚIE`, `ECONOMIE`, `CULTURĂ`, `EVENIMENTE`, `UNDE_IEȘIM`, `INVESTIGAȚII`, `JUSTIȚIE`, `SPORT` sau `OTHER`. Un semnal poate alimenta mai multe secțiuni, dar se publică o singură versiune canonică a materialului.
