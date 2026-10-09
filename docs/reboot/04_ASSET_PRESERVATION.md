# 04 — Active păstrate

## Invariante

Verificare suplimentară după #54: setul de 91 ID-uri și titlurile publice sunt identice cu checkpoint-ul baseline restaurat; sitemap-ul, proiecția și manifestul canonic coincid. Nu s-au modificat articole, media sau canonul pentru fixul de receipt. Probe: evidence/hourly_public_verification.json.

Păstrează misiunea pentru întreg județul Vâlcea; identitatea/brandul; standardul factual și proveniența; produsele editoriale și Local Life; research, surse, media cu drepturi, corecții și istoricul; publicarea demonstrată prin body/readback/receipt; single-writer pe resursă și idempotency. Un comunicat/semnal nu este automat articol. Un material vechi nu reintră în CURRENT fără delta materială nouă.

Arhitectura CIVORA, repo layout, workflow-uri, registries, cronuri și API-uri interne sunt alegeri tehnice revizuibile. Instrucțiunea ownerului pentru Reset 2026 prevalează asupra cerințelor tehnice istorice. Arhitectura veche nu devine contract pentru reconstrucție.

## Canon citit din Drive înainte de patch

| Document | ID | Clasificare |
|---|---|---|
| 00_START_HERE CANON v2.2 | 1bm8w5MEZxO4Z-taKQYJwhIP9rG65lr3LCOs0f8LIMHo | KEEP |
| 01_SYSTEM_CANON v2.1 | 1t1d6DafsF7vnOu2ly379lHCSD5XuFqJVpGP7dbQdJG8 | KEEP politici; mecanică revizuibilă |
| 02_CURRENT_STATUS | 1PmCRUZmQ0h6kr9_deaoUWuO7sVdLxSfPHzNwbCMl7F8 | KEEP evidence; header vechi, delte până la 9 octombrie |
| 03_EDITORIAL_RULES v2.1 + addendum no-recycle | 14mDx7712v9NktGdkC9yUHXiMKPqkntmVvoPDrQUFKrA | KEEP |
| 04_PRODUCT_CONTRACTS v2.1 | 1VHFSLf7ByAXsrMzF7R_HUgoLSitdl42MrDgrTvghKQM | KEEP |
| 50_SOURCE_REGISTRY | 1aaPc5IwN8-5XEjH9fjltjFFpo1wTyzp33qpj08DJVog | KEEP |
| 51_UAT_COVERAGE_AND_SCAN_PLAN | 16yZVm-Xs8a44EtOMVx19FR7jTjJo_vTyI7MZZYjnJBU | KEEP coverage; cadence tehnică revizuibilă |
| 32_LOCAL_LIFE_CANON | 146oZaHs8IhnfgiEbUKQhGe6b-Ocl4hPgMgcMJqUlbR4 | KEEP |
| 60_CHANNEL_PACK_CANON | 1pQd1BeeMQwhZUhEBT3x67Us5GJJ62VD3hkhe_xwZzD0 | KEEP editorial |
| 90_HOURLY_WORKER_CONTRACT | 1WMPDxW1IqNjGgBWTVzPr5rxqBsoKS8O9JwKpHDiXbsM | KEEP reference; nu obligație de arhitectură |

Documentele private sunt păstrate în Drive. Nu s-au publicat copiile integrale în GitHub. Canonul are versiuni în titlu diferite de addendum/body în unele documente; autoritatea se citește din conținut și instrucțiunea curentă, nu din nume.

## Editorial, date și media

Baseline public are 91 articole; fixul le păstrează în proiecție/arhivă. Inventarul hash este `evidence/preservation_sha256.csv` pentru toate fișierele urmărite din ambele HEAD-uri baseline. Persistența `facts_registry`, Fact Kernels, manual queue, source registries, publication holds, Local Life, editions, dossiers și social receipts a fost păstrată. Imaginile nu sunt relicențiate prin această fază; proveniența și rights rămân obligatorii.

Folderul Drive conține separat HQ/control, blockers, engine pointers, newsroom/articles/editions, product/site, sources/local intelligence, Local Life, media, distribution, hourly receipts și archive. Listările live sunt capturate în `drive_reference_inventory.json`; lista hourly este bounded și nu este declarată backup complet. Research-ul, agenda DJC și legacy superseded sunt păstrate. Fișierele sincronizate `sources/` nu au fost editate.

Preservation hash verifică identitatea fișierelor Git; nu dovedește backup complet Drive/social/cloud. Nicio ștergere ireversibilă nu este justificată până la recuperare verificată pentru resursa respectivă.

## Continuare orară: Local Life

Readback înainte/după #1374: 36 ID-uri canonice Local Life păstrate, 91 ID-uri/titluri publice baseline păstrate, ruta canonică S5 hash neschimbat. Proiecțiile generate au fost actualizate de generatorii existenți; nu pretindem bytes identici. Public HEAD neschimbat; S5 public 404 preexistent. Probe în 10/evidence.

[10 — Local Life persistence audit](10_LOCAL_LIFE_PERSISTENCE_AUDIT.md).
