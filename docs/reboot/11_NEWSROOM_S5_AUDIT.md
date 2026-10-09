# 11 — Ownership Newsroom și livrare S5: probe noi

Continuare orară 9 octombrie 2026, 11:08 UTC. Verdict **PARTIAL**. HEAD-uri live verificate: CIVORA `830e18d6e75cfb85c90b850e6c9b5f205d3b5847`, public `bb1f012cf7ceca9529bf2dda43693c908cca322f`. Rapoartele 00–10 și canonul/invariantele de păstrare din 04 au fost recitite; înaintea oricărei decizii au fost citite distinctive_products.json și contractul presentation-only S5. Nicio schimbare de cod sau resursă de producție în această rulare. Branch separat de audit; sources/ și checkout-urile cu modificări locale sunt păstrate.

## Newsroom: pierdere concurentă demonstrată local

Corpul Bash real al pasului `Persist live newsroom publication atomically` din valcea-clar-newsroom-live.yml salvează 12 căi înainte de fetch și le copiază peste main la fiecare încercare. Include runtime integral și public_ux_state.json. Fixture cu seed, runner, peer și origin bare exclusiv locale: runner modifică newsroom_state; peer modifică fitness, un fișier social media și public_ux_state. Primul scenariu avansează origin înainte de fetch; al doilea injectează push-ul peer prin hook pre-push, respinge primul push runner și exercită retry-ul. În ambele scenarii shell-ul se încheie cu succes, schimbarea Newsroom ajunge în origin, dar cele trei resurse peer revin la BASE. Șase suprascrieri demonstrate. Nu este dovada unei pierderi efectiv întâmplate în producție.

Adaptări explicite fixture: /tmp al tranzacției este relocat sub .git în directorul temporar verificat; numai exporter-ul post-push este stub, în afara persistenței studiate. Toate căile array-ului sunt prezente. Git config global/system este izolat, remotes sunt locale, fixture-ul nu conține date editoriale reale. Shell copy/stage/fetch/retry este neschimbat. Probe sanitizate: evidence/newsroom_snapshot_probe.json.

Primele încercări aveau un fixture incomplet: pathspec editions lipsea, git add eșua, iar `|| true` continua la mesajul already-present. Ele nu au demonstrat suprascrierea și nu sunt numărate printre cele două scenarii finale. Defectul de fail-open staging este separat, observat în fixture; nu se afirmă că un pathspec lipsește live. Repetarea cu toate căile prezente a demonstrat riscul de snapshot.

Fixul Local Life #1374 nu protejează acele fișiere contra writerului Newsroom cu scope larg. Nu se înlocuiește mecanic snapshot-ul editorial cu regenerare: trebuie păstrate decision, eligibility, event IDs, receipts și legătura între poveste/publication event. Nicio cale activă nu este oprită fără alternativă verificată și rollback.

## S5: existență canonică versus rezultat public

S5 este presentation-only: nu creează fapte materiale și derivă din story_archive, exemple S2 și datasetul Unde ieșim. validate() verifică fișierele runtime, modulele, numărul de fișe și sitemap-ul canonic. State OPERATIONAL (8 venue cards, 2 clarifications, 1 dossier) nu verifică domeniul public. Valorile observate sunt în evidence/s5_projection_probe.json.

| Rută | Canonic pinned HEAD | HTTP public |
|---|---:|---:|
| /clarificam/ | 200 | 200 |
| /unde-iesim/verificat/ | 200 | 404 |
| /dosare/ | 200 | 404 |
| /clarificam/restrictii-calimanesti-22-septembrie/ | 200 | 404 |
| /clarificam/somaj-valcea-august-2026/ | 200 | 404 |
| /dosare/open-air-blues-brezoi-2026/ | 200 | 404 |

