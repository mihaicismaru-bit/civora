# PARTENER.EU — UX / Market / SEO Research & Upgrade Baseline
Date: 2026-09-23
Status: RESEARCH_COMPLETE → IMPLEMENTATION_IN_PROGRESS
Scope: public PARTENER.EU only; no private client/MySMIS data.

## 1. Problem statement

PARTENER.EU already has a strong trust model and a useful funding concierge, but the public product is still shaped like a JavaScript application layered over one canonical URL. The next product step is to make the same intelligence easier to understand for humans, faster on mobile, and directly crawlable/indexable as a stable information architecture.

The upgrade must preserve the canonical rule: official authority evidence is truth; unknown remains unknown; OPEN is never inferred from planning/consultation; no UX element may weaken fail-closed publication.

## 2. External market scan

### Romania — Fonduri Structurale
Sources:
- https://www.fonduri-structurale.ro/finantari
- https://www.fonduri-structurale.ro/finantari/programate
- https://www.fonduri-structurale.ro/stiri/41185/aproape-160-de-oportunitati-noi-de-finantare-s-au-strans-peste-vara-peste-70-se-acceseaza-direct-de-la-comisia-europeana

Patterns worth borrowing:
- immediate lifecycle segmentation: Active / Programate / Închise;
- short list cards with programme, date window and direct detail CTA;
- editorial updates are linked back to the relevant funding opportunity;
- broad coverage remains visible even when editorial emphasis is selective.

PARTENER.EU opportunity:
- keep the lifecycle segmentation but make it more trustworthy: DESCHIS only after current official proof;
- add richer dossiers and provenance instead of stopping at a summary card.

### EU — Funding & Tenders / Commission call discovery
Sources:
- https://commission.europa.eu/funding-and-tenders/find-calls-tender_en
- https://projects.research-and-innovation.ec.europa.eu/en/funding/funding-opportunities/funding-programmes-and-open-calls/horizon-europe/eu-missions-horizon-europe/restore-our-ocean-and-waters/calls-proposals

Patterns worth borrowing:
- filters by keyword, programme, country, subject, deadline and status;
- funding search is distinct from programme information and funded-project information;
- status and deadline are first-class search dimensions.

PARTENER.EU opportunity:
- fewer filters by default, but the same dimensions available progressively;
- human wording first, programme acronyms second.

### Czechia — DotaceEU
Source:
- https://www.dotaceeu.cz/cs/jak-ziskat-dotaci/vyhledavac-dotacnich-prilezitosti

Pattern worth borrowing:
- guided flow: region → applicant type → topic;
- clear warning that the recommender is orientative and the exact call remains authoritative.

PARTENER.EU opportunity:
- keep the natural-language concierge and add equivalent guided profile shortcuts;
- explicitly distinguish “potrivire orientativă” from eligibility confirmed by the guide.

### Poland — Fundusze Europejskie
Sources:
- https://funduszeeuropejskie.gov.pl/aktualnosci/portal-funduszy-europejskich-w-nowej-odslonie/
- https://funduszeeuropejskie.gov.pl/nabory-wnioskow/
- https://funduszeeuropejskie.gov.pl/dokumenty/harmonogram-naborow-grantowych-fengpaih/

Patterns worth borrowing:
- explicit redesign around intuitive information architecture and accessibility across devices;
- call pages answer “who, what, when, own contribution, how to apply”;
- previous document versions remain visible.

PARTENER.EU opportunity:
- use the same decision questions in each dossier;
- keep source/version timeline as a differentiator.

### United States — Simpler.Grants.gov
Sources:
- https://simpler.grants.gov/search
- https://www.grants.gov/help/search-grants/search-grants-tab

Patterns worth borrowing:
- plain, dense but understandable faceted search;
- explicit status taxonomy: Forecasted / Posted(Open) / Closed / Archived;
- eligibility is a top-level filter;
- filters are removable and counts are visible.

