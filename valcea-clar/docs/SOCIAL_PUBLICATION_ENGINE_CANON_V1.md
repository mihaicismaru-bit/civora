# SOCIAL PUBLICATION ENGINE CANON v1.1

## Mission
VÂLCEA CLAR is the pilot instance of a replicable Local News OS. The website and every social-network page are sibling publications fed by the same verified fact kernel. Social channels are not mirrors of the website and must not be managed as copy-paste distribution endpoints.

## Core principle: one truth layer, multiple independent publications
All channels share the same verified facts, provenance, risk gates, corrections and entity registry. Each channel has its own editorial selection, cadence, native formats, tone, series, publishing state, backlog and performance learning.

The website remains the durable archive and deepest context surface, but a social publication may publish a native, stand-alone item when the facts pass the editorial gates. A site link is optional when native consumption is the better product; it is required when context, evidence or depth cannot be safely carried in-platform.

## Execution ownership
The CIVORA site engine is the only production owner for social publication. Scheduling, channel-native package generation, media validation, API calls, retry, deduplication, status polling and publication ledgers run in GitHub Actions and persist in the repository.

ChatGPT is an operator/development console only. It must never be:
- a social scheduler or recurring publishing task;
- the runtime that sends a post;
- the only storage location for a token, outbox, checkpoint or platform post ID;
- the place where a TikTok creator grants required publishing consent;
- a replacement for an official platform publishing adapter.

Local cron jobs and self-hosted runners are also forbidden. Platform credentials exist only as GitHub Actions secrets or variables. The machine-readable contract is `social/social_channels.json`; the scheduler is `.github/workflows/valcea-clar-social.yml`.

## Publication types
- WEBSITE: full local newsroom, archive, explainers, dossiers, SEO, source notes.
- FACEBOOK: utility-first local publication; service journalism, explainers, events, civic updates, community conversation, native photo/video and follow-up posts.
- INSTAGRAM: visual local publication; real-photo posts, carousels, Reels, Stories, maps/places, event discovery and strong visual continuity.
- TIKTOK: short-form local publication; photo posts and short video explainers, location-based updates, event/service hooks, recurring vertical formats and reporter-style scripts without synthetic portrayals of real people.
- YOUTUBE / SHORTS: searchable video publication; short bulletins plus evergreen explainers and recurring local series.
- THREADS: conversational text publication; concise local updates, live/context threads and follow-ups where operationally useful.
- LINKEDIN: selective business/civic publication; local economy, administration, procurement, infrastructure, EU projects and public-money explainers.
- WHATSAPP / TELEGRAM: alert and digest publication; concise service information, breaking verified updates and daily/weekly digest products.

## Channel independence contract
Every social publication has a CHANNEL_CONFIG defining:
- channel_id and instance_id
- audience promise
- editorial mix and exclusions
- native formats
- cadence and quiet hours
- maximum repetition/fatigue rules
- image/video requirements
- call-to-action policy
- link policy
- series/templates
- approval gates
- credentials reference (never raw secret in repository)
- publication state and last-known-good
- metrics available from native/free interfaces

No channel may reuse another channel's copy verbatim as its normal production path. The engine generates or composes channel-native packages from the shared STORY_OBJECT / FACT kernel. Legacy outbox entries without platform routing remain limited to their original channel and are not replayed automatically on newly activated networks.

## Social Publication Engine modules
1. CHANNEL FIT SCORER — determines whether a verified story belongs on each channel.
2. CONTENT ATOMIZER — converts one story into usable native units without altering facts.
3. HOOK ENGINE — produces clear, non-clickbait hooks optimized for the channel.
4. FORMAT ENGINE — text, single real photo, carousel, reel/short script, story sequence, thread, alert, digest.
5. VISUAL ROUTER — selects only approved real photographs/video and preserves provenance and credits.
6. CADENCE ENGINE — schedules by freshness, urgency, audience saturation and channel rhythm.
7. SERIES ENGINE — recurring local franchises and recognizable formats.
8. VIRALITY ENGINE — improves discovery and sharing without weakening editorial standards.
9. PUBLISHING ADAPTERS — one adapter per platform; direct native/free APIs where available, otherwise durable outbox packages until a verified connector exists.
10. CHANNEL STATE — published IDs, retries, failures, dedupe, last-known-good and rollback.
11. PERFORMANCE LEARNING — uses only observed metrics; never invents analytics.
12. CORRECTION PROPAGATION — a corrected fact/story generates correction/update actions for every affected publication.

