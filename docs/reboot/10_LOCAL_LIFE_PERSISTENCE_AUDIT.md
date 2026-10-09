# 10 — Local Life: persistență și ownership

Audit 9 octombrie 2026, continuarea orară 10:10 UTC. Verdict **PARTIAL**.

Baseline live: CIVORA `96f3155ba87844e55fb8607d3e1b2fa7a9803779`, public `bb1f012cf7ceca9529bf2dda43693c908cca322f`. Canonul și contractele de ownership/păstrare existente au fost consultate înainte de schimbare. Checkpoint-urile Git validate din 00 rămân punctele de recuperare; nu au fost atinse sursele sincronizate sau checkout-urile cu modificări existente.

## Defect demonstrat și modificare efectuată

Workflow-ul existent Local Life genera înainte de fetch, salva registry-ul și întregul arbore unde-iesim într-un snapshot temporar, apoi îl copia peste noul main. Retry-ul de push reutiliza același snapshot. Două regresii execută corpul Bash real al persistenței într-un fixture cu remote Git exclusiv local: concurență înainte de fetch și concurență injectată înainte de primul push. Pe codul vechi au eșuat șase verificări materiale: eveniment adăugat de celălalt writer, adresă fitness nouă și rută copil deținută separat, în fiecare scenariu. Nu s-au folosit date sau remote-uri de producție pentru fixture.

[PR #1374](https://github.com/mihaicismaru-bit/civora/pull/1374), commit `77337bc8ea4f26b3bfc192a40b7b347a524c05ce`, merge `e461b43a0b6525841d4d22e57b6d52ad88a91836`: cei trei generatori existenți rulează după fiecare fetch/reset, inclusiv la retry. Snapshot-ul și înlocuirea întregului arbore au fost eliminate. Persistența este restrânsă la registry-ul local_life_events.json și cinci pagini: hub, sport, cinema, meniul-zilei, fitness. Nu a fost adăugat un writer, framework, serviciu, cron sau mecanism de orchestrare; nicio cale activă nu a fost oprită. Concurrency-ul existent a fost păstrat.

| path/id | purpose | owner | dependencies | evidence_of_use | risk | recommendation |
|---|---|---|---|---|---|---|
| valcea-clar-local-life-sync.yml | registry și suprafețe Local Life | Local Life Sync | trei generatori existenți, main | run 37917372566 | alți writeri au scope comun | KEEP, scope restrâns efectiv |
| snapshot /tmp + copy arbore complet | replay peste main nou | același workflow | snapshot vechi | șase eșecuri reproduse | pierdere stare concurentă | DISABLE: comportament eliminat în #1374 |
| test_local_life_persistence.py | regresii concurență pe Bash real | mentenanță Local Life | stdlib, Git, Bash | două teste PASS local și în run | fixture local | KEEP |
| unde-iesim/verificat/index.html | suprafață separată S5 | S5, conform inventarului existent | proiecția publică | hash canonic neschimbat; public 404 | gap de livrare preexistent | KEEP activ canonic / INVESTIGATE livrare |
| writeri CIVORA cu scope larg | materializare runtime/editions | matrice din 08 | stări comune | inventar existent | single-writer global nedemonstrat | INVESTIGATE; nicio dezactivare efectuată |

## Teste și verificare operațională

Două regresii PASS în 15,575 secunde și self-test event writer PASS. Guardurile existente site ownership, audit automation strict și social ownership PASS; 31 writeri înregistrați, zero writeri autonomi neînregistrați și zero strict blockers în acest audit static. Cinci check-uri PR PASS. Aceste rezultate nu demonstrează absența concurenței între writerii înregistrați.

O singură dispatch a workflow-ului existent după merge: [run 37917372566](https://github.com/mihaicismaru-bit/civora/actions/runs/37917372566), SUCCESS, cu regresiile executate și pe Linux. Commit operațional `b8b302b21bc54bcb7906e7a42ffbaf99be9fc16f`: numai registry, hub, cinema și sport. Generarea existentă a actualizat proiecțiile și timestampul registry-ului; nu presupunem identitate byte-for-byte a tuturor fișierelor generate. Ruta S5 nu a fost atinsă.

Readback independent înainte 10:22:54 UTC și după 10:27:51 UTC: toate cele 36 de ID-uri de evenimente canonice păstrate; cele 91 de ID-uri/titluri publice identice baseline; receipt hash egal cu bytes persistați; 0 current; opt rute critice HTTP 200. Public HEAD a rămas `bb1f012cf7ceca9529bf2dda43693c908cca322f`: verificarea confirmă continuitatea site-ului existent, nu livrarea pe site a commitului canonic Local Life nou. Niciun articol de test, reciclare editorială sau dispatch social nou.

Hash SHA-256 canonic S5 verificat înainte/după: `149d475d22a66b33afe5550c8b18eaf901f9073975568ecda2b07eed302d4ff8`. Ruta publică /unde-iesim/verificat/ răspundea 404 înainte și răspunde 404 după. Acesta este un gap preexistent documentat, nu o regresie atribuită patchului și nici o dovadă de livrare S5.

## Recuperare și restanțe

Rollback cod: revert merge #1374 prin branch/PR normal, păstrând evenimentele adăugate ulterior; nu restaura snapshot-ul peste main. Revertul readuce riscul demonstrat, deci se folosește numai pentru o regresie justificată. Dacă trebuie revenit la proiecția generată, restaurează selectiv cele patru fișiere ale commitului operațional din părintele său, după verificarea schimbărilor ulterioare și a registry-ului. Checkpoint-urile Git verificate anterior rămân disponibile. Nu a fost necesar rollback.

Restanțe: writeri CIVORA cu staging larg și retry de snapshot, ownership runtime/editions/current_edition, proiecția S5 publică, cron Vercel Build Output/cloud, recovery extern și idempotency/timestamp churn. Nu s-au repetat cereri externe blocate fără schimbarea condițiilor. Taskul editorial clasic rămâne oprit conform ownerului. Recomandările din acest paragraf nu sunt modificări efectuate.

Următoarea acțiune Faza 0: reproduce local următoarea suprascriere între writerii cu scope larg și restrânge numai un scope demonstrat sigur; investighează read-only contractul de proiecție S5. Fără Faza 1.

Probe: evidence/local_life_persistence_audit.json, local_life_production_before.json și local_life_production_after.json. Acestea conțin identificatori, statusuri și hash-uri; nu conțin secrete sau conținut privat Drive.
