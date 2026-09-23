# VÂLCEA CLAR — LOCAL LIFE UX & MARKET INTELLIGENCE v1.0

Date: 2026-09-23
Status: CANONICAL PRODUCT RESEARCH

## Scope
Local-life products are distinct reader intents and should not be flattened into one generic event list:
1. Events
2. Sport / important matches
3. Cinema
4. Restaurants
5. Meniul zilei
6. Fitness

## UX benchmark synthesis

### Events
Patterns from Eventbrite / Songkick / Time Out style discovery:
- date-first browsing;
- category + location filters;
- structured date/time/venue/price/access;
- one explicit ticket/details CTA;
- upcoming only; expired inventory leaves discovery automatically.

### Sport
Schedule products (ESPN/SofaScore-style pattern) are not ordinary event cards:
- date + competition + home/away teams;
- venue;
- status: scheduled/live/final/postponed;
- score only after verified;
- team/competition filters;
- important/local-interest games promoted, not every low-signal fixture.
For Vâlcea: prioritise SCM football, SCM handball, finals/derbies/cups and major county competitions.

### Cinema
Cinemagia / cinema-program pattern:
- day tabs first;
- film as primary entity;
- showtimes grouped by cinema;
- format/language tags (2D/3D, DUB/SUB);
- price/ticket CTA only when verified;
- daily refresh because schedules change quickly.

### Restaurants
Eater-style editorial guide:
- curated directory, not an automated ranking;
- neighbourhood/locality, cuisine, price band and practical details;
- editorial lists should be explicitly curated and frequently updated;
- avoid converting third-party star ratings into VÂLCEA CLAR verdicts.
Restaurant directory is stable and can be scanned less frequently than daily-menu inventory.

### Meniul zilei
Daily menu is a separate high-frequency utility product:
- restaurant;
- today's date;
- dishes or package composition;
- price;
- serving interval;
- order/pick-up/delivery link/phone when verified;
- checked_at visible;
- stale entries disappear at end of day.
Benchmark pattern from Romanian daily-menu sites: users value price + dishes + availability hours above prose.

### Fitness
ClassPass / Mindbody pattern:
- activity/type;
- location;
- schedule/time;
- amenities only when verified;
- classes and availability separated from static gym directory.
For Vâlcea v1: start with venue directory + hours; add class schedules where sources are stable.

## Product architecture

Primary navigation stays simple:
ACASĂ / ULTIMELE / editorial products / UNDE IEȘIM / DESPRE

UNDE IEȘIM becomes LOCAL LIFE HUB with subnavigation:
- Evenimente
- Sport
- Cinema
- Restaurante
- Meniul zilei
- Fitness

Canonical routes:
- /unde-iesim/
- /unde-iesim/sport/
- /unde-iesim/cinema/
- /unde-iesim/restaurante/
- /unde-iesim/meniul-zilei/
- /unde-iesim/fitness/

## Homepage
Replace tall event-only block with compact "VÂLCEA, ÎN ORAȘ" intelligence strip/grid.
Each tile answers one intent:
- următorul eveniment;
- următorul meci important;
- cinema azi;
- meniul zilei;
- restaurante;
- fitness.
Maximum 6 compact tiles; no long vertical agenda on homepage.

## Scan cadence

### Events
hourly delta + 72h hot watch; daily 90-day sweep; weekly long horizon.

### Sport
- stable season schedules: deep scan daily or on source delta;
- next 14 days: reconfirm daily;
- <=48h before match: hot watch for time/venue/postponement;
- results: verify after scheduled end before publishing score.

### Cinema
- one full scan each morning after 06:30;
- second delta scan around 12:00 when schedule pages change;
- hot update only on cancellation/program change.
No hourly full recrawl.

### Restaurants
- stable directory deep scan weekly;
- source delta when opening/closing/hours changes;
- editorial guide review monthly or on meaningful new opening/closure.
No hourly full scan.

### Meniul zilei
- weekdays only;
- first sweep after 07:30;
- second sweep after 10:30 for late-posting restaurants;
- optional delta check at 12:00;
- no further scan if same source fingerprint and availability window already verified;
- expire daily entries automatically at local midnight/end of service.

### Fitness
- directory + hours: weekly;
- class schedules: daily only for sources that publish structured schedules;
- promotions are not editorial recommendations.

## Trust / freshness
Every local-life record should carry:
source_url, source_tier, checked_at, status and stable entity_id/fingerprint.
No price, ticket availability, opening status or class availability is inferred.
Stale daily-menu and cinema rows fail closed.

## Current Vâlcea source intelligence
Cinema:
- Cinema Geo Saizescu official site
- Cinemagia / Orange cinema programme
- Cinema City / Shopping City public programme

Sport:
- SCM Râmnicu Vâlcea football official programme
- SCM Râmnicu Vâlcea handball official competitive programme
- AJF Vâlcea

Restaurants / daily menu:
- direct restaurant sites when available
- Wolt/Glovo menu pages as current commercial evidence
- PapaDream local menu aggregation as discovery, then corroborate where possible

Fitness:
- official gym sites/social schedules where available
- local business listings only as discovery/secondary evidence

## Acceptance
- homepage local-life module is compact and dense;
- no excessive whitespace;
- separate pages by intent;
- daily menu has same-day freshness gate;
- cinema has date/showtime grammar;
- sport has match grammar;
- restaurant guide never presents automated ratings as VÂLCEA CLAR editorial ranking;
- fitness page separates stable venue data from dynamic class schedules;
- all new routes enter sitemap;
- build/QA/deploy/readback pass.
