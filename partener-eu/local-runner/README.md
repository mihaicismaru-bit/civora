# PARTENER.EU — MIPE Romania Runner

Scop: calculatorul din România oferă doar accesul de rețea/browser către `mfe.gov.ro`. Crawl-ul, verificarea, persistența și programarea sunt conduse de GitHub/PARTENER.EU.

## Instalare — o singură dată

1. În GitHub deschide repository-ul `mihaicismaru-bit/civora` → **Settings → Actions → Runners → New self-hosted runner → Windows → x64**.
2. Din comanda `config.cmd ... --token XXXXX` copiază numai valoarea `XXXXX`. Tokenul este temporar și expiră după aproximativ o oră.
3. Descarcă `INSTALL-MIPE-RUNNER.cmd` și deschide-l. Windows va cere drepturi Administrator, apoi scriptul îți cere tokenul. Atât.

Installerul:
- descarcă automat cea mai nouă versiune GitHub Actions Runner pentru Windows x64;
- instalează în `C:\actions-runner-partener-mipe`;
- înregistrează runnerul pentru repository;
- aplică eticheta `mipe-ro`;
- îl configurează ca serviciu Windows cu pornire automată;
- nu salvează tokenul GitHub în repository.

## După instalare

Nu mai pornești nimic manual. Workflow-ul `PARTENER.EU MIPE Romania Scheduler` cere automat un crawl la fiecare 3 ore. Colectorul rulează numai când calculatorul este pornit și conectat la internet. Dacă este oprit, rularea poate aștepta până când runnerul revine online.

Crawlerul folosește browser real Microsoft Edge când este disponibil, extrage numai URL-uri oficiale `mfe.gov.ro`, păstrează proveniența și aplică fail-closed/last-known-good dacă MIPE nu poate fi accesat.

## Verificare rapidă

În GitHub → **Settings → Actions → Runners**, runnerul `PARTENER-MIPE-<NUME-PC>` trebuie să apară `Idle` sau `Active`.

În Actions, workflow-ul **PARTENER.EU MIPE Romania Collector** trebuie să treacă din `Queued` în `In progress` atunci când PC-ul este online.

## Siguranță

- Nu pune parole, PAT-uri sau registration token-uri în fișierele repository-ului.
- Registration token-ul este folosit numai la configurarea inițială.
- Runnerul este repository-scoped, nu un runner public.
- Publicarea rămâne fail-closed: accesul la o pagină nu este suficient pentru promovarea automată a unui fapt material.
