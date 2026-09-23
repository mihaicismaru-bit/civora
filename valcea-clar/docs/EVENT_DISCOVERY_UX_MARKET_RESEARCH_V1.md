# VÂLCEA CLAR — EVENT DISCOVERY UX MARKET RESEARCH v1.0

Date: 2026-09-23
Status: CANONICAL PRODUCT RESEARCH

## Product goal
Turn UNDE IEȘIM from a normal article archive into a local event-discovery utility that helps a reader answer, in seconds:
- What can I do today / this weekend / later?
- Where is it?
- When does it start?
- What kind of event is it?
- How much does it cost?
- Where do I get tickets / reserve?
- Is the information still current?

## Benchmark families
Research model includes event-discovery patterns popularised by:
- Time Out: editorial curation + city discovery + "things to do" intent.
- Songkick: chronological concert discovery, artist/venue/date clarity.
- Resident Advisor: date-led event browsing and strong event metadata.
- Eventbrite: filterable event inventory, date/category/location discovery and conversion.
- iaBilet / ticketing catalogues: Romanian ticket availability, event date, venue, price/conversion expectations.
- premium news benchmarks already canonicalised (WSJ/NYT/Le Monde/FT/DER SPIEGEL): editorial hierarchy, trust, typography, topic/product separation.

This is principles research, not a claim of identical features or an instruction to copy distinctive trade dress.

## High-value UX patterns

### 1. Date is the primary event navigation axis
Readers usually begin with intent, not editorial section:
AZI / MÂINE / WEEKEND / 7 ZILE / LUNA ASTA / MAI TÂRZIU.
Date chips should be visible before category filters.

### 2. Event cards need structured facts
An event discovery card is not a normal news card.
Minimum visible fields when verified:
- date;
- start time;
- event name;
- venue;
- locality;
- category;
- price/free/unknown;
- ticket/access state.

### 3. Conversion must be obvious but not misleading
Use a single clear action:
- BILETE when an official/verified ticket URL exists;
- REZERVĂ when reservation exists;
- DETALII when no direct booking is verified.
Never invent availability or imply tickets remain available without current evidence.

### 4. Filters should reflect real local decisions
Priority filters for Vâlcea:
- Concerte;
- Teatru;
- Stand-up;
- Copii & familie;
- Festivaluri;
- Expoziții;
- Sport;
- Comunitate;
- Gratuit;
- Râmnicu Vâlcea / Brezoi / Călimănești / Horezu / Drăgășani / restul județului.
Do not expose filters with zero current results merely for visual symmetry.

### 5. Chronological grouping beats one long feed
Group event inventory by:
- Azi;
- Mâine;
- Weekend;
- Următoarele 7 zile;
- Octombrie / Noiembrie / Decembrie or subsequent month.
Within a day, sort by start time; unknown-time items follow timed events.

### 6. Editorial curation belongs above inventory
A local newsroom adds value beyond a ticket catalogue:
- 1–3 "Alegerile redacției" when justified;
- "Merită drumul" for county-wide discovery;
- contextual previews;
- reviews/follow-ups after major events;
- public-money context where relevant, without polluting the event card itself.

### 7. Event detail page
Header:
category → event name → date/time → venue/locality → price/access → verified CTA.
Then:
- concise editorial description;
- why it may matter / what to expect;
- exact access/ticket information;
- organiser;
- map/location when verified;
- source freshness / last checked;
- related coverage.
Separate editorial review from organiser claims.

### 8. Freshness is a first-class trust signal
Event facts expire.
Store:
- event_start;
- event_end;
- doors_time when known;
- venue;
- locality;
- price_min/max/currency;
- free flag;
- ticket_url;
- organiser;
- source URL;
- source tier;
- checked_at;
- status: scheduled / changed / cancelled / sold_out / past / unknown.
Past events automatically leave the upcoming inventory but remain in editorial archive.

### 9. Mobile
- horizontal date chips;
- compact filter control;
- cards become one column;
- date block remains highly visible;
- CTA minimum comfortable tap target;
- avoid modal-heavy browsing;
- no forced map before list.

### 10. SEO
Create a durable /unde-iesim/ landing page.
Future extensions only when inventory supports them:
- /unde-iesim/concerte/
- /unde-iesim/teatru/
- locality landing pages.
Event detail pages should use Event structured data only when required facts are verified; do not generate schema from guesses.

## VÂLCEA CLAR canonical interface
Desktop:
1. UNDE IEȘIM mast / short value proposition
2. date chips
3. category chips
4. featured editorial pick(s), optional
5. chronological event agenda
6. upcoming-month sections
7. "Nu găsești evenimentul?" source/tip CTA

Mobile:
1. title + date chips
2. filters
3. chronological cards
4. sticky filter/date affordance where feasible

## Card visual grammar
- date tile at left/top;
- event name as primary headline;
- venue/locality secondary;
- category eyebrow;
- price/access as compact metadata;
- visual optional, never required;
- no editorial/social cartoline as event photography;
- CTA visually distinct but restrained.

## Acceptance
- /unde-iesim/ is not a generic stream page;
- date and category navigation exist;
- event data can be stored separately from article prose;
- no stale/past event in upcoming inventory;
- CTA never implies unverified availability;
- works text-only when no eligible image exists;
- mobile one-column UX;
- site-wide no-cartoline rule remains intact.
