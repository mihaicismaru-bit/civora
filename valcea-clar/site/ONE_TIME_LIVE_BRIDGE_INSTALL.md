# VÂLCEA CLAR — instalare / reparație structurală pentru site-ul live story-first

## Scop

Această operațiune structurală se face în editorul site-ului existent `valceaclar.ro`. Nu se creează un site paralel și nu se schimbă domeniul. După publicare, site-ul citește automat fluxul canonic generat de CIVORA și afișează fiecare story imediat ce intră în feed ca material verificat. Edițiile de dimineață și de seară rămân recapuri, nu ferestre de publicare.

Aceeași instalare trebuie să păstreze paginile juridice reale `https://valceaclar.ro/termeni/` și `https://valceaclar.ro/confidentialitate/`, să materializeze corect indexurile editoriale `/stiri/` și `/despre/` și să publice directorul `/artisti/` plus rutele individuale `/artisti/<slug>/`. Rutele juridice trebuie să rămână server-rendered/static, cu textul integral în HTML-ul inițial. `/stiri/`, `/despre/` și `/artisti/` trebuie să aibă HTTP 200, canonical propriu și conținut coerent cu runtime-ul CIVORA; bridge-ul client-side este fallback/reîmprospătare, nu motiv pentru a lăsa aceste rute ca shell generic.

Conținutul editorial și juridic rămâne canonic în CIVORA. Bridge-ul public nu inventează, completează sau rescrie fapte ori clauze.

## Implementare canonică

Folosește împreună:

- `valcea-clar/site/chatgpt-sites-live-bridge.js` — homepage, story individual, Artist Intelligence, legal și `Unde ieșim`;
- `valcea-clar/site/chatgpt-sites-route-bridge.js` — fallback/reîmprospătare pentru `/stiri/` și `/despre/`;
- `valcea-clar/site/runtime/stiri/index.html` — HTML de referință pentru indexul de știri;
- `valcea-clar/site/runtime/despre/index.html` — HTML de referință pentru pagina Despre;
- `valcea-clar/site/runtime/artisti/index.html` și `valcea-clar/site/runtime/artisti/*/index.html` — directorul și profilurile publice;
- `valcea-clar/site/runtime/artists.json` — registrul public Artist Intelligence;
- `valcea-clar/site/runtime/live-feed.json` — feed editorial canonic;
- `valcea-clar/site/legal/legal_pages.json` — text juridic canonic.

## Prompt unic pentru editorul Site-ului

Folosește acest prompt în chatul/editorul Site-ului VÂLCEA CLAR:

