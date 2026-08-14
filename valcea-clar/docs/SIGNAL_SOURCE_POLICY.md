# VÂLCEA CLAR — Politica surselor de semnale

## Principiu

Radarul editorial trebuie să aibă acoperire largă. O sursă de semnal nu este automat o sursă suficientă pentru publicare. Semnalul intră în coada de verificare, iar faptele publicabile sunt confirmate separat, preferabil din surse primare/oficiale și prin documente.

## Principiul de autoadaptare

**Întregul sistem de surse, crawl, scoring, rutare și discovery este autoadaptabil.** Nu există o listă statică de surse, frecvențe sau ponderi care să rămână neschimbată dacă datele reale arată altceva.

Autoadaptarea funcționează pe cinci niveluri:

1. **Source discovery** — sistemul descoperă automat surse noi din sitemap-uri, RSS, linkuri canonice, documente, entități, social media, ONRC, SICAP, portal.just.ro, pagini oficiale, presă și grafurile de relații dintre entități.
2. **Source scoring** — scorurile se ajustează în funcție de confirmări, infirmări, viteză, exclusivități, duplicate, corecții, zgomot și valoarea editorială reală produsă.
3. **Crawl scheduling** — frecvența de crawl se recalibrează dinamic după volatilitatea sursei, prioritate, oră, zi, sezonalitate, evenimente și rata istorică de schimbare.
4. **Editorial routing** — relevanța pe secțiuni se modifică în timp. O sursă poate deveni importantă pentru `INVESTIGAȚII`, `UNDE_IEȘIM` sau `BREAKING` fără intervenție manuală dacă începe să producă semnale validate în acea zonă.
5. **Entity graph expansion** — fiecare entitate nouă poate genera automat căutări pentru surse, persoane, firme, contracte, dosare, localuri, evenimente și relații documentabile.

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

Se indexează avocați și societăți de avocatură, notari și birouri notariale, executori, practicieni în insolvență, mediatori și alte profesii juridice relevante, când informația este publică și utilă editorial.

Surse prioritare: registrele profesionale oficiale, site-urile barourilor/camerelor/uniunilor profesionale, site-urile cabinetelor și portal.just.ro pentru cauze publice relevante.

#### Fitness, wellness și servicii personale

Se indexează săli de fitness, studiouri și cluburi sportive, antrenori personali, instructori și coachi cu activitate publică, frizerii/barbershop-uri și frizeri, saloane de manichiură/pedichiură și tehnicieni, plus servicii beauty/wellness conexe.

#### Săli de evenimente și hospitality

Se indexează săli de evenimente, ballroom-uri, restaurante pentru evenimente, hoteluri cu spații de conferințe/nunți, centre de conferințe și locații private/publice pentru evenimente.

#### Cluburi de business și rețele profesionale

Se indexează camere de comerț, cluburi de business, asociații patronale, networking groups, organizații profesionale și alte rețele economice active în Vâlcea.

#### Personalități politice cu origine sau legături relevante cu Vâlcea

Se menține un registru backend pentru persoane care ocupă sau au ocupat funcții publice naționale și au o legătură documentată cu Vâlcea: origine, domiciliu public relevant, studii, carieră profesională/politică sau circumscripție.

#### Artiști și personalități culturale cu origine sau legături cu Vâlcea

Se indexează artiști, muzicieni, actori, scriitori, regizori, creatori, sportivi și alte personalități culturale cu origine sau legături documentate cu județul.

#### Masonerie și organizații cu apartenență sensibilă

Masoneria și alte organizații de acest tip pot fi indexate numai ca entități publice/documentabile. Nu se construiesc liste speculative de membri, iar apartenența individuală se publică numai când este declarată public sau confirmată robust și există interes public legitim.

## Niveluri de încredere

- `T1` — document/sursă oficială primară;
- `T1B` — canal oficial al entității;
- `T2` — presă identificabilă și surse secundare reputabile;
- `T3` — agregatoare, directoare, repostări și semnale neverificate.

Orice clasă poate produce un `SIGNAL`; numai dovezile suficiente pot produce un `FACT_KERNEL` publicabil.

## Scorarea obligatorie a surselor

Fiecare sursă primește note 0–100 pentru `importance_score`, `relevance_score`, `authority_score`, `reliability_score`, `freshness_score`, `exclusivity_score` și `signal_value_score`.

Nota agregată implicită este:

`0.22 × importance + 0.20 × relevance + 0.18 × authority + 0.15 × reliability + 0.10 × freshness + 0.08 × signal_value + 0.07 × exclusivity`

Gradele editoriale sunt: `A+` 90–100, `A` 80–89, `B` 65–79, `C` 50–64, `D` 30–49, `E` 0–29.

## Relevanță pe verticală

O sursă primește scoruri distincte 0–100 pentru `breaking`, `administratie`, `politica`, `economie`, `cultura`, `evenimente`, `unde_iesim`, `lifestyle`, `investigatii`, `justitie`, `sport`, `judet` și `oras`.

## Scor de entitate și scor de eveniment