PARTENER.EU opportunity:
- use a compact filter drawer on mobile and persistent key filters on desktop;
- Romanian lifecycle language: Deschise acum / În pregătire / În consultare / Închise.

### Commercial benchmark — Instrumentl
Sources:
- https://www.instrumentl.com/
- https://help.instrumentl.com/en/articles/15723039-the-new-instrumentl-discover-beta
- https://help.instrumentl.com/en/articles/3827937-sorting-and-filtering-your-opportunity-matches
- https://help.instrumentl.com/en/articles/105641-tracker-view

Patterns worth borrowing:
- natural-language project description instead of keyword setup;
- matches are refined interactively;
- context/eligibility nuance is surfaced without opening multiple tabs;
- saved opportunities move into a tracker with deadlines/tasks.

PARTENER.EU opportunity:
- public discovery remains free/readable;
- later “urmărește” can become a lightweight saved-opportunity layer, but discovery and official evidence stay usable without an account.

## 3. Current PARTENER.EU UX audit

### Strengths
- excellent human-first hero: “Ce vrei să finanțezi?”;
- clear separation of OPEN, preparation, consultation and changes;
- fail-closed status/deadline checks in runtime;
- cards expose programme, grant/deadline and audience;
- dossiers already contain decision/action, quick facts, sections, sources and unknowns;
- mobile layout has specific breakpoints and search focus regression coverage.

### Critical UX / architecture gaps
1. The public information architecture exists mainly as SPA state, not stable URLs.
2. Primary navigation is button-based; crawlers and no-JS users do not receive a meaningful link graph.
3. The raw HTML fallback exposes almost only the hero; opportunity/dossier content arrives after JavaScript.
4. There is no checked-in/generated robots.txt or sitemap.xml in the public web tree.
5. All canonical metadata points to the homepage because most public states share one URL.
6. Large data projections are loaded on the homepage, including multi-megabyte dossier/canonical-call payloads.
7. The concierge is mounted after load, which can create unnecessary layout movement.
8. A user cannot copy/share a stable public URL for most dossier/search states.
9. The navigation vocabulary mixes product concepts (“Oportunități”, “Calendar”, “Știri & dosare”) rather than one consistent lifecycle model.

## 4. Simulated user journeys

### Persona A — first-time microenterprise owner
Intent: “Am o firmă mică și vreau utilaje / digitalizare.”
Failure risk today: acronyms, uncertainty about whether an item is actually open.
Target journey:
Home → describe project / Firmă-IMM shortcut → results → OPEN filter → dossier → eligibility / grant / deadline / “ce fac acum” → official source.
Success criterion: reaches a credible candidate without needing to know programme acronyms.

### Persona B — NGO manager
Intent: “Caut finanțare pentru servicii sociale / educație.”
Target journey:
Home → ONG shortcut → results → filter region/status → dossier → eligible applicant class → activities → cofinancing → documents.
Success criterion: can reject obviously irrelevant calls rapidly and see unknowns explicitly.

### Persona C — mayor / public institution employee
Intent: “Ce apeluri sunt deschise sau urmează pentru infrastructură?”
Target journey:
Deschise acum → applicant/region filtering → dossier; then În pregătire for pipeline planning.
Success criterion: OPEN and preparation cannot be visually confused.

### Persona D — farmer
Intent: “Ce pot depune acum?”
Target journey:
Agricultură shortcut → Deschise acum → AFIR dossier → deadline / possible early closure / latest documents / source.
Success criterion: authoritative lifecycle information is visible before narrative detail.

### Persona E — consultant
Intent: “Ce s-a schimbat azi și ce deadline-uri contează?”
Target journey:
Ce s-a schimbat → material changes only → linked dossier → source/version history; parallel direct route to all open calls.
Success criterion: low noise, high scan speed, stable URLs that can be shared with clients.

### Persona F — mobile user
Intent: quick search while away from desktop.
Target journey:
Home → input retains focus while typing → compact results → tap dossier → back works predictably → source opens separately.
Success criterion: no horizontal overflow, controls >= comfortable touch size, no forced desktop-density tables.

