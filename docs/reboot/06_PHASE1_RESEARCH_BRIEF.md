# 06 — Întrebări pentru cercetarea Fazei 1

Acesta este un brief, nu o soluție aleasă. Faza 1 nu a început.

1. Care sunt resursele canonice reale: articol/claim/proveniență, entity/story identity, currentness, calendar, media rights, delivery receipts? Ce mecanică legacy poate fi eliminată fără pierderea acestora?
2. Un repository editorial și unul de proiecție versus un repository cu componente separate: costul de operare, ownership, atomicitate, recovery și latență demonstrabilă pentru fiecare alternativă.
3. Cum se garantează un singur writer per resursă? Comparație între reducerea writerilor existenți, ownership exclusiv pe subarbori și serializarea existentă. Nu adăuga orchestrare înainte de probarea necesității.
4. Care registre sunt politică, source frontier, observații runtime, ledger sau cache? Pot fi consolidate fără a confunda signal cu evidence și fără a pierde historicul?
5. Ce parte a pipeline-ului poate fi pură/deterministă și ce necesită judecată editorială? Cum se testează fail-closed pentru zero-current, source missing, false certainty, duplicate și stale Local Life?
6. Ce output verificabil produce fiecare cron/check? Care poate deveni manual, event-driven sau dispărea fără să afecteze livrarea ori recuperarea?
7. Care hosting este efectiv live și care proiecte sunt doar probes? Compară utilizarea infrastructurii deja disponibile după inventarierea aliasurilor/deployments; nu adăuga servicii.
8. Cum se păstrează rutele, timestamps, corrections, SEO, article/media rights și research în migrare? Ce exercițiu de restaurare demonstrează recuperarea Git + Drive + stare externă?
9. Cum se măsoară discovery→factual closure→publication→body readback și freshness, fără target de volum? Cum se izolează un canal social fără a bloca site-ul?
10. Cum separăm identitatea receipt-ului, ceasul de execuție și expirarea TTL? #54 demonstrează că hash-ul trebuie să descrie bytes publicați după reconciliere; stabilizarea timestampurilor nu trebuie să ascundă o schimbare reală de eligibility.

Artefacte necesare înainte de alegere: matrice completă resource→writer→trigger→commit→deploy→receipt; inventar scheduler extern/cloud; probe de regen/recovery; baseline cost/output; riscuri și tradeoff pentru fiecare alternativă. Canonul editorial este invariant; CIVORA actual nu este cerință.

## Continuare orară: Local Life

Întrebare pentru cercetarea ulterioară: ce contract permite derivarea fiecărei proiecții din HEAD-ul sursă actual și păstrează ownership-ul copil la retry? #1374 demonstrează o corecție locală în mecanismul existent, fără alegere arhitecturală. Ce contract de livrare lipsește pentru suprafața S5 deja canonică? Nu se începe reconstrucția.

[10 — Local Life persistence audit](10_LOCAL_LIFE_PERSISTENCE_AUDIT.md).
