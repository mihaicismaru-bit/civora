# Contract de prezentare — valceaclar.ro / ChatGPT Sites

## Statut

Acest document descrie numai o punte de prezentare pentru site-ul existent. Nu acordă ChatGPT Sites sau unei conversații ChatGPT niciun rol de scheduler, monitor, generator editorial, depozit de stare ori runtime de producție.

## Roluri canonice

- `valceaclar.ro` este produsul editorial public.
- `civora/valcea-clar` este sursa tehnică unică pentru date, programare, ingestie, monitorizare, validare, generare, stare și distribuție.
- GitHub Actions este schedulerul și runtime-ul server-side al engine-ului CIVORA.
- `valcea-clar/site/runtime/` este **singura proiecție canonică reader-facing** pentru homepage, articole, rubrici, Local Life, RSS/feed, sitemap, robots și metadata.
- `overlay_runtime_export.py` este owner-ul canonic al finalizării prezentării reader-facing.
- ChatGPT Sites poate rămâne temporar strat de prezentare sau bridge pentru site-ul existent, dar nu este o dependență critică a engine-ului.
- ChatGPT este doar consolă de administrare și dezvoltare la cerere.
- PARTENER.EU rămâne izolat; niciun workflow VÂLCEA CLAR nu modifică directoarele sau deploymentul său.

## Arhitectură activă — runtime only

Începând cu 27 august 2026, vechiul export static `valcea-clar/dist/chatgpt-sites/` și scriptul `build_sites_export.py` sunt **retrase intenționat**. Nu trebuie recreate și nu trebuie folosite ca strat paralel de adevăr.

Commitul de retragere a mutat acceptanța de la „canonical export” la **canonical runtime** și a eliminat din workflow-uri orice dependență de `dist/chatgpt-sites`. Payloadul reader-facing acceptat este `valcea-clar/site/runtime/`, iar artefactele de workflow, când sunt folosite, trebuie să transporte acest runtime canonic.

Consecință operațională: dacă `site/runtime/` este corect și `valceaclar.ro` servește o versiune veche, problema este la **bridge/hosting/currentness**, nu se rezolvă prin reintroducerea unui al doilea export static.

## Interdicție de execuție în ChatGPT

Pentru CIVORA și VÂLCEA CLAR sunt interzise:

1. taskuri sau monitoare recurente create într-o conversație ChatGPT ca înlocuitor al engine-ului;
2. generarea edițiilor prin reluarea periodică a unei conversații;
3. păstrarea checkpointurilor sau a stării editoriale exclusiv în contextul ChatGPT;
4. cron-uri pe calculatorul utilizatorului sau runner-e GitHub `self-hosted`;
5. chei ori apeluri către API-uri LLM în fluxurile de monitorizare și creare de conținut;
6. orice proces editorial critic care se oprește când conversația este închisă.

Registrul machine-readable este `valcea-clar/engine/automation_registry.json`. Engine-ul GitHub rămâne autoritatea pentru execuția recurentă.

## Puntea de prezentare

Orice strat extern de prezentare trebuie să consume **direct proiecția canonică `site/runtime/`** sau artefactul de workflow derivat identic din aceasta. Puntea:

- nu face ingestie;
- nu monitorizează surse;
- nu generează fapte;
- nu decide eligibilitatea editorială;
- nu păstrează o copie semantică divergentă;
- nu rescrie titluri, corpuri, imagini, metadata sau stări de corecție;
- nu declară publicare fără readback al URL-ului public.

Sincronizarea trebuie să fie replace/atomic la nivel de runtime sau să respecte hash-uri/ETag echivalente. Un workflow „success” nu este dovadă suficientă că domeniul public servește runtime-ul nou.

## Rute canonice

Rutele sunt materializate în `site/runtime/` și validate prin sitemap/manifest. Printre suprafețele stabile:

- `/` — frontpage;
- `/stiri/` și `/stiri/<slug>/` — index și articole;
- `/unde-iesim/` — Local Life hub;
- `/unde-iesim/sport/`;
- `/unde-iesim/cinema/`;
- `/unde-iesim/restaurante/`;
- `/unde-iesim/meniul-zilei/`;
- `/unde-iesim/fitness/`;
- rubricile, localitățile, edițiile, paginile legale și corecțiile materializate de runtime.

URL-urile deja indexate nu se șterg arbitrar; schimbările de identitate/rutare trebuie să păstreze continuitatea și redirecturile unde este cazul.

## Quality gates înainte de publicare

1. engine-ul produce `site/runtime/` fără dependență de ChatGPT;
2. Fact Kernel / Editorial Writer / Integrity gates trec;
3. publication holds sunt aplicate fail-closed;
4. `overlay_runtime_export.py` finalizează reader presentation;
5. `smoke_web.py` și verificările public UX trec;
6. `live-feed.json`, `stiri/manifest.json`, sitemap și routes sunt coerente;
7. Local Life nu publică rânduri stale/neverificate;
8. deduplicarea story/event/channel trece;
9. după bridge/deploy se face readback HTTP al URL-ului, corpului, imaginii, metadata și linkurilor relevante;
10. numai după readback public pot porni distribuțiile sociale care depind de URL-ul nou.

## Regula de deployment

Engine-ul produce și persistă conținutul în `site/runtime/`. Bridge-ul/hostingul public trebuie să reflecte acel runtime fără un writer secundar. Dacă readback-ul public nu coincide cu runtime-ul, starea corectă este `PUBLIC_READBACK_PENDING` / `DEPLOYMENT_CURRENTNESS_DIVERGENCE`; nu se inventează succes și nu se reintroduce legacy `dist/chatgpt-sites`.
