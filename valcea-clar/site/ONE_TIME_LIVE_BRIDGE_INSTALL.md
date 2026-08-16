# VÂLCEA CLAR — instalare unică pentru redacția live story-first

## Scop

Această operațiune structurală se face o singură dată în editorul Site-ului existent `valceaclar.ro`. După publicare, site-ul citește automat fluxul canonic generat de CIVORA și afișează fiecare story imediat ce intră în feed ca material verificat. Edițiile de dimineață și de seară rămân recapuri, nu ferestre de publicare.

Aceeași instalare trebuie să expună public și documentele juridice canonice la `/termeni/` și `/confidentialitate/`. Aceste două pagini trebuie să existe ca pagini reale, indexabile, cu textul disponibil în HTML-ul inițial; nu este suficientă o pagină goală care se umple numai după JavaScript. Cerința este importantă pentru verificări automate ale platformelor externe, inclusiv TikTok.

Conținutul editorial și juridic rămâne canonic în CIVORA. Bridge-ul public nu inventează, completează sau rescrie fapte ori clauze.

## Prompt unic pentru editorul Site-ului

Folosește acest prompt în chatul/editorul Site-ului VÂLCEA CLAR:

> Actualizează site-ul existent `valceaclar.ro`, fără a crea un site paralel. Păstrează domeniul, brandingul bleumarin/alb/roșu, secțiunile existente și setările curente. Folosește ca implementare de referință `valcea-clar/site/chatgpt-sites-live-bridge.js` din repository-ul `mihaicismaru-bit/civora`.
>
> **Redacția live:** la încărcare și apoi la fiecare 60 de secunde, citește cu cache dezactivat feed-ul canonic `https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json`. Modelul principal este `publication_model=continuous_story_first`; câmpurile de ediție sunt doar compatibilitate și nu trebuie să conducă homepage-ul. Homepage-ul randerează `stories[]` în ordinea feed-ului, cu eticheta `ACTUALIZAT LIVE`. Fiecare titlu duce exact la `story.path`, iar canonicalul este `story.canonical_url`. Folosește numai câmpurile furnizate de feed și nu inventa detalii.
>
> Configurează ruta/catch-all `/stiri/*` astfel încât pagina individuală să fie randată din story-ul corespunzător. Pagina are titlu, dek, corpul din `paragraphs`, surse clickable și `<link rel="canonical">` egal cu `story.canonical_url`. Dacă story-ul nu există, afișează indisponibilitate fără conținut inventat.
>
> **Documente juridice:** creează două pagini publice reale, server-rendered/static, nu doar client-rendered: `/termeni/` și `/confidentialitate/`. Sursa unică este `https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/legal/legal_pages.json`. Copiază exact titlul, introducerea, secțiunile și paragrafele pentru cheia corespunzătoare, fără reformulare. În HTML-ul inițial trebuie să existe întregul text al paginii, `redactie@valceaclar.ro`, `<meta name="robots" content="index,follow">` și canonical exact `https://valceaclar.ro/termeni/`, respectiv `https://valceaclar.ro/confidentialitate/`.
>
> Adaugă în footer-ul tuturor paginilor linkuri vizibile `Termeni` → `/termeni/` și `Confidențialitate` → `/confidentialitate/`. Nu pune `noindex`, autentificare, redirect spre homepage sau blocare de crawler pe cele două rute juridice.
>
> Dacă feed-ul de știri nu poate fi citit, păstrează ultima versiune bună deja randată. Nu face fallback la o ediție veche ca sursă editorială principală. Documentele juridice publicate rămân disponibile independent de feed-ul de știri.
>
> Nu folosi imagini generate automat pentru persoane, evenimente sau locuri reale. Nu introduce chei API, parole ori tokenuri în client. Bridge-ul nu are voie să apeleze OpenAI sau alt API LLM.
>
> În preview verifică obligatoriu: (1) homepage-ul este `continuous_story_first`; (2) un `story.id` apare și deschide exact `story.path`; (3) pagina story folosește canonicalul exact; (4) `Unde ieșim` funcționează; (5) `/termeni/` afișează în HTML-ul inițial titlul `Termeni și condiții` și textul complet; (6) `/confidentialitate/` afișează în HTML-ul inițial titlul `Politica de confidențialitate` și textul complet; (7) ambele rute juridice au HTTP 200, canonical propriu și `index,follow`; (8) footer-ul leagă ambele pagini; (9) layoutul mobil nu are overflow. Nu publica modificarea structurală până când toate verificările trec.

## Criterii de acceptare înainte de Publish

- homepage-ul afișează `stories[]`, nu lead-ul unei ediții;
- eticheta vizibilă este **ACTUALIZAT LIVE**;
- fiecare material are URL propriu `/stiri/<story-id>/` și canonical corect;
- `https://valceaclar.ro/termeni/` răspunde HTTP 200 și conține textul complet în HTML-ul inițial;
- `https://valceaclar.ro/confidentialitate/` răspunde HTTP 200 și conține textul complet în HTML-ul inițial;
- ambele pagini juridice sunt `index,follow`, fără autentificare sau redirect;
- footer-ul site-ului conține linkurile Termeni și Confidențialitate;
- `Unde ieșim` rămâne funcțional;
- mobilul nu are overflow orizontal;
- nu există chei API, parole sau tokenuri în codul client;
- nu există dependență de API LLM plătit.

## Surse tehnice canonice

- bridge story-first + fallback legal: `valcea-clar/site/chatgpt-sites-live-bridge.js`
- feed canonic: `valcea-clar/site/runtime/live-feed.json`
- date juridice canonice: `valcea-clar/site/legal/legal_pages.json`
- HTML juridic de referință: `valcea-clar/site/runtime/termeni/index.html` și `valcea-clar/site/runtime/confidentialitate/index.html`
- manifest stories: `valcea-clar/site/runtime/stiri/manifest.json`
- workflow newsroom: `.github/workflows/valcea-clar-newsroom-live.yml`
- workflow juridic: `.github/workflows/valcea-clar-legal-pages.yml`

## După instalarea structurală

Nu mai este necesar un Publish manual pentru fiecare știre. CIVORA actualizează feed-ul și evenimentul de story, iar site-ul îl preia automat. Documentele juridice rămân rute publice stabile; la o modificare juridică intenționată, sursa canonică este `legal_pages.json`, iar publicarea site-ului trebuie să păstreze exact aceleași rute și canonicals.
