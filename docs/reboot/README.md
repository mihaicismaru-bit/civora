# VÂLCEA CLAR — Reset 2026, Faza 0

Audit realizat la 9 octombrie 2026. Citește 00 → 07. Acest director documentează infrastructura existentă și limitele verificării; nu definește arhitectura următoare.

Inventarul detaliat este în `evidence/file_inventory.csv` și `workflow_inventory.csv`. Coloanele de dependențe/referințe sunt indicii statice, nu dovada exhaustivă a execuției. `INVESTIGATE` înseamnă că utilizarea sau proprietarul exact nu au fost demonstrate. Nu autorizează ștergerea.

`preservation_sha256.csv` identifică fișierele baseline prin SHA-256. CSV-ul acoperă ambele repository-uri; inventarul clasificat acoperă VÂLCEA CLAR, LOCAL NEWS OS, toate workflow-urile CIVORA și proiecția publică. Celelalte verticale CIVORA sunt inventariate la nivel de componente și workflow-uri, fără audit semantic complet.

Rapoartele publice conțin numai identificatori tehnici, referințe și dovezi fără credențiale. Canonul privat din Drive este referențiat, nu copiat integral în repository-ul public. Scripturile temporare folosite pentru audit nu sunt mecanisme de producție și nu sunt adăugate în repo.
# Actualizare de stabilizare

[08 — Ownership follow-up](08_OWNERSHIP_FOLLOWUP.md): recovery Pages corectat, inventar Vercel recuperat, matrice writeri extinsă și limite restante.

[09 — Hourly receipt audit](09_HOURLY_RECEIPT_AUDIT.md): receipt hash/lead metadata corectat și surse Vercel inspectate read-only.

[10 — Local Life persistence audit](10_LOCAL_LIFE_PERSISTENCE_AUDIT.md): regenerare după fetch/retry, scope restrâns și probe de păstrare; verdict PARTIAL.

[11 — Newsroom / S5 audit](11_NEWSROOM_S5_AUDIT.md): overwrite local demonstrat, gap public S5 și limitele schedulerului.
