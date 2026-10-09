# 05 — Datorie tehnică rămasă

| Prioritate | Problemă demonstrată / limită | Impact și următorul control |
|---|---|---|
| P0 | runtime suprapus: Newsroom/UX/metadata, Editions, Local Life, Recovery, Social media și rollback | risc stale overwrite; matrice extinsă în 08; dovedește ownership și tranzacția câștigătoare înainte de dezactivare |
| P0 | feed derivat conține încă 1 story, manifest CURRENT=0 | defect semantic/proiecție; manifestul a corectat proiecția publică local, dar upstream trebuie reconciliat prin writer existent |
| RESOLVED | livrarea zero-current era blocată de reconciliator și teste UX | #51 + #52, Public Sync 37877613582 și readback independent confirmă zero-current + 91 rute |
| RESOLVED | Pages manual omitea reconcilierea și avea concurrency diferită | #53 refolosește readiness/reconcile și grupul Public Sync; run 37901247379 + readback PASS; ambele căi păstrate |
| P1 | Vercel cron și Git linkage necunoscute; erori ale contextului explicit | follow-up a recuperat 4 proiecte / 6 deploymenturi / 8 aliasuri în același cont; răspunsurile omit cron și gitSource, deci acestea rămân INVESTIGATE |
| P1 | taskul ChatGPT cunoscut este oprit conform ownerului; inventarul cloud nu este enumerabil din sesiune | 9 octombrie: confirmare owner pentru „Vâlcea Clar Redacție”, fără readback independent; absența altor copii rămâne nedemonstrată |
| P1 | Local Life near-term verificări vechi / public lag inițial | utilitate stale; respectă TTL/fail-closed, fără umplerea golurilor cu date inventate |
| P1 | resolver UNROUTED/NO_PRIMARY_MATCH în status istoric recent | editorial yield insuficient; cercetare target claim-level și dispositions explicite |
| P1 | secrete/state externe nu sunt în checkpoint Git; backup Drive complet netestat | recuperare globală nedemonstrată; fără destructive cleanup extern |
| P2 | 142 workflow-uri VÂLCEA, multe checks paralele/fine-grained | compute și complexity; măsoară output/consumatori și consolidatează ulterior numai după dovezi |
| P2 | 423 fișiere generate clasificate REFACTOR LATER, stări în Git | churn și dualitate de stare; păstrează până la regenerare exactă/LKG |
| P2 | 1002 fișiere clasificate INVESTIGATE | dead-code audit static incomplet; import graph + dispatch/manual consumers + artefacte recente înainte de delete |
| P2 | PR-uri vechi, prototype/vnext și verticale colocate | pierdere de control/scope; analizează independent fără merge sau ștergere automată |
| P2 | status Drive append-heavy, header/version stale | boot cost și autoritate confuză; compactare numai cu snapshot și delta verificată |
| RESOLVED | receipt lead_published_at/hash proveneau dinainte de reconcile | #54 recalculează hash-ul fișierului persistat și lead publication date/null; regresii pentru current și zero-current PASS; vezi 09 |
| P2 | Public Sync actualizează updated_at la fiecare reconciliere; fallback-uri de provenance folosesc ora execuției | idempotency incompletă; verifică diff repetat și TTL înainte de curățare, fără scheduler nou; #54 nu rezolvă churn-ul |

Nu sunt ascunse ca PASS global rezultatele locale ale guard-urilor. Nu există dovadă de writer neînregistrat din scanarea existentă; există posibilitate demonstrată de suprapunere între writeri înregistrați. Nu s-a introdus un mecanism nou pentru a o masca.

## Continuare orară: Local Life

REZOLVAT pentru Local Life Sync: snapshot stale după fetch/retry și staging întreg arbore; #1374 cu două regresii. P1 INVESTIGATE: S5 /unde-iesim/verificat/ canonic există, public 404 înainte/după. Rămân scope-urile comune ale altor writeri, cloud cron și timestamp churn; single-writer global nedemonstrat.

[10 — Local Life persistence audit](10_LOCAL_LIFE_PERSISTENCE_AUDIT.md).
