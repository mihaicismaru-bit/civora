# 01 — Inventar legacy

Inventar per fișier: `evidence/file_inventory.csv`, cu `path/id | purpose | owner | dependencies | evidence_of_use | risk | recommendation | classification`. Inventar per workflow: `workflow_inventory.csv`, cu triggers, cron, permissions, concurrency, scripturi și efecte potențiale. Permisiunea de write nu dovedește singură publicare externă; un script numit publish poate fi preview. Gate-urile trebuie citite.

## Componente și căi

| Componentă | Rol și stare | Recomandare |
|---|---|---|
| Drive VALCEA_CLAR | canon, contracte, cercetări, evidențe, worker contract | KEEP |
| valcea-clar/editorial | facts/kernels, manual intake, source frontier, Local Life, holds, identity/currentness | KEEP date; REFACTOR LATER mecanică |
| valcea-clar/engine/automation_registry.json | allow-list producție; 31 workflow-uri prezente | KEEP ca evidență; convenția este revizuibilă |
| valcea-clar/scripts | verificare, compoziție, renderer, writer, readback, governance | INVESTIGATE utilizare per script; REFACTOR LATER căile active |
| valcea-clar/site/runtime | proiecție urmărită în Git, articole/rute/media și manifest | REFACTOR LATER; nu șterge înainte de regenerare demonstrată |
| valcea-clar/social | stare/outbox/receipts/preview și adaptoare | KEEP receipts; REFACTOR LATER mecanică |
| local-news-os/core și social | runtime comun importat/folosit de verticală | INVESTIGATE granular; păstrează dependențele demonstrate |
| local-news-os/vnext | arhitectură istorică alternativă deja existentă | INVESTIGATE; fără activare ori extindere |
| partener-eu, eucons, public-presence-os și alte verticale | proiecte colocate, workflow-uri și dependențe comune | KEEP în afara curățeniei destructive VÂLCEA |
| repository valcea-clar | proiecție publică Python/static, content și Pages | KEEP livrare; REFACTOR LATER separarea stării |

Calea editorială existentă: surse/ingest/semnale → primary verification/manual intake → Fact Kernel Builder → facts_registry → Live Newsroom/editorial writer/integrity → manifest/runtime → Public Sync în repository-ul public → reconciliere/currentness/Local Life → build/metadata/verify → Pages → readback → persistare proiecție. Socialul are adaptoare și lane-uri independente; SITE PASS precedă distribuția conform canonului.

Public Sync: `1,16,31,46 * * * *`; workflow-ul manual deploy-pages poate livra tot în Pages, dar are alt grup de concurență (`pages` față de `valcea-clar-civora-public-sync`). Manualul nu a fost executat.

## Writeri și proprietate

| Resursă | Mecanisme capabile să scrie | Limită |
|---|---|---|
| facts_registry | Fact Kernel Builder înregistrat | gate existent single-writer |
| site/runtime, editions, current_edition | Live Newsroom și Autonomous Editions | ambele înregistrate; grupuri de concurență distincte, scope suprapus |
| site/runtime/unde-iesim | Local Life Sync și writerii runtime mai largi | snapshot copy/retry poate suprascrie o proiecție mai nouă |
| Pages public | Public Sync; deploy-pages manual | două căi existente, serializare comună nedemonstrată |
| Facebook/Instagram/TikTok | Social Publication Engine | guard existent PASS; nu s-a publicat social în audit |
| Threads | adaptor Threads înregistrat | lane separat; delivery live nu este reverificată în Faza 0 |
| X/LinkedIn/YouTube/Telegram/WhatsApp | OUTBOX_ONLY în registry | preview/outbox nu sunt livrare |

Guards: 142 workflow-uri VÂLCEA prezente, 31 înregistrate, zero writeri/dispatcheri autonomi neînregistrați; 63 observers neînregistrați (62 doar push), 48 manual/PR-only. PASS al allow-list-ului nu demonstrează serializare pe resursă a writerilor înregistrați. `single-writer` este invariant de păstrat, nu afirmație de audit deja satisfăcută integral.

## Stări și schedulere externe

Rolurile registrelor de surse sunt în `source_control_map.json`: politica editorială, frontieră discovery, stare de sănătate, evidența catalogului și progresul de verificare sunt distincte. Nu sunt comasate doar pentru că au surse comune.

Workerul ChatGPT orar „Vâlcea Clar Redacție” este descris în canon/receipts ca orchestrator extern. Nu există în această sesiune API de enumerare a schedulerului ChatGPT clasic; înregistrarea live/enable-state nu este demonstrată. Directorul local Codex automations a avut zero intrări observabile; nu dovedește absența automatizărilor cloud.

Vercel listează patru proiecte: valcea-clar, valcea-clar-live, valcea-clar-autonom, valcea-clar-editor-probe. Citirea deploymenturilor returnează 403; CLI vercel nu este disponibil. Cronuri, aliasuri, deployment activ și rol operațional rămân INVESTIGATE. Nu s-a oprit niciun proiect.

Inventarul de branches și PR-uri deschise este capturat în `evidence/open_prs.json` și `branches.json`. Vechimea nu justifică închidere/ștergere; toate au rămas păstrate.

Dependențe: runtime Python 3.12/3.13; Actions checkout/setup/upload/deploy; Pillow în renderer-ele sociale; local-news-os/core; standard-library HTTP/JSON/zoneinfo. Nu există manifest central de dependențe VÂLCEA. Nu s-a eliminat nicio dependență fără probă. tzdata a fost instalat numai în mediul Windows de audit pentru testare, fără schimbare de dependențe de producție.