## 5. Target information architecture

Public, indexable hierarchy:

/
├── /finantari/
│   ├── /finantari/deschise/
│   └── /finantari/in-pregatire/
├── /consultari/
├── /dosare/
│   └── /dosare/{stable-slug}/
└── /schimbari/

Rules:
- search/filter query states are useful for users but are not sitemap URLs;
- every dossier has one canonical stable URL;
- every detail page links upward with visible breadcrumbs;
- homepage and hubs link using normal <a href> elements;
- CLOSED dossiers may remain indexable when PUBLISHABLE because they provide history, source/version context and outcome continuity;
- PROVISIONAL_FAIL_CLOSED / unpublished objects never enter the public static sitemap.

## 6. Google/Search-friendly contract

Reference:
- Google Search Central sitemap/breadcrumb/structured-data/page-experience guidance.
- https://developers.google.com/search/docs/appearance/structured-data/breadcrumb
- https://developers.google.com/search/docs/appearance/page-experience
- https://developers.google.com/search/docs/appearance

Implementation contract:
1. Generate robots.txt with an absolute sitemap URL.
2. Generate sitemap.xml from canonical public hubs + PUBLISHABLE dossier pages.
3. Exclude query/filter/search-result URLs from sitemap.
4. Use canonical URL per page.
5. Use real crawlable anchor links.
6. Add visible Breadcrumbs + BreadcrumbList JSON-LD on dossier pages.
7. Keep meaningful body content in static HTML; JS enhances rather than creates the only indexable representation.
8. Use lastmod only from meaningful dossier/content timestamps.
9. Preserve mobile-first layouts, visible focus and accessible semantic landmarks.
10. Do not mark speculative funding facts in structured data.

## 7. Design direction

Keep the existing sober green/navy identity. Do not perform a cosmetic rebrand.

Upgrade:
- clearer typographic hierarchy and more whitespace;
- one primary action per block;
- consistent lifecycle status colors and labels;
- high-contrast fact strip: status / deadline / grant / region;
- lighter cards with better scan hierarchy;
- source/provenance treatment visually distinct from editorial explanation;
- mobile filters collapsed progressively;
- reduced motion support;
- stronger keyboard focus;
- static pages visually consistent with the SPA.

Avoid:
- dashboard visual noise on homepage;
- unexplained scores as decision proxies;
- card walls without lifecycle grouping;
- unsupported SEO schema;
- hiding the full catalogue to keep the homepage short.

## 8. Measurement / acceptance

Primary UX measures:
- path to a relevant OPEN dossier in <= 3 meaningful interactions for guided profiles;
- OPEN never confused with consultation/upcoming in copy or styling;
- every public PUBLISHABLE dossier has a shareable canonical URL;
- every hub/detail works with JavaScript disabled;
- keyboard-accessible navigation and visible focus;
- no horizontal overflow at 360px;
- stable public sitemap and robots;
- generated pages pass HTML/static contract tests;
- existing 10/10 frontend regression remains green.

Performance targets for next optimization pass:
- reduce homepage bytes by avoiding unnecessary full-corpus projections on first paint;
- eliminate post-load homepage replacement where possible;
- progressively load heavy dossier data only when the user enters discovery/detail surfaces.

## 9. Rollout strategy

Phase 1 (this upgrade):
- crawlable information architecture;
- static SEO/public dossier projection generated from canonical decision products;
- sitemap/robots/breadcrumbs/canonicals;
- real anchor navigation;
- consistent static design;
- automated regression tests.

Phase 2:
- split heavy JS/data bundles and lazy-load dossier/canonical datasets;
- route/history synchronization for SPA states;
- mobile filter drawer and selected-filter chips;
- measure layout shift / payload / interaction latency.

Phase 3:
- lightweight saved opportunities and deadline watchlists, only if useful without contaminating public funding truth.

