# Contract de prezentare — valceaclar.ro / ChatGPT Sites

## Statut

Acest document descrie numai o punte de prezentare pentru site-ul existent. Nu acordă ChatGPT Sites sau unei conversații ChatGPT niciun rol de scheduler, monitor, generator editorial, depozit de stare ori runtime de producție.

## Roluri canonice

- `valceaclar.ro` este produsul editorial public.
- `civora/valcea-clar` este sursa tehnică unică pentru date, programare, ingestie, monitorizare, validare, generare, stare și distribuție.
- GitHub Actions este schedulerul și runtime-ul server-side al engine-ului CIVORA.
- `site/runtime/` și feedurile generate în repository sunt sursele publice actualizabile independent de o conversație.
- ChatGPT Sites poate rămâne temporar strat de prezentare sau bridge pentru site-ul existent, dar nu este o dependență critică a engine-ului.
- ChatGPT este doar consolă de administrare și dezvoltare la cerere.
- PARTENER.EU rămâne izolat; niciun workflow VÂLCEA CLAR nu modifică directoarele sau deploymentul său.

## Interdicție de execuție în ChatGPT

Pentru CIVORA și VÂLCEA CLAR sunt interzise:

1. taskuri sau monitoare recurente create într-o conversație ChatGPT;
2. generarea edițiilor prin reluarea periodică a unei conversații;
3. păstrarea checkpointurilor sau a stării editoriale exclusiv în contextul ChatGPT;
4. cron-uri pe calculatorul utilizatorului sau runner-e GitHub `self-hosted`;
5. chei ori apeluri către API-uri LLM în fluxurile de monitorizare și creare de conținut;
6. orice proces care se oprește când conversația este închisă.

Registrul machine-readable este `valcea-clar/engine/automation_registry.json`. `validate_site_engine_ownership.py` și workflow-ul `valcea-clar-engine-guard.yml` blochează modificările care încalcă regula.

Monitorul extern `VC-INV-2026-001` este retras; înlocuitorul canonic este `.github/workflows/valcea-clar-olanesti-investigation-monitor.yml`. Toate celelalte monitoare recurente VÂLCEA CLAR din ChatGPT sunt considerate retrase și nu trebuie reactivate.

## Pachetul de prezentare

`python valcea-clar/scripts/build_sites_export.py` creează `valcea-clar/dist/chatgpt-sites/` cu:

- pagina secțiunii și activele sale;
- proiecția publică a localurilor și creatorilor;
- metadatele de rutare și hash-urile fișierelor;
- materialele editoriale asociate;
- un raport de conținut care separă fișele publice de candidații ascunși.

Acest director este un payload determinist de prezentare. Nu face ingestie, nu monitorizează surse, nu generează fapte, nu programează ediții și nu deține starea canonică. Poate fi înlocuit de alt strat de hosting fără a schimba engine-ul editorial.

## Rute canonice

- `/` — frontpage și ediția curentă;
- `/unde-iesim/` — landing și director;
- `/unde-iesim/local/<slug>/` — fișa permanentă a localului;
- `/unde-iesim/nou-deschis/<slug>/` — material editorial despre deschidere;
- `/unde-iesim/metodologie/` — transparență, corecții și politică comercială.

Sincronizarea actualizează după slug, nu creează duplicate. URL-urile deja indexate nu se șterg; schimbările de nume folosesc redirect permanent și păstrează cronologia.

## Quality gates înainte de publicare

1. ownership guard confirmă `execution_owner=civora_site_engine`;
2. toate joburile sunt în registru și folosesc runner GitHub-hosted;
3. `validate_data.py` trece;
4. `build_public_data.py` nu produce diff necomis;
5. `smoke_web.py` trece;
6. JavaScript are sintaxă validă;
7. exportul are manifest și hash pentru fiecare fișier;
8. numărul fișelor publice din manifest este identic cu proiecția publică;
9. candidații și creatorii nevalidați au număr public zero;
10. orice schimbare semantică a unei surse materiale are task de reverificare.

## Regula de deployment

Engine-ul produce și persistă conținutul fără ChatGPT. Puntea ChatGPT Sites poate afișa payloadul sau feedul public, dar indisponibilitatea ei nu trebuie să oprească ingestia, edițiile, monitorizarea, distribuția sau istoricul. Această schimbare nu mută domeniul și nu modifică DNS-ul; separă strict prezentarea de execuția editorială.
