# civora

Monorepo pentru trei produse:

| Folder | Produs | Workflow-uri |
|---|---|---|
| `partener-eu/` | **partener.eu** — EU Funds Intelligence (GitHub Pages, CNAME `partener.eu`) | `partener-eu-*`, `needs-factory-*`, `rpm-lead-api` |
| `eucons/` | **eucons.ro** — site-ul și sistemul comercial Euroconsult; citește proiecția publică din partener.eu, nu o modifică | `eucons-*` |
| `public-presence-os/` | **Public Presence OS** — publicare social media (Facebook, Instagram) | `public-presence-*` |

`tools/` conține utilitare comune (ex. `repo_weight_audit.py`).

Vâlcea Clar și local-news-os au fost mutate din acest repo (oct. 2026) și se reconstruiesc separat în `valcea-clar`.

## partener.eu — ritmul de colectare (din 2026-10-11)

Colectarea rulează **de două ori pe zi**, în două ferestre (ore UTC; România = UTC+3 vara, UTC+2 iarna):

| Pas | Fereastra 1 | Fereastra 2 |
|---|---|---|
| Surse oficiale (registru, Legislativ, ESC, EEA, F&T, MFF) | 04:05–04:18 | 14:05–14:18 |
| **MIPE crawl complet** (runner Windows din România; până la 2000 pagini, adâncime 6, max. 80 min, se oprește când frontiera se golește) | 04:20 | 14:20 |
| MIPE ingest, AFIR, PEO | 05:50–06:03 | 15:50–16:03 |
| Decision products → Editorial (doar dimineața) → Validare | 06:20–06:50 | 16:20–16:50 |

Pages se publică după fiecare pas, dar sare peste republicare dacă site-ul construit e identic cu cel live (sub 6 h). Calculatorul cu runner-ul Windows trebuie să fie pornit la 04:20 și 14:20 UTC. Orice workflow se poate porni și manual din Actions.
