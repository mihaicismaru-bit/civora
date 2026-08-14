# VÂLCEA CLAR — SOURCE INTELLIGENCE CANON v1.0

Status: `CANONICAL_BASELINE`
Date: 2026-08-15
Scope: discovery, crawling, source scoring, entity graph, document graph, signal generation, verification routing and editorial safety.

## 1. Objective

VÂLCEA CLAR maintains an adaptive local intelligence layer that continuously discovers, evaluates and monitors public-information sources relevant to Vâlcea. The system must learn from confirmation history, adapt crawl frequency and source priority, expand its graph automatically and remain fail-closed for publication.

The goal is not maximum URL volume. The goal is: for every important local entity, know where to look when something changes.

## 2. Mandatory source families

The system must discover and monitor, where publicly accessible and lawful:

- all active local newspapers/publications and their official social channels;
- official sites and public channels of local companies;
- ONRC and company-ranking/business-intelligence sources;
- SICAP/public procurement sources and CNSC decisions;
- portal.just.ro and relevant court records;
- ANAF public datasets/lists where relevant;
- ANI public integrity communications and legally available data;
- Monitorul Oficial and local official gazettes;
- Prefecture, County Council, municipalities/local councils and deconcentrated services;
- Police, Gendarmerie, ISU, health institutions, environmental/water authorities, utilities and transport authorities;
- cultural institutions, theatres, museums, libraries, philharmonics, galleries, festivals and public cultural organizers;
- local companies by sector, especially large employers, contractors, construction, hospitality, retail, health, energy and transport;
- restaurants, cafés, pubs, clubs, hotels, event halls and leisure venues;
- gyms, studios, personal trainers, barbers, beauty/nail businesses and related services;
- lawyers, law firms, notaries and other regulated legal professions via official professional registers;
- business clubs, chambers, employer organizations and professional networks;
- political/public figures with a documented Vâlcea connection;
- artists, creators, athletes and cultural figures with a documented Vâlcea connection;
- public/documentable Masonic organizations and similar organizations, subject to strict sensitive-membership rules;
- data.gov.ro and other public open-data catalogues;
- geospatial/cadastral public sources when a legitimate investigation requires them;
- official social accounts and public community channels as discovery sources.

## 3. Source taxonomy

Authority tier and editorial priority are separate dimensions.

- `T1` — primary official document/source;
- `T1B` — official channel of the entity;
- `T2` — identifiable reputable secondary source;
- `T3` — aggregator, directory, repost, community or unverified discovery source.

A source can be high-priority and still remain T2/T3 for factual confirmation.

## 4. Mandatory source scoring

Every source has scores from 0 to 100:

- `importance_score`
- `relevance_score`
- `authority_score`
- `reliability_score`
- `freshness_score`
- `exclusivity_score`
- `signal_value_score`

Default aggregate:

`source_priority_score = 0.22 importance + 0.20 relevance + 0.18 authority + 0.15 reliability + 0.10 freshness + 0.08 signal_value + 0.07 exclusivity`

Editorial grades:

- `A+` 90–100
- `A` 80–89
- `B` 65–79
- `C` 50–64
- `D` 30–49
- `E` 0–29

Every source also stores per-vertical relevance for at least: breaking, administration, politics, economy, culture, events, unde_iesim, lifestyle, investigations, justice, sport, city and county.

## 5. Adaptive lifecycle

Source lifecycle:

`DISCOVERED_UNRATED -> PROBATION -> ACTIVE -> STRATEGIC`

Degradation states:

`LOW_VALUE`, `DORMANT`, `INACTIVE`, `MOVED`, `FAILED`.

Transitions are data-driven but auditable. No automatic transition may elevate factual authority from T3/T2 to T1/T1B.

## 6. Adaptive crawling

Each URL/source gets a dynamic `next_fetch_at` based on:

- source priority;
- page volatility;
- vertical urgency;
- entity heat;
- historical confirmation value;
- fetch cost;
- failure history.

Preferred access order:

`API/RSS -> sitemap -> conditional HTML fetch -> rendered browser only when necessary`.

Use ETag, Last-Modified, If-None-Match, If-Modified-Since, robots/rate limits, retry/backoff and last-known-good preservation.

## 7. Automatic discovery

For every domain discover:

- robots.txt;
- sitemap.xml and sitemap indexes;
- RSS/Atom feeds;
- canonical URLs;
- JSON-LD/schema.org;
- public APIs;
- relevant internal sections such as news, HCL, procurement, events, jobs, menus, press, legal pages and documents.

Any cited entity, domain, document or official account can become a source candidate. The graph grows from source citations, documents, procurement records, court records, company records and entity relationships.