Constructorul public build.py reconstruiește output-ul din propriul content și rutele sale; local_life_routes enumeră sport, cinema, restaurante, meniul-zilei, fitness. Nu conține rutele dosare/, unde-iesim/verificat/ sau child Clarificăm inspectate. sync_civora.py proiectează feed/articole/media, nu face mirror al întregului runtime. În absența unui contract comun pentru aceste produse, un simplu copy HTML ar introduce o cale de prezentare și potențiale diferențe de design; nu a fost aplicat. HTTP 200 la hubul Clarificăm nu dovedește echivalența semantică cu hubul S5 canonic.

Public Sync este configurat la minutele 1,16,31,46 în main. Ultimul run returnat de API este 37909884441, push, SUCCESS la 09:13:28 UTC; ultimul schedule returnat este 37908403026 la 08:59:35. Inventarul bounded nu explică întârzierea schedulerului și nu dovedește dezactivarea. Nu s-a trimis dispatch de audit și nu s-a creat alt scheduler. Cron cloud Vercel/Build Output rămâne inaccesibil prin suprafețele deja inspectate; nu s-au repetat aceleași cereri blocate.

## Inventar clasificat și decizii

| path/id | purpose | owner | dependencies | evidence_of_use | risk | recommendation |
|---|---|---|---|---|---|---|
| valcea-clar-newsroom-live.yml / publication transaction | poveste și stări canonice | Newsroom | decision, editions, runtime, receipts | shell real executat pe remote local | P0 overwrite peer/retry | REFACTOR LATER; tranzacția editorială trebuie validată înainte de restrângere |
| snapshot runtime + public_ux_state | replay tranzacție veche | Newsroom | 12 căi array | 6 overwrite în 2 cazuri | P0 pierde stare alt writer | INVESTIGATE; nicio dezactivare efectuată |
| git add ... || true | staging tranzacție | Newsroom | toate pathspec-urile | fail-open în fixture incomplet | P1 false success dacă pathspec lipsește | INVESTIGATE contractul staging; nu se afirmă incident live |
| s5_distinctive_products.py + distinctive_products.json | produse editoriale derivate | S5 | archive/S2/venue evidence | 6 pagini canonice, state OPERATIONAL | 5 public 404 | KEEP active utile; REFACTOR LATER livrare/receipt |
| public scripts/build.py și sync_civora.py | site Pages și proiecție | public repository | content/feed/media | HTTP critice/readback | nu acoperă toate produsele S5 | KEEP; INVESTIGATE contract de livrare |
| CIVORA Public Sync schedule | convergență cross-repo | public workflow | readiness, Pages | configurat; API bounded recent | cadență reală nedemonstrată | KEEP; INVESTIGATE scheduling |
| Vercel cloud cron/Build Output | posibil scheduler extern | owner nedemonstrat | acces cloud | limită acces din 08/09 | inventar extern incomplet | INVESTIGATE, fără retry identic |

## Continuitate, rollback și predare

Verificarea independentă curentă: 36 ID-uri de evenimente canonice păstrate, 91 ID-uri/titluri publice baseline păstrate, receipt hash valid, zero-current, opt rute critice 200 și hash canonic S5 neschimbat. Probe evidence/hour11_production_verification.json. Nu s-au șters active, editat articole, publicat fixture-uri, declanșat social, schimbat designul sau repornit taskul editorial clasic. Acesta rămâne oprit conform ownerului.

Schimbări efective: numai raport, inventar clasificat și trei probe sanitizate. Teste efective: două scenarii locale de concurență (rezultat RISK_REPRODUCED, nu test de produs PASS); verificări HTTP/ID/hash PASS pentru scope-ul declarat. Nu s-au executat suite de cod, deoarece nu există patch de cod. Recuperarea Git validată în 00 rămâne; rollback raport prin revert normal, fără mutații de producție de reversat.

Nu se declară PASS: single-writer global, cloud cron și recuperarea externă sunt încă incomplete, iar livrarea S5 nu este demonstrată. Următoarea acțiune exactă Faza 0: verifică setul minim de fișiere produse de tranzacția Newsroom și construiește o regresie care păstrează împreună story/decision/event/receipt înainte de orice reducere de scope; pentru S5 inventariază contractul de proiecție și eligibilitatea datelor existente, fără un renderer sau writer nou. STOP după Faza 0.
