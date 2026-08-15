# PARTENER.EU — Editorial Automation Contract v1

## 1. Daily Executive Brief — „Ce este nou și ce trebuie făcut acum”

### Product role
Homepage executive briefing. It is not a raw feed and not an independent source of truth.

### Inputs
- `decision_products.json` only for public editorial selection.
- Canonical dossier status, deadline, grant/budget, decision action, programme and verified news.
- MIPE/AFIR/PEO/other ingest influences the brief only after projection into Decision Products.

### Cadence
- Rebuild after every successful `PARTENER.EU Decision Products` workflow.
- Guaranteed daily rebuild by scheduled workflow.
- Maximum 4 cards on homepage.

### Selection rules
1. Material verified news: deadline extension, call opening/closing, guide change, consultation, results.
2. OPEN calls with near deadlines.
3. EXPECTED calls with launch/deadline proximity.
4. PUBLIC_CONSULTATION only as consultation, never OPEN.
5. Diversify programmes when possible.
6. Raw ingestion rows, hash changes and generic source pages are excluded.

### Required card fields
- maturity label;
- programme;
- human headline;
- one-line financial/deadline context;
- explicit `Ce faci acum` action;
- link to canonical dossier/news article.

### QA / fail-closed
- No more than 4 cards.
- No raw dictionaries / JSON.
- No English internal labels.
- No EXPECTED/CONSULTATION item represented as OPEN.
- Every card must lead to an internal dossier/news object or an official source.
- If there are fewer than 4 useful items, show fewer than 4.

## 2. Decision-Maker Intelligence — „Ce spun decidenții”

### Product role
Subsidiary intelligence block near the bottom of homepage. Maximum 3 cards. It must never compete visually with open calls or the daily brief.

### Pipeline
`tracked people registry → official observations → statement signal → corroboration → editorial ranking → homepage card`.

### Core rule
**Statement ≠ administrative fact.** A statement can generate a public signal. A change to status, budget, deadline, eligibility or rules requires T1/T1B administrative evidence before it affects a funding dossier.

### Tracked-person registry
Each record contains:
- stable person ID;
- current displayed name and role;
- institution;
- aliases;
- topics;
- relevance priority;
- active/inactive state.

Role-holder changes must update the registry; historical signals remain attached to the original person ID.

### Observation inputs
Initial v1:
- verified seed observations;
- MIPE observations containing a tracked-person mention;
- Decision Products news containing a tracked-person mention.

Extension path:
- official ministry press-release indexes;
- European Commission / Representation pages;
- ADR leadership statements when funding-relevant;
- official social accounts as discovery only, never as administrative evidence.

### Signal classes
- `FUNDING_COMMITMENT` → public financing/budget signal;
- `PROGRAMME_CHANGE_SIGNAL` → calendar/guide/programme signal;
- `POLICY_SIGNAL` → strategic/policy direction.

### Homepage ranking
1. recency;
2. relevance of office/person;
3. direct funding/calendar impact;
4. source quality;
5. diversity: maximum one homepage signal per person;
6. maximum 3 cards.

### Card design
- photo when a verified source exposes a usable `og:image`;
- initials fallback, never an invented portrait;
- name + role;
- Romanian signal badge;
- concise headline;
- `De ce contează` summary;
- institution + CTA `Vezi analiza`.

### Article structure
- Ce a spus / anunțat;
- Ce putem afirma operațional;
- De ce contează;
- Pe cine poate afecta;
- Ce urmărim mai departe;
- Surse și proveniență.

### QA / fail-closed
- No statement may directly mutate canonical call material facts.
- No operational claim without T1/T1B evidence.
- Photo is optional; invalid/unavailable images fall back to initials.
- No English internal type names in public UI.
- Maximum 3 homepage cards and one per person.

## 3. Engine ownership
Both products are generated and deployed by the PARTENER.EU site engine / GitHub workflows. ChatGPT is not part of the runtime dependency chain.
