# Contract de integrare — valceaclar.ro / ChatGPT Sites

## Roluri

- `valceaclar.ro` rămâne produsul editorial public.
- ChatGPT Sites rămâne stratul de prezentare și publicare al site-ului existent.
- `civora/valcea-clar` este sursa tehnică unică pentru date, validare, monitorizare și export.
- PARTENER.EU rămâne izolat; niciun workflow VÂLCEA CLAR nu modifică directoarele sau deploymentul său.

## Pachetul de sincronizare

`python valcea-clar/scripts/build_sites_export.py` creează `valcea-clar/dist/chatgpt-sites/` cu:

- pagina secțiunii și activele sale;
- proiecția publică a localurilor și creatorilor;
- metadatele de rutare și hash-urile fișierelor;
- materialele editoriale asociate;
- un raport de conținut care separă fișele publice de candidații ascunși.

Exportul nu conține candidați neverificați și nu poate reintroduce prețuri expirate. El este un payload de sincronizare; publicarea efectivă cere acces la editorul site-ului existent.

## Rute canonice

- `/unde-iesim/` — landing și director;
- `/unde-iesim/local/<slug>/` — fișa permanentă a localului;
- `/unde-iesim/nou-deschis/<slug>/` — material editorial despre deschidere;
- `/unde-iesim/metodologie/` — transparență, corecții și politică comercială.

Sincronizarea trebuie să actualizeze după slug, nu să creeze duplicate. URL-urile deja indexate nu se șterg; schimbările de nume folosesc redirect permanent și păstrează cronologia.

## Quality gates înainte de publicare

1. `validate_data.py` trece;
2. `build_public_data.py` nu produce diff necomis;
3. `smoke_web.py` trece;
4. JavaScript are sintaxă validă;
5. exportul are manifest și hash pentru fiecare fișier;
6. numărul fișelor publice din manifest este identic cu proiecția publică;
7. candidații și creatorii nevalidați au număr public zero;
8. orice schimbare semantică a unei surse materiale are task de reverificare.

## Regula de deployment

Publicarea pe `valceaclar.ro` este permisă numai în site-ul existent din ChatGPT Sites. Nu se creează un site paralel, nu se mută domeniul și nu se schimbă DNS-ul pentru această verticală.
