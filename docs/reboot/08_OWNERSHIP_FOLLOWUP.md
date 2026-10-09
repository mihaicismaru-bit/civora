# 08 — Stabilizare suplimentară Faza 0

Continuare autorizată prin „next+”, 9 octombrie 2026. Verdict **PARTIAL**. Actualizează limitele raportului inițial; baseline-ul și checkpoint-urile rămân istorice.

## Efectuat: recovery Pages

[PR public #53](https://github.com/mihaicismaru-bit/valcea-clar/pull/53), commit `264b3b243cf5864adad54b3224a075269e9b61d1`, merge `ff5b64cd3b0499fe3e3d725b5ecbd5b7fff53d5c`.

Calea manuală sincroniza feed-ul upstream stale (1 current) fără reconcilierea cu manifestul (0 current). Refolosește acum readiness și reconcilierea existente înainte de teste/build. Grupul de concurrency devine `valcea-clar-civora-public-sync`, identic cu livrarea automată, `cancel-in-progress: false`. Ambele căi rămân disponibile; nicio automatizare, dependență, componentă sau cale nouă. Serializarea controlează cele două căi Pages, fără a demonstra single-writer global.

Validare locală: readiness PASS; reconciler self-test PASS; reconciliere 0 current / 91 archive; 38 teste PASS în 46,389 secunde; build, history projection, metadata și verify PASS. YAML parsat confirmă concurrency comună și readiness → sync → reconcile → tests → build. Trei checks PR PASS. Run manual [37901247379](https://github.com/mihaicismaru-bit/valcea-clar/actions/runs/37901247379) SUCCESS, inclusiv deploy. Readback independent fără cache PASS: zero-current pe homepage și /stiri/, sitemap egal exact cu cele 91 ID-uri din manifestul canonic, două articole arhivate și cinci suprafețe Local Life HTTP 200. Probe: evidence/recovery_pages_verification.json. Fără conținut de test.

Prima expresie de parsare din verificatorul local excludea greșit ID-urile cu litera s și a produs un mismatch fals. A fost corectată, apoi readback-ul repetat a trecut; nu a fost identificată o regresie de producție.

Rollback: revert #53 prin branch/PR normal; Public Sync rămâne disponibil. Revert-ul reintroduce riscul stale pe calea manuală, deci verifică înainte de dispatch. Bundle-urile baseline rămân disponibile. Nu s-a executat rollback.

## Inventar Vercel recuperat

Cererile cu teamId explicit au răspuns inconsistent (listă goală, 404, 403); contextul implicit a returnat aceleași patru ID-uri, cu accountId=team_C4qLzkG5lGcGriTEdvm1a95a. S-au comparat identitatea și ID-urile. Nu s-au schimbat credențiale sau permisiuni.

| Proiect | Deploymenturi listate | Ultimul production | Aliasuri |
|---|---:|---|---:|
| valcea-clar | 1 | dpl_9RCccvy9gGgcRk5qVVKVfh4ArYet, READY | 2 |
| valcea-clar-live | 3 | dpl_GzzY51zn8wGwbio1HaiLCqVjbLoY, READY | 2 |
| valcea-clar-autonom | 1 | dpl_AHPab5CHgfbN3WtpPjqqBCMLxZLy, READY | 2 |
| valcea-clar-editor-probe | 1 | dpl_7L2b2SHdzLyMZvcWJm73M4cr8Lx8, READY | 2 |

Listele observate au paginare fără next; nu se revendică istoricul deploymenturilor șterse. Domeniile și aliasurile listate sunt *.vercel.app, fără valceaclar.ro. GitHub Pages rămâne proprietarul demonstrat al domeniului canonic. READY este stare control-plane, fără revalidare editorială a paginilor Vercel sau afirmație de inactivitate.

Configurația urmărită valcea-clar/vercel.json are numai outputDirectory și trailingSlash, fără crons. Răspunsurile connectorului omit cron și gitSource. **Absența cronurilor cloud rămâne NEDEMONSTRATĂ.** Proiectele sunt păstrate. Probe fără datele creatorilor: evidence/external_followup.json.

## Writeri: scope și gate-uri reale

Inspecție pe CIVORA HEAD `503f583720` și public HEAD înainte de patch `45196af714ba1443077517d32b85d3acbd43d0c7`. Gate-urile PR/preview au fost citite; o mențiune de runtime nu dovedește push extern.

| Mecanism | Scope persistent | Gate / concurrency | Concluzie |
|---|---|---|---|
| Live Newsroom | editions, pointer, archive, runtime; indexing chiar fără story nou | decision; valcea-clar-live-newsroom | writer activ; snapshot retry poate copia stare veche |
| Autonomous Editions | editions, pointer, auto_facts, runtime, ingest | run_generation; grup editions | suprapunere cu Newsroom |
| Local Life Sync | events, runtime/unde-iesim | push/manual; grup local-life | înlocuire snapshot; suprapunere runtime general |
| Edition Recovery | editions, pointer, runtime | persist push/manual, fără PR; grup propriu | writer suplimentar de recovery |
| S4, S5, Story Social Metadata | runtime, public_ux_state | persist fără PR; grup Newsroom | serializate cu Newsroom, nu Editions/Local Life |
| Social Publication Engine | social state, runtime/media/social | persist fără PR; grup social propriu | media suprapusă cu runtime general |
| S6 governance | governance/audit; runtime numai rollback explicit | execute_runtime_rollback manual; grup propriu | nu s-a declanșat rollback |
| Canonical Export | preview/artifact | manual/PR, fără git push | nu este writer main în workflow-ul inspectat |
| Public Sync + manual Pages | Pages; Sync persistă proiecția publică | grup comun după #53 | suprapunere Pages controlată |

Nicio cale CIVORA activă nu a fost dezactivată. Un grup comun numai pentru primele trei ar lăsa necontrolate Recovery, Social și rollback; nu ar demonstra invariantul global. Suprapunerea rămâne P0, fără introducerea unui strat nou de coordonare.

## Scheduler și următorul pas

Nu există API disponibil pentru enumerarea taskurilor ChatGPT clasice. Încercarea read-only cua.getState() a eșuat la inițializarea sandboxului Windows, înainte de acces la browser. Nicio stare UI citită sau schimbată. Inventarul Pages automations nu ar demonstra starea taskului clasic. S-a cerut ownerului starea/cadența/ultimul rezultat pentru „Vâlcea Clar Redacție”, fără secrete.

Actualizare owner, 9 octombrie 2026: utilizatorul confirmă că a oprit taskul discutat „Vâlcea Clar Redacție”. Stare: **OPRIT — confirmare owner**, fără verificare live independentă. Utilizatorul nu crede că ar mai fi activ în altă parte; această apreciere nu constituie inventar complet al altor schedulere. Agentul nu a efectuat o dezactivare și nu a modificat taskul.

Următorul pas: inventar read-only al cronurilor Vercel și, dacă există, al copiilor taskului clasic, apoi decizie documentată de ownership per resursă CIVORA, cu livrare rămasă și rollback demonstrate înainte de dezactivarea unei căi active. Taskul cunoscut nu mai este tratat ca activ fără dovezi contrare. **STOP: fără implementarea Fazei 1.**
