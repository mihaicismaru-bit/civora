# VÂLCEA CLAR — External Cost & API Policy

Status: `CANONICAL_BASELINE`

## Principiu

VÂLCEA CLAR trebuie să funcționeze implicit **fără API-uri plătite și fără servicii externe care generează costuri recurente sau variabile**.

Regula de bază este:

`NO_EXTERNAL_PAID_SERVICES_BY_DEFAULT`

API-urile se folosesc numai când sunt absolut necesare, există o justificare tehnică clară și nu există o alternativă gratuită/locală suficientă. Orice integrare care poate genera cost extern trebuie tratată ca excepție explicită, nu ca dependență implicită.

## Ordinea de preferință

1. surse publice gratuite, HTML/RSS/sitemap/documente;
2. date oficiale descărcabile gratuit;
3. crawling propriu, cu respectarea robots.txt și a limitelor rezonabile;
4. baze și fișiere locale persistente;
5. biblioteci open-source și procesare locală;
6. integrare prin servicii/API gratuite deja disponibile;
7. API extern doar dacă este realmente indispensabil;
8. serviciu plătit extern — interzis implicit.

## Geospatial / Maps

Pentru hărți și geolocalizare, implementarea implicită NU depinde de Google Maps Platform cu billing.

Preferințe:
- OpenStreetMap pentru hartă și geocodare, în limitele politicilor serviciilor utilizate;
- geocodare din surse oficiale / adrese documentate;
- coordonate salvate local după verificare;
- hărți statice generate local din date open-source;
- linkuri către Google Maps/Street View doar ca destinație externă pentru utilizator/editor, fără consum API plătit;
- Street View poate fi folosit manual ca sursă de context/verificare, cu respectarea termenilor platformei, dar nu devine o dependență de backend.

## Visual Factory

Visual Factory trebuie să poată funcționa complet fără servicii grafice plătite externe. Priorități:
- fotografii proprii;
- imagini cu drepturi clare;
- asset-uri furnizate de entități pentru publicare;
- hărți și grafice generate local;
- compoziție și randare locală/open-source;
- generare AI disponibilă în mediul curent numai când este editorial permisă și fără crearea unei dependențe comerciale externe.

## Source Intelligence

Crawlerul și Source Intelligence trebuie să prefere:
- RSS/Atom;
- sitemap-uri;
- HTML;
- JSON-LD;
- documente PDF/DOCX/XLSX;
- registre publice;
- portaluri oficiale gratuite;
- cache și last-known-good local.

Nicio sursă importantă nu trebuie exclusă doar fiindcă nu oferă API.

## Excepții

O excepție de API poate fi propusă numai dacă:
1. alternativa gratuită nu poate furniza funcția necesară;
2. lipsa funcției produce un blocaj real, nu doar comoditate;
3. costul este cunoscut și controlabil;
4. există fallback fără serviciul extern;
5. utilizatorul aprobă explicit costul înainte de activare.

În lipsa aprobării explicite, costul extern autorizat este **0 EUR**.

## Acceptance invariant

Orice modul nou trebuie să treacă testul:

> Poate funcționa în producție cu cost extern variabil = 0 EUR?

Dacă răspunsul este nu, arhitectura trebuie revizuită înainte de acceptare.
