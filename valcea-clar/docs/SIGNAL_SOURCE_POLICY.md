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

#### Topuri de firme și ONRC

Topurile de firme sunt surse de semnale economice: cifră de afaceri, profit, angajați, creșteri/scăderi anuale, lideri pe CAEN/localitate/județ și firme care apar disproporționat de des în contracte publice. Ele generează `SIGNAL_ECONOMIC`, dar cifrele sunt reverificate înainte de publicare.

ONRC este sursă strategică primară pentru denumire juridică, CUI, sediu/puncte de lucru, administratori, asociați, CAEN, înființări, radieri, suspendări, schimbări de sediu/conducere/capital și conexiuni documentate între societăți. Semnalele ONRC pot alimenta `ECONOMIE`, `UNDE_IEȘIM`, `INVESTIGAȚII` și `ADMINISTRAȚIE`.

Nu se deduc relații politice sau economice doar din coincidențe de nume, adresă sau administrator. Pentru afirmații sensibile se păstrează data verificării și se solicită poziția părților relevante.

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

### 6. Registrul local de profesii, servicii, comunități și personalități

VÂLCEA CLAR menține un index backend de entități locale și persoane cu activitate publică/profesională relevantă. Indexarea este pentru discovery, verificare, relaționarea știrilor și construirea ghidurilor; nu presupune automat publicarea unui profil.

#### Profesii reglementate

Se indexează:
- avocați și societăți de avocatură;
- notari și birouri notariale;
- executori, practicieni în insolvență, mediatori și alte profesii juridice relevante, când informația este publică și utilă editorial.

Surse prioritare: registrele profesionale oficiale, site-urile barourilor/camerelor/uniunilor profesionale, site-urile cabinetelor și portal.just.ro pentru cauze publice relevante.

Nu se publică date private de contact, adrese personale sau informații fără legătură cu activitatea profesională.

#### Fitness, wellness și servicii personale

Se indexează:
- săli de fitness, studiouri și cluburi sportive;
- antrenori personali (PT), instructori și coachi cu activitate publică;
- frizerii/barbershop-uri și frizeri cu activitate profesională publică;
- saloane de manichiură/pedichiură și tehnicieni cu activitate profesională publică;
- servicii beauty/wellness conexe.

Câmpuri: locație, program, servicii, prețuri publice datate, conturi oficiale, recenzii ca semnal, operator juridic când este relevant, acreditări/calificări numai dacă pot fi verificate.

Aceste entități alimentează în principal `UNDE_IEȘIM`, `LIFESTYLE`, `ECONOMIE` și ghidurile locale.

#### Săli de evenimente și hospitality

Se indexează săli de evenimente, ballroom-uri, restaurante pentru evenimente, hoteluri cu spații de conferințe/nunți, centre de conferințe și locații private/publice pentru evenimente.

Câmpuri: capacitate declarată, tipuri de evenimente, operator, facilități, parcare, catering, prețuri/pachete publice, calendare publice și conturi sociale oficiale.

#### Cluburi de business și rețele profesionale

Se indexează camere de comerț, cluburi de business, asociații patronale, networking groups, organizații profesionale și alte rețele economice active în Vâlcea.

Se urmăresc: conducerea publică, membri declarați public, evenimente, sponsori, parteneriate, poziții publice și legături documentate cu proiecte sau achiziții. Apartenența unei persoane se publică numai dacă este declarată oficial/public sau documentată în surse credibile.

#### Personalități politice cu origine sau legături relevante cu Vâlcea

Se menține un registru backend pentru persoane care ocupă sau au ocupat funcții publice naționale și au o legătură documentată cu Vâlcea: origine, domiciliu public relevant, studii, carieră profesională/politică sau circumscripție.

Prioritate: membri ai Guvernului, secretari de stat, parlamentari, conducători de agenții/companii publice și alte funcții naționale cu impact local.

Se monitorizează declarații, decizii, numiri, proiecte și resurse care pot afecta județul. Originea sau legătura cu Vâlcea se publică numai când poate fi documentată; nu se transformă automat într-o relație de influență.

#### Artiști și personalități culturale cu origine sau legături cu Vâlcea

Se indexează artiști, muzicieni, actori, scriitori, regizori, creatori, sportivi și alte personalități culturale cu origine sau legături documentate cu județul.

Semnale: lansări, concerte, expoziții, premii, apariții locale, proiecte, colaborări, festivaluri și declarații despre Vâlcea. Se separă clar `ORIGIN`, `BORN_IN`, `RAISED_IN`, `LIVES_IN`, `WORKS_IN`, `FAMILY_LINK`, `EVENT_LINK` și `HISTORICAL_LINK` pentru a evita formulările vagi.

#### Masonerie și organizații cu apartenență sensibilă

Masoneria și alte organizații de acest tip pot fi indexate numai ca **entități publice/documentabile**: obediențe, loji sau organizații care au site oficial, personalitate juridică, comunicate, evenimente publice sau apar în documente publice.

**Nu se construiesc liste speculative de membri.** Apartenența individuală este considerată informație sensibilă editorial și se publică numai când persoana a declarat-o public ori există documente/surse publice robuste care o confirmă și există interes public legitim. Nu se deduce apartenența din fotografii, relații sociale, participarea la un eveniment, simboluri ambigue, prietenii sau zvonuri.

Orice material care leagă o apartenență masonică de o decizie publică, afacere, licitație sau influență necesită dovezi separate pentru **apartenență**, **relația concretă** și **relevanța publică**. Vinovăția prin asociere este interzisă.

## Niveluri de încredere

- `T1` — document/sursă oficială primară;
- `T1B` — canal oficial al entității;
- `T2` — presă identificabilă și surse secundare reputabile;
- `T3` — agregatoare, directoare, repostări și semnale neverificate.

Orice clasă poate produce un `SIGNAL`; numai dovezile suficiente pot produce un `FACT_KERNEL` publicabil.

## Discovery continuu

Lista surselor este deschisă. Motorul caută periodic publicații, firme, profesioniști, personalități, instituții și organizații noi, domenii mutate, conturi oficiale și feed-uri noi. O sursă dispărută nu se șterge din istoric; se marchează `INACTIVE`, `MOVED` sau `FAILED` și se caută succesorul.

## Rutare editorială

Semnalele sunt clasificate automat în: `BREAKING`, `ORAȘ`, `JUDEȚ`, `ADMINISTRAȚIE`, `ECONOMIE`, `CULTURĂ`, `EVENIMENTE`, `UNDE_IEȘIM`, `LIFESTYLE`, `INVESTIGAȚII`, `JUSTIȚIE`, `SPORT` sau `OTHER`. Un semnal poate alimenta mai multe secțiuni, dar se publică o singură versiune canonică a materialului.
