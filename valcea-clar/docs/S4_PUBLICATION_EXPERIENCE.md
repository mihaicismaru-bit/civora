# VÂLCEA CLAR — S4 Publication Experience

S4 turns the existing public runtime into a coherent publication surface without changing editorial facts.

## Delivered

- visible editorial responsibility on article pages;
- explicit `Publicat` vs. `Actualizat` semantics (only explicit update/correction timestamps qualify; `last_seen_at` never does);
- public correction register at `/corectii/registru/`;
- RSS 2.0 at `/rss.xml`;
- dedicated rubric pages generated from the article's explicit `section`;
- locality pages generated only from explicit locality metadata already present in S2 artifacts — no locality inference from title/slug;
- sitemap additions for S4 reader routes;
- S4 is called from canonical Public UX and story-integrity renders so it persists after future rebuilds.

The existing `/corectii/` page remains the editorial corrections policy; the S4 register is the machine/readable history surface. Its migration flag is deliberately `false`: absence of a row is not presented as proof that no historical update ever occurred.

## Acceptance

S4 closes when the runtime contains rubric and locality indexes, correction register, RSS, article responsibility metadata, published-time metadata, and all existing Quality/Ownership/runtime gates remain green.