## Platform gates

### Facebook
The engine publishes Page photo posts through the Meta Graph API. A post is eligible only when its story-specific photograph is real, rights-documented, editor-approved and available in the approved media store. The publication ID and replacement cleanup are persisted in `facebook_state.json`.

### Instagram
The engine creates a media container, waits for a publishable status and calls `media_publish`. The account must be an authorized Instagram professional account, the asset must be a publicly reachable JPEG, and the required Meta content-publishing permissions must be present. State and deduplication are isolated in `instagram_state.json`.

### TikTok
The engine may use Direct Post only after:
- the account has authorized the app for the required publishing scope;
- fresh creator information and current privacy options have been queried;
- the chosen privacy option matches the returned choices;
- the media URL is public under the verified `valceaclar.ro` domain;
- the app has passed the required audit for public visibility;
- explicit per-post consent, actor and timestamp are recorded through the valceaclar.ro administration surface.

Until every condition is true, the package remains `hold`; it is not sent by ChatGPT and is not silently downgraded into an unauthorized workaround. Submission IDs, pending status, failures and final post IDs are stored in `tiktok_state.json`.

## Virality Engine
Virality is a product objective, not a permission to sensationalize. It optimizes:
- story/channel fit
- first-frame or first-line strength
- local relevance and proximity
- useful specificity
- shareability and saveability
- timing
- repeatable series
- follow-up value
- conversation prompts that do not manufacture outrage
- topic fatigue and repetition avoidance
- resurfacing of evergreen local utility
- event lifecycle coverage: announcement -> reminder -> live/service -> result -> aftermath
- breaking-news lifecycle: alert -> verified update -> explainer -> consequences
- cross-channel handoff when a story performs naturally on another format

Forbidden optimization: fabricated urgency, invented exclusivity, unsupported claims, misleading thumbnails, rage bait, synthetic engagement, fake analytics, harassment, or degrading editorial gates.

## Independent editorial mixes
The same local story may have different treatments:
- Website: full verified article and source context.
- Facebook: stand-alone useful explanation plus community-relevant question when appropriate.
- Instagram: real-photo post or carousel summarizing what changes for residents.
- TikTok/Shorts: photo-mode summary or 20–60s script explaining the essential consequence or event utility.
- WhatsApp/Telegram: one-paragraph alert with action/date/location.

This is not duplication; each is a native publication product derived from one evidence base.

## Generic vs local
CORE_GENERIC:
- channel schemas
- fit scoring
- atomization
- hook/format/cadence/series/virality engines
- visual provenance rules
- publication state, retry, dedupe and correction propagation
- metrics schema and learning loop

LOCAL_TEMPLATE:
- recommended channel mix
- default series library
- local service/event/civic/sport/business templates

VALCEA_SPECIFIC:
- account/page IDs and handles
- local series names when brand-specific
- local audiences, events, venues and source references
- credentials refs
- the verified social-media URL prefix on valceaclar.ro

TEMPORARY_ADAPTER:
- any manual or quota-gated publishing surface
- platform-specific workaround that cannot be generalized

## Zero-paid-dependency rule
Normal operation must not require paid LLM APIs, paid content APIs, paid schedulers, paid social-management suites or paid hosting APIs. Free/native platform APIs may be used when available and verified. If a platform cannot be published to automatically without paid infrastructure or without its required approval, the system must still generate a durable channel-native outbox package and continue all other channels.

## Current pilot
The unified `VÂLCEA CLAR Social Distribution Engine` owns Facebook, Instagram and TikTok routing. It runs every 15 minutes in GitHub Actions, builds channel-native packages from the current verified edition, fetches approved real photographs, validates all adapters, publishes eligible items, persists independent platform state and produces an auditable summary.

Facebook is active when its Page token is valid. Instagram is engine-ready and activates with the professional-account ID and authorized content-publishing token. TikTok is engine-ready but remains fail-closed until app audit, token, verified media domain and site-admin consent are complete.

## Acceptance for Social Publication Engine 1.0
PASS requires:
- website + at least three social publications running from the same verified fact kernel
- distinct channel-native outputs, not verbatim cross-posting
- independent channel state and dedupe
- real-photo provenance gates
- correction propagation
- observed-metrics learning without fabricated analytics
- virality tests that do not weaken safety/editorial gates
- instance isolation test with a second local-news fixture
- no mandatory paid API/subscription dependency
- no recurring ChatGPT or local runtime dependency
