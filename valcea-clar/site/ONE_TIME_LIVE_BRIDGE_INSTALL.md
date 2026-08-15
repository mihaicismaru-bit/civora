# VÂLCEA CLAR — instalare unică pentru frontpage autonom

## Scop

Această operațiune se face o singură dată în editorul Site-ului existent `valceaclar.ro`. După publicarea bridge-ului, frontpage-ul citește automat ediția curentă din feed-ul public generat de GitHub Actions și verifică o versiune nouă la fiecare 5 minute. Edițiile de dimineață și de seară nu mai necesită republish zilnic.

## Prompt unic pentru editorul Site-ului

Folosește acest prompt în chatul/editorul Site-ului Vâlcea Clar:

> Transformă homepage-ul existent Vâlcea Clar într-un frontpage live care se actualizează din feed-ul editorial canonic. Păstrează domeniul, brandingul bleumarin/alb/roșu și toate setările existente ale Site-ului. Nu crea un site paralel. La încărcarea paginii și apoi la fiecare 5 minute, citește JSON-ul public de la `https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json`, cu cache dezactivat. Randarea trebuie să folosească exclusiv câmpurile din feed: lead-ul ediției, știrile secundare, sursele și modulul „Unde ieșim”. Nu inventa, completa sau rescrie fapte. Dacă feed-ul nu poate fi citit, păstrează ultima ediție încărcată și afișează discret că actualizarea live este temporar indisponibilă. Edițiile `auto_hold` nu trebuie să înlocuiască ultima ediție publicabilă. Layout responsive mobil/desktop, stil newsroom premium, fără imagini generate automat. Folosește implementarea de referință din `valcea-clar/site/chatgpt-sites-live-bridge.js` din repository-ul GitHub `mihaicismaru-bit/civora`. În preview verifică obligatoriu că `edition.edition_id` din feed apare în frontpage și că linkul „Unde ieșim” funcționează. Nu publica până când aceste două verificări trec.

## Criterii de acceptare înainte de Publish

- homepage-ul arată ediția indicată de `site/runtime/live-feed.json`;
- lead-ul și ordinea știrilor sunt cele din feed, fără completări AI;
- sursele sunt vizibile și clickable;
- „Unde ieșim” este vizibil și duce la secțiunea existentă;
- mobilul nu are overflow orizontal;
- la o eroare de fetch rămâne ultima ediție bună;
- nu există nicio cheie API, parolă sau token în codul client;
- frontpage-ul nu depinde de OpenAI API sau alt API LLM plătit;
- după această instalare, edițiile sunt actualizate de workflow-ul `VÂLCEA CLAR Autonomous Editions` la 07:45 și 18:30 Europe/Bucharest.

## Sursa tehnică

- bridge: `valcea-clar/site/chatgpt-sites-live-bridge.js`
- feed: `valcea-clar/site/runtime/live-feed.json`
- frontpage static fallback: `valcea-clar/site/runtime/index.html`
- pointer public: `valcea-clar/site/current_edition.json`
- workflow: `.github/workflows/valcea-clar-editions.yml`

Acest pas este deliberat unic: Site-ul public trebuie revizuit și publicat o dată după schimbarea codului structural; schimbările ulterioare de conținut vin din feed și nu cer o nouă intervenție editorială în Site.
