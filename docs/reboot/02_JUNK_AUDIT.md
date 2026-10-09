# 02 — Junk și complexitate

## Clasificare și acțiuni

| path/id | purpose | owner | dependencies | evidence_of_use | risk | recommendation |
|---|---|---|---|---|---|---|
| 8 workflow IDs în orphan_disable_receipts.json | metadata istorică Actions | CIVORA | fișier absent pe main | live tree complet + zero queued/in_progress per ID | scăzut; rollback enable | DISABLE — efectuat |
| reconcile_civora_currentness_events.py: guard current_ids | blocare deploy zero-current | proiecție publică | renderer/manifest | log failure run 37873040220 | păstrarea stale-current | corectat prin PR #51 |
| editorial/editions/media/receipts | active editoriale și recuperare | owner/runtime | writer/proiecție | manifest/rute/registry | pierdere de date | KEEP — păstrat |
| site/runtime, dist, previews urmărite | output generat și LKG | runtime | public projection, recovery | referințe/manifest, 91 rute | regenerare incompletă | REFACTOR LATER — fără ștergeri |
| documente Drive LEGACY__*__SUPERSEDED | istorie și decizii vechi | editorial | referință | etichetă superseded explicită | confuzie de autoritate | ARCHIVE — clasificare, fără mutare în această fază |
| Live Newsroom / Autonomous Editions / Local Life Sync | writeri înregistrați cu scope suprapus | site_engine | mai multe lane-uri active | git add/push asupra runtime, concurrency diferită | stale overwrite | INVESTIGATE — fără oprire |
| deploy-pages manual | cale de deploy manuală | proiecție publică | Pages | workflow prezent cu confirmare DEPLOY | concurență cu Public Sync | INVESTIGATE — păstrat |
| Vercel 4 proiecte | deployment legacy/probe potențial | cloud account | cloud cron/Build Output necunoscute | 08: deploymenturi și aliasuri recuperate; 09: surse statice inspectate, un vercel.json fără crons | rol live/cron nedemonstrat | INVESTIGATE — păstrat |
| branchuri/PR-uri vechi | lucrări istorice | autorii PR | dependențe neevaluate | listare live | pierdere de lucru | INVESTIGATE — fără închidere |
| scripturi fără referință workflow | experiment/funcție posibil importată/manuală | maintainer | import/dynamic/manual nerezolvate | numai Git + scanare statică | false dead-code classification | INVESTIGATE — fără ștergere |
| cache/log/tmp | candidat junk | local runtime | necunoscute | căutare extensii/nume, nicio dovadă suficientă de inutilitate | eliminare evidence | DELETE SAFE: niciun element demonstrat |

Dezactivările vizează înregistrări orfane, nu 8 căi de publicare active. Fișierele lor erau deja absente. Nu se revendică economii măsurabile de compute pe baza acestei curățenii de metadata.

Nu s-a adăugat un workflow, framework, writer, serviciu cloud, bază de date, scheduler sau strat de compatibilitate. Nu s-a șters un fișier editorial ori un resource de producție. Nu s-au mutat documente Drive.

Testele de preview, dependențele și documentația fără referințe directe nu sunt declarate „junk” automat. Referințele statice incomplete sunt o limită explicită a inventarului. Consolidarea celor 142 workflow-uri VÂLCEA necesită verificarea output-ului și a consumatorilor înaintea opririi.

Mentenanță suplimentară #54: KEEP reconciliatorul existent, corectat receipt hash/lead date. Nicio ștergere sau dezactivare suplimentară. Churn-ul timestampurilor rămâne REFACTOR LATER, fără a masca expirarea TTL.

## Continuare orară: Local Life

DISABLE efectuat asupra comportamentului snapshot/copy complet din Local Life Sync (#1374), înlocuit cu regenerarea existentă după fetch. Nu s-a dezactivat writerul sau o cale activă. Generatori și ruta canonică S5 KEEP; gap public S5 INVESTIGATE. Nicio ștergere editorială.

[10 — Local Life persistence audit](10_LOCAL_LIFE_PERSISTENCE_AUDIT.md).
