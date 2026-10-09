# 03 — Modificări și verificare

## Efectuat

1. Checkout-uri separate, branchuri cleanup și bundle-uri baseline verificate prin restaurare.
2. 8 înregistrări Actions orfane dezactivate individual; tree live complet și absența queued/in_progress verificate înaintea fiecărei operațiuni; `disabled_manually` citit după operațiune. ID-uri: 337179624, 337301115, 343450220, 343657473, 343661102, 363919030, 361190642, 347910411. Comenzile de rollback și timestamps sunt în receipts.
3. Fix public: eliminat guardul care impunea un story curent și setat `lead_story_id=null` pentru set gol. Equality check între articole și manifest rămâne obligatoriu. Trei teste reale: apply() cu zero-current și arhivă păstrată; apply() normal cu lead; manifest cu articol lipsă refuzat.
4. Creat acest director cu cele opt livrabile, inventare, hashes și evidence. Nicio modificare în canonul Drive.

## Commituri și PR-uri

- Fix: `5c88624822b1e94fa6225ed97f048b924527e5ed`.
- [PR public #51](https://github.com/mihaicismaru-bit/valcea-clar/pull/51), merged la 2026-10-09T02:57:25Z.
- Merge: `bb6bca930f25125929593174b32fa13f38958ee1`.
- [PR public #52](https://github.com/mihaicismaru-bit/valcea-clar/pull/52): adaptează trei contracte UX vechi pentru starea zero-current, păstrând verificările pentru lead normal și toate rutele arhivate. Commit `5d8c8ebfa6b70235f1545ebec3419125097975eb`, merge `e2dfde7f818d0e52c8b33a030701328752704999`.
- [PR CIVORA #1369](https://github.com/mihaicismaru-bit/civora/pull/1369) predă acest director; commitul inițial de documentare este `84dcf73ac292f81e8dd90b048e898db92b4521b3`. Istoria PR-ului păstrează și completarea referinței de predare.

## Teste

- 38 teste unitare publice PASS, 34,672 secunde; output local păstrat și sumar în evidence.
- Limită depistată după #51: testele inițiale rulate înainte de reconcile nu exercitau fixture-ul CURRENT=[]. Run 37877020809 a eșuat la trei aserțiuni UX după reconcile, înainte de deploy. #52 corectează contractele; toate cele 38 de teste au trecut apoi pe proiecția reconciliată 0/91, plus verify. Verificările PR #52 au trecut și pe datele baseline ne-reconciliate.
- self-test reconciliator și readiness PASS.
- Pipeline local existent: readiness → sync → reconcile → build → history projection → enrich metadata → verify PASS. Rezultat: CURRENT=0, archive=91, 127 rute construite înainte de enrichment; niciun articol nou.
- Automation surface self-test + strict audit PASS; site ownership PASS; social ownership PASS, held-outbox changes=0.
- Newsroom decision self-test PASS (include editorial writer și integrity); S6 governance self-test PASS.
- Blocarea socialului este separată în modelul governance existent; S6 self-test și state indică site_blocker_count=0 și channel_backlog_count=3. Nu s-a simulat un outage social real în producție.
- Restaurare bundle-uri exactă și CIVORA fsck PASS.
- Public Sync 37877613582 pe merge #52 a finalizat toate etapele, inclusiv deploy și readback. HTTP independent confirmă zero-current pe ambele suprafețe, toate cele 91 de rute în sitemap, articolele arhivate eșantionate și Local Life accesibile. Nu au fost pierdute ID-uri sau schimbate headline-uri în comparația baseline/proiecție locală (`article_preservation_check.json`).

Nu s-a declanșat un workflow social, nu s-a introdus un articol de test. Generarea locală a folosit numai date canonice și a rămas într-un checkout separat. Artefactele locale generate nu sunt commitate manual; persistența publică aparține Public Sync existent.

O încercare de merge #52 cu SHA prescurtat a fost refuzată de GitHub. Comanda următoare din acel lot a declanșat accidental run 37877581763 pe main anterior; a eșuat la aceleași teste înainte de deploy. Merge-ul a fost repetat cu SHA complet verificat, apoi s-a declanșat Public Sync o singură dată pe HEAD-ul nou (37877613582). Nu a rezultat o mutație publică din rularea accidentală.

## Rollback

Continuare 9 octombrie 2026: [PR public #53](https://github.com/mihaicismaru-bit/valcea-clar/pull/53), commit `264b3b243cf5864adad54b3224a075269e9b61d1`, merge `ff5b64cd3b0499fe3e3d725b5ecbd5b7fff53d5c`. Refolosește readiness/reconcile în recovery manual, mută testele după reconciliere și folosește grupul existent Public Sync. 38 teste locale PASS, trei checks PR PASS, deployment manual 37901247379 SUCCESS și readback independent 0 current / 91 archive PASS. Inventarul Vercel a fost recuperat fără mutații cloud. Detalii și limite: 08_OWNERSHIP_FOLLOWUP.md; probe: external_followup.json și recovery_pages_verification.json.

Rollback #53: revert normal prin PR; Public Sync rămâne disponibil. Nu a fost necesar rollback. Nu s-a dezactivat nicio cale activă în această continuare.

Predarea follow-up-ului: [PR CIVORA #1370](https://github.com/mihaicismaru-bit/civora/pull/1370), commit inițial de documentare `f5c9792d7dd64f6cfac5ddde43378511ac15f427`; numai docs/reboot, fără cod operațional.

9 octombrie 2026: ownerul confirmă oprirea taskului ChatGPT „Vâlcea Clar Redacție”. Consemnat ca owner-reported stopped, fără readback independent și fără mutație de scheduler efectuată de agent. Nu se deduce absența altor cronuri sau writeri din această confirmare.

Revert PR #51 prin branch/PR; enable pentru ID-urile orfane conform receipts; recuperare Git din bundle în director nou. Nu rescrie main. Starea externă se verifică independent după rollback. Nu s-a aplicat rollback deoarece nu a fost identificată o regresie a patch-ului la testele executate.
