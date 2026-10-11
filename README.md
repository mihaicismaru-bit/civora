# civora

Monorepo pentru trei produse:

| Folder | Produs | Workflow-uri |
|---|---|---|
| `partener-eu/` | **partener.eu** — EU Funds Intelligence (GitHub Pages, CNAME `partener.eu`) | `partener-eu-*`, `needs-factory-*`, `rpm-lead-api` |
| `eucons/` | **eucons.ro** — site-ul și sistemul comercial Euroconsult; citește proiecția publică din partener.eu, nu o modifică | `eucons-*` |
| `public-presence-os/` | **Public Presence OS** — publicare social media (Facebook, Instagram) | `public-presence-*` |

`tools/` conține utilitare comune (ex. `repo_weight_audit.py`).

Vâlcea Clar și local-news-os au fost mutate din acest repo (oct. 2026) și se reconstruiesc separat în `valcea-clar`.
