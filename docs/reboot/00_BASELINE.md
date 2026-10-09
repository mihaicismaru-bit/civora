# 00 — Baseline și recuperare

## Autorități și HEAD-uri fixate

| Resursă | Baseline |
|---|---|
| CIVORA main | `5e88827c97c61c098322e59d879ba0a02e32455f` |
| valcea-clar main | `b7b204c524a32310e2469b87d76a19d98323129f` |
| Control editorial | folder Drive `18wk3WI-2qZJUFlt5POCt_q9zlsKMLwm2`, VALCEA_CLAR |
| Livrare | https://valceaclar.ro; GitHub Pages confirmat prin API `/pages`, cname=valceaclar.ro, build_type=workflow |
| Branch audit | `cleanup/phase0-reset-20261009` în CIVORA |
| Branch mentenanță publică | `cleanup/phase0-zero-current-20261009` în valcea-clar |

Checkout-ul local anterior `civora/` era pe `feat/valcea-clar-premium-frontpage-20260818`, cu modificări necomise. Nu a fost resetat, editat ori curățat. Checkout-urile auditului sunt independente. `sources/` rămâne read-only.

## Starea inițială

Baseline CIVORA: 6.846 fișiere urmărite; 277 workflow-uri prezente, 38 cu schedule. Proiecția publică: 42 fișiere, 6 workflow-uri, 2 programate. Enumerarea Actions paginată a produs duplicate; după deduplicare după ID au fost observate 330 înregistrări CIVORA, dintre care 8 VÂLCEA CLAR fără fișier pe main. Aceste numere descriu captura, nu un registru global garantat stabil.

Manifestul canonic autorizează 91 de articole, CURRENT=0. Feedul derivat conține încă un element; publicul are 3 curente / 88 arhivă. `sync/civora_state.json` consemnează source_generated_at=2026-10-06T05:53:54.082740Z. Site-ul și rutele eșantionate răspund 200. Sitemap-ul public păstrează 91 de rute de articole. Readback înainte de schimbare: `evidence/public_readback_before.json`.

Public Sync 37873040220 și 37872335766 eșuează pe baseline public. Cauză confirmată din log: reconciliatorul refuză manifestul fără active_now, chiar dacă rendererul și canonul acceptă CURRENT=[]. Quality verde nu compensează deploy-ul eșuat.

Governance runtime are observație 2026-10-07T22:14:18Z, READY_WITH_KNOWN_LIMITATIONS, cu 3 canale blocate și migrare istorică a corecțiilor incompletă. Nu este tratat ca dovadă live a sănătății globale.

## Checkpoint verificat

Bundle-urile locale din directorul proiectului `checkpoints/` conțin istoria completă:

| Fișier | SHA-256 |
|---|---|
| phase0-civora-20261009.bundle | `CC7F3A5A73DEF6D60BA8DE8C6471357B13A338B64480DFF0DE2703A480F2AE1B` |
| phase0-public-20261009.bundle | `D02E6289956BF53AA37CDC219453C66DAAF41B1FECD8B1C124604889B07229B3` |

`git bundle verify` a trecut pentru ambele. Clone-uri separate din bundle au reprodus exact HEAD-urile; `git fsck --full` pentru restaurarea CIVORA a trecut. Bundle-urile sunt locale, nu reprezintă backup off-device, nu conțin secretele GitHub, datele externe, versiunile Drive sau toate resursele cloud. Recuperarea acestor resurse nu este demonstrată. Nu s-au făcut ștergeri de date externe.

## Procedură de rollback

1. Clonează bundle-ul într-un director nou; verifică SHA-256, HEAD și `git fsck --full`.
2. Pentru fixul public, creează un branch din main actual, aplică `git revert` asupra commitului de merge al PR #51 și verifică testele. Livrează prin PR și Public Sync existent. Nu reseta/force-push main.
3. Pentru fiecare înregistrare Actions dezactivată, comanda exactă `/enable --method PUT` este în `orphan_disable_receipts.json`. Reactivarea metadata nu recreează fișierul absent.
4. Pentru raportul CIVORA, revert-ul PR-ului de documentare elimină numai documentele; starea Actions se recuperează separat.

Rollback-ul tehnic public ar readuce și incidentul zero-current. Se folosește numai dacă apar regresii și după identificarea unui LKG editorial acceptabil. Nu se declară un homepage cu știri reciclate drept LKG factual.

Checkpoint de observație suplimentar, fără înlocuirea baseline-ului: la 9 octombrie 12:16:04 Europe/Bucharest, CIVORA `7ea9bcde83045dfb8b4969ecf57763bd05fcaf11`, public `bb1f012cf7ceca9529bf2dda43693c908cca322f`. Receipt și readback după #54 verificate în `evidence/hourly_public_verification.json`. Rollback-ul #54 folosește revert normal al merge-ului `2d67f1c022eb1305f140dd90cb5df25b5a484999`, fără rescrierea main; bundle-urile inițiale rămân punctele de restaurare Git verificate.