Importanța sursei nu este confundată cu importanța subiectului. Fiecare entitate și fiecare semnal primesc scoruri proprii pentru impact, interes public, caracter local, noutate, exclusivitate, risc și necesitatea verificării.

## Motorul adaptiv de crawl

Fiecare sursă și fiecare rută internă au un profil dinamic:

- `change_frequency` — frecvența observată a schimbărilor reale;
- `signal_yield` — semnale utile / 100 fetch-uri;
- `confirmed_signal_rate` — proporția semnalelor ulterior confirmate;
- `duplicate_rate` — cât conținut duplicat produce;
- `noise_rate` — cât conținut irelevant produce;
- `latency_score` — cât de repede publică informația față de alte surse;
- `failure_rate` — indisponibilitate, erori, blocaje;
- `cost_score` — costul de fetch/render/parsing;
- `section_yield` — randament separat pe fiecare secțiune editorială.

Schedulerul calculează dinamic `next_fetch_at`. Intervalele nu sunt fixe: se scurtează când sursa devine volatilă, produce semnale confirmate sau apare un eveniment relevant și se lungesc când sursa stagnează sau produce zgomot.

Exemple:
- un site ISU care începe să publice intervenții la intervale scurte trece temporar de la 30 minute la 5–10 minute;
- un restaurant fără modificări timp de 60 zile poate trece de la 6 ore la 24–72 ore;
- o pagină de proiect monitorizată într-o investigație activă poate fi accelerată automat la detectarea unui act adițional sau a unei schimbări de document;
- portal.just.ro poate accelera temporar în zilele cu termene asociate dosarelor urmărite.

## Auto-discovery și promovarea surselor

Sursele noi pornesc cu statut `DISCOVERED_UNRATED`. După primele observații primesc un scor provizoriu și pot evolua prin stările:

`DISCOVERED_UNRATED → PROBATION → ACTIVE → STRATEGIC`

sau, dacă sunt slabe:

`PROBATION → LOW_VALUE → DORMANT → INACTIVE`.

O sursă poate reveni automat din `DORMANT` dacă reapare cu activitate relevantă. Nicio sursă nu este eliminată din istoric.

## Recalibrare continuă

Scorurile se recalculază prin ferestre mobile de 7, 30 și 180 zile. Sistemul păstrează atât scorul curent, cât și istoria modificărilor.

Exemple de ajustări:
- semnale confirmate repetat: crește `reliability` și `signal_value`;
- exclusivități confirmate: crește `exclusivity`;
- informații infirmate: scade `reliability`;
- publicare rapidă înaintea altor surse: crește `freshness/latency`;
- duplicate frecvente: scade `signal_value`;
- pagini indisponibile: crește intervalul de crawl și scade `health`, fără ștergerea sursei;
- schimbarea profilului editorial al unei surse: se modifică automat `vertical_relevance`.

Recalibrarea este limitată de guardrails: o sursă T3 nu devine T1 prin popularitate, iar o sursă oficială nu devine automat suficientă pentru orice afirmație.

## Learning loop editorial

După fiecare material, sistemul înregistrează:
- ce sursă a produs primul semnal;
- ce surse au confirmat;
- ce surse au contrazis;
- timpul până la confirmare;
- dacă semnalul a devenit știre, investigație, update sau a fost respins;
- importanța finală a materialului;
- corecții ulterioare.

Aceste rezultate realimentează scoringul, frecvența de crawl, descoperirea de surse și rutarea editorială.

## Detectarea schimbării de regim

Motorul urmărește `concept_drift`: o publicație își schimbă frecvența, un site devine inactiv, un restaurant începe să publice zilnic, o instituție mută comunicatele pe alt domeniu, un politician își schimbă platforma principală sau un nou canal social devine sursa dominantă.

La detectarea unei schimbări de regim, sistemul creează automat o reevaluare a sursei și își adaptează frontier-ul de crawl.

## Discovery continuu

Lista surselor este permanent deschisă. Motorul caută periodic publicații, firme, profesioniști, personalități, instituții și organizații noi, domenii mutate, conturi oficiale și feed-uri noi. O sursă dispărută se marchează `INACTIVE`, `MOVED` sau `FAILED`, iar sistemul caută automat succesorul.

## Rutare editorială

Semnalele sunt clasificate automat în `BREAKING`, `ORAȘ`, `JUDEȚ`, `ADMINISTRAȚIE`, `ECONOMIE`, `CULTURĂ`, `EVENIMENTE`, `UNDE_IEȘIM`, `LIFESTYLE`, `INVESTIGAȚII`, `JUSTIȚIE`, `SPORT` sau `OTHER`. Un semnal poate alimenta mai multe secțiuni, dar se publică o singură versiune canonică a materialului.

## Fail-closed

Autoadaptarea poate modifica scoruri, frecvențe, priorități și cozi de verificare, dar **nu poate relaxa singură regulile de publicare**. Pentru proprietate, justiție, politică, apartenențe sensibile, acuzații, investigații și date personale rămân obligatorii pragurile editoriale și verificarea umană/documentară.
