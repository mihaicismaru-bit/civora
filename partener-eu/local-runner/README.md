# PARTENER.EU — MIPE Romania Runner

Scop: calculatorul din România oferă accesul de rețea/browser către `mfe.gov.ro`; GitHub/PARTENER.EU controlează programarea, crawl-ul, verificarea și persistența.

## Instalare — o singură dată

1. În GitHub deschide `mihaicismaru-bit/civora` → **Settings → Actions → Runners → New self-hosted runner → Windows → x64**.
2. Din comanda `config.cmd ... --token XXXXX` copiază numai valoarea `XXXXX`. Tokenul este temporar.
3. Descarcă `INSTALL-MIPE-RUNNER.cmd` și deschide-l.
4. Acceptă drepturile Administrator și lipește tokenul când este cerut.

Installerul:
- descarcă automat ultima versiune GitHub Actions Runner pentru Windows x64;
- instalează în `C:\actions-runner-partener-mipe`;
- înregistrează runnerul doar pentru repository-ul `mihaicismaru-bit/civora`;
- aplică eticheta `mipe-ro`;
- creează task-ul Windows `PARTENER.EU MIPE Runner`, care pornește automat runnerul la logon și îl repornește dacă procesul se oprește;
- nu salvează tokenul de înregistrare în repository.

Runnerul este pornit în sesiunea Windows autentificată, nu ca serviciu de sistem, astfel încât crawlerul poate folosi Microsoft Edge real dacă este disponibil.

## După instalare

Nu mai pornești manual crawlerul. Workflow-ul **PARTENER.EU MIPE Romania Scheduler** cere automat un crawl la fiecare 3 ore, la minutul 47, în fusul `Europe/Bucharest`.

Colectorul existent rulează fail-closed: păstrează last-known-good când MIPE nu este accesibil și nu promovează automat fapte materiale doar pentru că o pagină răspunde.

Dacă PC-ul este oprit sau nu există o sesiune Windows autentificată, jobul poate rămâne în așteptare; la următoarea autentificare runnerul revine automat.

## Verificare rapidă

În GitHub → **Settings → Actions → Runners**, runnerul `PARTENER-MIPE-<NUME-PC>` trebuie să apară `Idle` sau `Active` când sesiunea Windows este deschisă.

În Actions, workflow-ul **PARTENER.EU MIPE Romania Collector** trebuie să treacă din `Queued` în `In progress` când runnerul este online.

## Siguranță

- Nu pune parole, PAT-uri sau registration token-uri în fișierele repository-ului.
- Registration token-ul este folosit numai la configurarea inițială.
- Runnerul este repository-scoped.
- Schedulerul are doar `actions: write` și `contents: read`; persistența rămâne în workflow-ul collector existent.
