# VÂLCEA CLAR — instalare unică pentru redacția live story-first

## Scop

Această operațiune structurală se face o singură dată în editorul Site-ului existent `valceaclar.ro`. După publicarea bridge-ului, site-ul citește automat fluxul canonic generat de CIVORA și **publică/afișează fiecare story imediat ce acesta intră în feed ca material verificat**. Edițiile de dimineață și de seară rămân recapuri și nu sunt ferestre de publicare.

Conținutul editorial continuă să fie produs și validat exclusiv de site engine; bridge-ul public nu inventează, completează sau rescrie fapte.

## Prompt unic pentru editorul Site-ului

Folosește acest prompt în chatul/editorul Site-ului VÂLCEA CLAR:

> Migrează site-ul existent `valceaclar.ro` la modelul de redacție live **continuous_story_first**, păstrând domeniul, brandingul bleumarin/alb/roșu, secțiunile existente și toate setările curente. Nu crea un site paralel. Folosește implementarea de referință din `valcea-clar/site/chatgpt-sites-live-bridge.js` din repository-ul `mihaicismaru-bit/civora`.
>
> La încărcare și apoi la fiecare 60 de secunde, citește cu cache dezactivat feed-ul canonic `https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json`. Modelul principal al feed-ului este `publication_model=continuous_story_first`; câmpurile `edition` și `pointer` sunt doar compatibilitate și nu trebuie să conducă homepage-ul.
>
> Homepage-ul trebuie să randereze `stories[]`, ordonate exact cum sunt livrate de feed, cu eticheta `ACTUALIZAT LIVE`. Fiecare titlu trebuie să ducă la `story.path`, iar URL-ul canonic este `story.canonical_url`. Pentru fiecare material folosește doar `headline`, `dek`, `paragraphs`, `section`, `sources` și eventual `visual` furnizate de feed. Nu inventa și nu completa detalii.
>
> Configurează și ruta/catch-all `/stiri/*` astfel încât aceeași componentă live să poată randera pagina individuală corespunzătoare după `story.path`. Pagina individuală trebuie să aibă titlu, dek, corpul din `paragraphs`, sursele clickable și `<link rel="canonical">` setat la `story.canonical_url`. Dacă un story nu există în feed, afișează un mesaj de indisponibilitate și link spre homepage, fără a inventa conținut.
>
> Dacă feed-ul nu poate fi citit, păstrează ultima versiune bună deja randată și afișează discret că actualizarea live este temporar indisponibilă. Nu șterge conținutul bun și nu face fallback la o ediție veche ca sursă editorială principală.
>
> Nu folosi imagini generate automat pentru persoane, evenimente sau locuri reale. Nu introduce chei API, parole ori tokenuri în client. Bridge-ul nu are voie să apeleze OpenAI sau alt API LLM.
>
> În preview verifică obligatoriu: (1) `publication_model` este `continuous_story_first`; (2) cel puțin un `story.id` apare pe homepage; (3) click pe titlu deschide exact `story.path`; (4) pagina individuală folosește exact `story.canonical_url`; (5) `Unde ieșim` funcționează; (6) layoutul mobil nu are overflow. Nu publica modificarea structurală până când toate verificările trec.

## Criterii de acceptare înainte de Publish

- homepage-ul afișează `stories[]`, nu lead-ul unei ediții;
- eticheta vizibilă este **ACTUALIZAT LIVE**, nu „Ediția de dimineață/seară”;
- fiecare material are URL propriu `/stiri/<story-id>/` și canonical corect;
- corpul articolului și sursele provin exclusiv din feed;
- un story nou apare fără a aștepta ora unei ediții;
- `Unde ieșim` rămâne funcțional;
- mobilul nu are overflow orizontal;
- la eroare de fetch rămâne ultima versiune bună;
- nu există nicio cheie API, parolă sau token în codul client;
- nu există dependență de API LLM plătit;
- recapurile dimineață/seară nu pot autoriza, bloca sau întârzia un story.

## Sursa tehnică

- bridge story-first: `valcea-clar/site/chatgpt-sites-live-bridge.js`
- feed canonic: `valcea-clar/site/runtime/live-feed.json`
- manifest stories: `valcea-clar/site/runtime/stiri/manifest.json`
- pagini statice fallback: `valcea-clar/site/runtime/stiri/*/index.html`
- workflow newsroom: `.github/workflows/valcea-clar-newsroom-live.yml`
- eveniment social: `valcea-clar/site/story_publication_event.json`

## După instalarea structurală

Nu mai este necesar un Publish manual pentru fiecare știre. CIVORA actualizează feed-ul și evenimentul de story; site-ul îl preia automat, iar Social Publication Engine distribuie același story independent pe canalele pentru care există adaptor, credențiale și media aprobate.