## 8. Source graph, entity graph and document graph

Canonical entity types include at least:

`PERSON`, `COMPANY`, `INSTITUTION`, `VENUE`, `PROJECT`, `CONTRACT`, `PROCUREMENT`, `CASE`, `EVENT`, `PROPERTY`, `ORGANIZATION`, `DOCUMENT`.

Every relationship stores source, date, relation type and confidence. Coincidence of name/address is never enough to create a sensitive relationship.

Documents have version lineage, hash, issuer, publication date, retrieved date and diff against previous versions. Silent replacement of official PDFs/annexes must be detectable.

## 9. Signal engine

Source quality is separate from signal importance.

Every signal gets independent scores for:

- entity importance;
- local impact;
- public interest;
- novelty;
- urgency;
- exclusivity;
- verification need.

Changes are classified, at minimum, as:

`NEW_DOCUMENT`, `VALUE_CHANGE`, `DATE_CHANGE`, `PERSON_CHANGE`, `COMPANY_CHANGE`, `STATUS_CHANGE`, `REMOVED_CONTENT`, `NEW_LAWSUIT`, `COURT_DECISION`, `NEW_PROCUREMENT`, `NEW_SUBCONTRACTOR`, `PRICE_CHANGE`, `OPENING_CLOSURE`, `NEW_EVENT`.

## 10. Higher-order detection

Mandatory derived engines:

- duplicate/propagation detection;
- source provenance/origin detection;
- cross-source contradiction detection;
- missing expected document/public-record detection;
- historical anomaly detection;
- source-pair monitoring, e.g. SICAP<->CNSC, company<->ONRC<->portal.just<->ANAF;
- follow-the-money graph: budget -> project -> procurement -> contract -> company -> subcontractor -> payment -> addendum -> reception;
- promise tracker for public commitments;
- expected-event detection around deadlines;
- geospatial correlation where legally and editorially justified;
- coverage/blind-spot heatmap by locality and vertical;
- source diversity guard;
- source failure/rescue mechanism;
- source trust by topic;
- claim-level confidence scoring;
- sensitive-claim gate;
- right-to-reply manager;
- story decay/revisit model;
- evidence ledger.

## 11. Rumour/community handling

Facebook groups, comments, TikTok, Reddit, WhatsApp tips and community channels may generate `SIGNAL` only. They cannot create publishable facts by themselves. The system extracts the claim/entity/location and searches automatically for higher-authority confirmation.

## 12. Sensitive categories

Masonic membership and similar sensitive affiliations must never be inferred from photos, symbols, friendships, event attendance or rumours. Individual membership may be considered only when publicly self-declared or robustly documented from public sources and there is legitimate public interest.

Court cases do not prove guilt or merit. The system records role, court, case number, object, status and latest decision and preserves the presumption of innocence.

Ownership, political influence, conflicts of interest, corruption allegations and criminal allegations require enhanced evidence gates and right of reply.

## 13. Adaptive learning

For each source and topic, track rolling 7/30/180-day metrics:

- first-signal rate;
- confirmation rate;
- false/infirmed rate;
- correction rate;
- duplicate rate;
- average confirmation latency;
- useful-story yield;
- noise rate;
- topic-specific reliability.

These metrics can adjust priority, relevance and crawl frequency. They cannot weaken editorial evidence rules.

## 14. Coverage targets

Initial operational targets:

- Phase 1: 250 sources / ~2,000 monitored URLs;
- Phase 2: 1,000 sources / 15,000–25,000 monitored URLs;
- Phase 3: persistent county-wide Local Intelligence Graph.

Coverage is measured by locality x vertical x source type, not just raw source count.

## 15. Publishing pipeline

Canonical pipeline:

`SIGNAL -> VERIFIED_SIGNAL -> FACT_KERNEL -> STORY_CLUSTER -> STORY_DRAFT -> QA -> PUBLISH -> FOLLOW_UP`

Sensitive investigations insert additional evidence and right-to-reply gates. Crawling, discovery, scoring and clustering may be autonomous; publication remains fail-closed.

## 16. System health

Dashboard must expose:

- source coverage by locality/vertical;
- active/failed/moved sources;
- average crawl latency;
- T1/T1B/T2/T3 distribution;
- unresolved contradictions;
- verification backlog;
- source confirmation rates;
- entity coverage;
- missing expected records;
- crawl cost and rendered-browser share;
- last-known-good age.

## 17. Non-negotiable architecture rule

Everything is adaptive except evidence standards. The system may learn where to look, how often to look and what to prioritize; it may not autonomously redefine what counts as proof.
