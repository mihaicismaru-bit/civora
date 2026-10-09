# 09 — Audit orar: receipt și surse Vercel

9 octombrie 2026, prima continuare orară. HEAD inițial CIVORA: `2d669a0c8049b9302ee24a6c42832edc0c0586d8`; public: `ac8df90b960218dc27f760e971af835ab3d3b51e`. Delta CIVORA după confirmarea opririi taskului conține numai durable monitor state; workflow-urile și scripturile writerilor nu s-au schimbat. Suprapunerea documentată în 08 rămâne deschisă.

## Dovezi noi Vercel

Inspecția read-only a surselor ultimelor patru deploymenturi production a reușit. Arborele expus conține numai HTML, robots.txt și un vercel.json; nu există funcții sau rute API în arborele expus. Singurul vercel.json identificat în deploymentul valcea-clar declară cleanUrls, trailingSlash, redirect /admin → /editor/ și security/noindex headers, fără crons. Celelalte trei arbori nu conțin vercel.json.

[Documentația oficială Vercel Cron Jobs](https://vercel.com/docs/cron-jobs) precizează configurarea prin vercel.json sau Build Output API. Prin urmare, lipsa crons în sursa observată NU dovedește lipsa configurației Build Output sau a stării cloud. Nu s-au retrimis cererile anterior refuzate cu același context. Nu s-a instalat CLI, nu s-au accesat secrete și nu s-a oprit niciun proiect. Clasificare: surse reutilizabile KEEP; rol operațional și cron cloud INVESTIGATE.

## Modificare efectuată: receipt corect după reconciliere

La HEAD public inițial, articles_sha256 nu corespundea bytes ai content/articles.json; lead_story_id era null, dar lead_published_at păstra 2026-09-14. Receipt-ul provenea din feed înainte de reconcilierea currentness.

[PR public #54](https://github.com/mihaicismaru-bit/valcea-clar/pull/54), commit `bac66289f3c6e3d0d7f59162f25dad1663e02420`, merge `2d67f1c022eb1305f140dd90cb5df25b5a484999`: reconciliatorul existent recalculează hash-ul exact al fișierului persistat și data lead-ului curent, sau null în starea zero-current. Două fișiere schimbate: scriptul existent și regresiile sale. Nicio schimbare de articol, design, writer, dependență, scheduler sau interfață de publicare.

Patru eșecuri reproduse înainte de fix; după fix, patru teste targeted și self-test PASS, întreaga suită 39 teste PASS în 19,977 secunde. Reconcilierea locală cu manifest live păstrează 0 current / 91 archive și verifică receipt hash equality. Trei check-uri PR PASS. Fișierele generate local au fost excluse din commit.

Public Sync [37909884441](https://github.com/mihaicismaru-bit/valcea-clar/actions/runs/37909884441) a trecut build, deploy, readback și persistență. Readback independent la 09:16:04 UTC (12:16:04 Europe/Bucharest): hash receipt egal cu bytes reali, lead ID/date null, 0 current / 91 archive, toate ID-urile și titlurile baseline identice, canonical/projection/sitemap exact match și zece rute HTTP 200. Probe: evidence/hourly_public_verification.json; HEAD-uri capturate CIVORA 7ea9bcde83045dfb8b4969ecf57763bd05fcaf11, public bb1f012cf7ceca9529bf2dda43693c908cca322f. Nu s-a publicat conținut de test și nu s-a declanșat social.

Rollback: revert #54 prin branch/PR normal; păstrează Public Sync existent și verifică readback-ul și receipt-ul după revert. Checkpoint-urile baseline verificate anterior rămân disponibile; operațiunea nu a șters date. Nu a fost necesar rollback.

## Limită de idempotency și verdict

Acest patch corectează adevărul receipt-ului. Nu elimină timestampurile updated_at la fiecare reconciliere, provenance fallback la ora execuției sau tot churn-ul pipeline-ului. Înlocuirea timestampurilor fără studiul TTL/eligibility ar putea masca expirarea; rămâne datorie distinctă P2.

Verdict **PARTIAL**: cron cloud/configurația Build Output și single-writer global CIVORA nedemonstrate; taskul clasic cunoscut este oprit conform ownerului. Următorul control: reproducere locală a suprascrierii snapshot între writerii existenți și identificarea unei reduceri sigure a scope-ului înainte de orice dezactivare. Fără reconstrucție Faza 1.

Probe sanitizate: evidence/hourly_receipt_audit.json și evidence/hourly_public_verification.json. Autorizația orară aparține continuării de audit în acest fir; taskul editorial oprit nu este repornit.