> Actualizează site-ul EXISTENT `valceaclar.ro`; nu crea alt site, nu schimba domeniul și nu muta execuția editorială în Sites. Păstrează brandingul, paginile valide și setările curente.
>
> Folosește ca implementare de referință fișierele din `mihaicismaru-bit/civora`: `valcea-clar/site/chatgpt-sites-live-bridge.js`, `valcea-clar/site/chatgpt-sites-route-bridge.js`, `valcea-clar/site/runtime/stiri/index.html`, `valcea-clar/site/runtime/despre/index.html`, `valcea-clar/site/runtime/artisti/`, `valcea-clar/site/runtime/artists.json` și `valcea-clar/site/legal/legal_pages.json`.
>
> **Homepage + stories:** la încărcare și apoi la fiecare 60 de secunde, citește fără cache `https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json`. Modelul principal este `publication_model=continuous_story_first`. Homepage-ul randerează `stories[]`, separă explicit `active_now=true` de arhivă și nu prezintă un story arhivat drept „activ acum”. Fiecare titlu duce exact la `story.path`, iar pagina individuală folosește canonicalul `story.canonical_url`. Folosește numai câmpurile furnizate de feed și nu inventa detalii.
>
> **Artist Intelligence în fiecare story:** dacă `story.artist_profiles[]` există și nu este gol, interfața trebuie să proiecteze vizibil aceste date. În corpul articolului, fiecare apariție textuală exactă a unui artist/actor/regizor/dirijor/creator din `artist_profiles[]` devine link intern către `item.path` (`/artisti/<slug>/`). Sub corpul articolului afișează obligatoriu secțiunea `Artiști și creatori din acest material`, cu toate profilele din `artist_profiles[]`. Nu genera linkuri către persoane care nu există în `artist_profiles[]`. Dacă `external_identity_verified=false`, profilul intern rămâne accesibil, dar nu inventa sau atașa conturi sociale externe. Fingerprint-ul de refresh trebuie să includă și `artist_profiles`, astfel încât o modificare doar a acestor profile să rerandeze pagina fără reload manual.
>
> **Director și profile artiști:** publică ruta reală `/artisti/` și toate rutele declarate în `valcea-clar/site/indexing_routes.json` de forma `/artisti/<slug>/`, folosind HTML-ul canonic din `site/runtime/artisti/`. Fiecare profil trebuie să aibă canonical propriu, `index,follow`, bio-ul disponibil, aparițiile culturale documentate și linkuri inverse spre articolele relevante. Nu înlocui aceste rute cu un shell generic și nu crea profile care nu există în runtime.
>
> **Indexul `/stiri/`:** păstrează/creează ruta publică reală `/stiri/`, HTTP 200, cu canonical exact `https://valceaclar.ro/stiri/`. În HTML-ul inițial trebuie să existe titlul `Știrile Vâlcii, puse în ordine.` și contractul de navigație `valcea-clar-primary-v2`. Lista trebuie să distingă materialele curente de arhivă; monitoarele interne, investigațiile incomplete și publication holds nu devin articole. Instalează și logica din `chatgpt-sites-route-bridge.js` ca refresh/fallback client-side pentru această rută.
>
> **Pagina `/despre/`:** păstrează/creează ruta publică reală `/despre/`, HTTP 200, canonical exact `https://valceaclar.ro/despre/`, cu titlul `Clar înainte de rapid.`. Pagina trebuie să explice pe scurt principiile deja canonice: verificare înainte de publicare, arhivă distinctă de actualitate și surse verificabile. Instalează și logica din `chatgpt-sites-route-bridge.js` ca fallback client-side.
>
> **Story routes:** configurează/păstrează catch-all `/stiri/*` astfel încât pagina individuală să fie randată din story-ul corespunzător. Dacă story-ul nu există în fluxul autorizat, afișează indisponibilitate fără conținut inventat.
>
> **Documente juridice:** `https://valceaclar.ro/termeni/` și `https://valceaclar.ro/confidentialitate/` rămân pagini publice reale, server-rendered/static. Sursa unică este `legal_pages.json`. În HTML-ul inițial trebuie să existe textul integral, `redactie@valceaclar.ro`, `<meta name="robots" content="index,follow">` și canonicalul exact al fiecărei rute. Nu folosi doar JavaScript pentru conținutul juridic.
>
> Footer-ul tuturor paginilor trebuie să includă linkuri vizibile către `Termeni`, `Confidențialitate` și `Despre`. `Unde ieșim` trebuie să rămână funcțional.
>
> Dacă feed-ul nu poate fi citit, păstrează ultima versiune bună deja randată. Nu reveni la o ediție veche ca sursă editorială principală. Nu folosi imagini generate automat pentru persoane, evenimente sau locuri reale. Nu introduce chei API, parole ori tokenuri în client și nu apela API-uri LLM din bridge.
>
> În preview verifică obligatoriu înainte de Publish: (1) homepage-ul este story-first și diferențiază actualitatea de arhivă; (2) `/stiri/` are HTTP 200, canonical propriu, titlul `Știrile Vâlcii, puse în ordine.` și navigația v2; (3) `/despre/` are HTTP 200, canonical propriu și titlul `Clar înainte de rapid.`; (4) un `story.id` deschide exact `story.path` și canonicalul corect; (5) pentru un story care are `artist_profiles`, cel puțin un nume din corp este clicabil către `/artisti/<slug>/`, iar secțiunea `Artiști și creatori din acest material` este vizibilă; (6) `/artisti/` și cel puțin două profile individuale se deschid cu HTTP 200 și canonical propriu; (7) `https://valceaclar.ro/termeni/` și `https://valceaclar.ro/confidentialitate/` au textul integral în HTML-ul inițial, canonical propriu și `index,follow`; (8) `Unde ieșim` funcționează; (9) layoutul mobil nu are overflow. Nu publica până când toate verificările trec.

## Criterii de acceptare după Publish

- `/` răspunde HTTP 200 și proiectează `continuous_story_first`;
- materialele arhivate nu sunt etichetate drept `ACTIV ACUM`;
- `/stiri/` răspunde HTTP 200, canonical `https://valceaclar.ro/stiri/`, conține `Știrile Vâlcii, puse în ordine.` și navigația `valcea-clar-primary-v2`;
- `/despre/` răspunde HTTP 200, canonical `https://valceaclar.ro/despre/` și conține `Clar înainte de rapid.`;
- fiecare material are URL propriu `/stiri/<story-id>/` și canonical corect;
- dacă un story are `artist_profiles[]`, numele corespunzătoare din corp sunt linkuri către `/artisti/<slug>/` și secțiunea `Artiști și creatori din acest material` este vizibilă;
- `/artisti/` și rutele individuale `/artisti/<slug>/` sunt HTTP 200, indexabile și au canonical corect;
- profilele artiștilor leagă înapoi aparițiile și articolele documentate;
- `https://valceaclar.ro/termeni/` și `https://valceaclar.ro/confidentialitate/` sunt HTTP 200, text integral în HTML-ul inițial, canonical propriu și `index,follow`;
- `Unde ieșim` rămâne funcțional;
- footer-ul conține Termeni, Confidențialitate și Despre;
- mobilul nu are overflow orizontal;
- nu există chei API, parole, tokenuri sau dependență de API LLM plătit în codul client.

## Validare automată

După Publish, `.github/workflows/valcea-clar-public-health.yml` trebuie să treacă strict pe `main`. Probe-ul verifică inclusiv `/stiri/`, `/despre/` și, pentru story-urile care au `artist_profiles`, existența proiecției publice `/artisti/`; un HTTP 200 generic nu este suficient dacă lipsesc markerii/canonicalul rutei.

## După instalarea structurală

Nu este necesar Publish manual pentru fiecare știre. CIVORA actualizează feed-ul și evenimentul de story, iar site-ul îl preia automat. O republicare structurală este necesară numai când se schimbă bridge-ul, structura rutelor sau paginile statice ale providerului. Modificarea Artist Intelligence din august 2026 schimbă bridge-ul și adaugă rutele `/artisti/*`, deci necesită această republicare structurală o singură dată; ulterior profilele și legăturile alimentate din feed se actualizează automat.