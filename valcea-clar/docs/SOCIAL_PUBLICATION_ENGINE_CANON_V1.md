# SOCIAL PUBLICATION ENGINE CANON v1.2

## Mission
VÂLCEA CLAR is the pilot instance of a replicable Local News OS. The website and every social-network page are sibling publications fed by the same verified fact kernel. Social channels are not mirrors of the website and must not be managed as copy-paste distribution endpoints.

## Core principle: one truth layer, multiple independent publications
All channels share the same verified facts, provenance, risk gates, corrections and entity registry. Each channel has its own editorial selection, cadence, native formats, tone, series, publishing state, backlog and performance learning.

The website remains the durable archive and deepest context surface, but a social publication may publish a native, stand-alone item when the facts pass the editorial gates. A site link is optional when native consumption is the better product; it is required when context, evidence or depth cannot be safely carried in-platform.

## Execution ownership rule
All recurring preparation, scheduling, publication, retry, deduplication, correction propagation and publication-state persistence belong exclusively to the CIVORA site engine.

The canonical scheduler and runtime are GitHub Actions workflows registered in `valcea-clar/engine/automation_registry.json`. Channel ownership, adapters, outboxes, credentials references and status are registered in `valcea-clar/social/channel_registry.json`.

ChatGPT is an operator and development console only. It may not:

- own or execute recurring social-publication tasks;
- publish directly or on a schedule to any social network;
- hold platform credentials or canonical publication state;
- replace a missing adapter or credential through a conversational workaround;
- become a dependency whose closure stops publication.

Local cron jobs and GitHub `self-hosted` runners are also forbidden. A missing adapter, credential, visual approval, platform permission, audit or consent blocks that channel fail-closed while every other verified channel continues.

## Publication types
- WEBSITE: full local newsroom, archive, explainers, dossiers, SEO and source notes.
- FACEBOOK: utility-first local publication; explainers, events, civic updates, community conversation and native media.
- INSTAGRAM: visual local publication; real-photo posts, carousels, Reels, Stories, maps/places and event discovery.
- TIKTOK: short-form local publication; photo-mode summaries and short video explainers without synthetic portrayals of real people.
- YOUTUBE / SHORTS: searchable short and evergreen video explainers.
- THREADS: conversational text updates and follow-ups.
- LINKEDIN: selective business, civic, procurement, infrastructure and EU-project publication.
- WHATSAPP / TELEGRAM: concise alerts and digest products.

## Channel independence contract
Every social publication has a CHANNEL_CONFIG defining:

- channel and instance identity;
- audience promise;
- editorial mix and exclusions;
- native formats;
- cadence and quiet hours;
- repetition/fatigue rules;
- media requirements;
- link policy;
- recurring series;
- approval gates;
- credentials reference, never a raw secret;
- publication state and last-known-good;
- observed metrics sources.

No channel may reuse another channel's copy verbatim as its normal production path. The engine generates channel-native packages from the shared STORY_OBJECT / FACT kernel. Historical entries without an explicit `platforms` object remain Facebook-only and are never replayed automatically on newly activated networks.

## Social Publication Engine modules
1. CHANNEL FIT SCORER — determines whether a verified story belongs on each channel.
2. CONTENT ATOMIZER — converts one story into native units without altering facts.
3. HOOK ENGINE — produces clear, non-clickbait hooks optimized for the channel.
4. FORMAT ENGINE — text, single real photo, carousel, reel/short, story sequence, thread, alert or digest.
5. VISUAL ROUTER — selects approved real photographs/video and preserves provenance and credits.
6. CADENCE ENGINE — schedules by freshness, urgency, audience saturation and channel rhythm.
7. SERIES ENGINE — recurring local franchises and recognizable formats.
8. VIRALITY ENGINE — improves discovery and sharing without weakening editorial standards.
9. PUBLISHING ADAPTERS — one verified native/free adapter per active platform.
10. CHANNEL STATE — published IDs, pending IDs, retries, failures, dedupe and last-known-good.
11. PERFORMANCE LEARNING — uses only observed metrics; never invents analytics.
12. CORRECTION PROPAGATION — generates update/correction actions for every affected publication.

## Platform gates

### Facebook
The engine publishes Page photo posts through the Meta Graph API. Eligibility requires a canonical site link and a story-specific real photograph with provenance, rights and editorial approval. The publication ID and replacement cleanup are persisted in `facebook_state.json`.

### Instagram
The engine publishes only to an authorized Instagram professional account. It creates a media container, checks container status and then calls `media_publish`. Media must be a publicly reachable JPEG and all publication identifiers are persisted in `instagram_state.json`.

Missing `VALCEA_IG_ACCOUNT_ID` or `VALCEA_IG_ACCESS_TOKEN` produces a controlled blocked result; it does not create a ChatGPT fallback.

### TikTok
The Content Posting adapter can submit a post only after all of the following are true:

- the account has authorized the app for the required publishing scope;
- the app is approved for public posting;
- fresh creator information and current privacy options have been queried;
- the selected privacy level is one of the returned options;
- media is publicly reachable under the verified `valceaclar.ro` domain;
- the post has explicit consent, actor and timestamp recorded through the `valceaclar.ro` administration surface.

Until every condition is true, the package remains `hold`. The engine may build the package and media projection, but it does not send it, lower the privacy silently or delegate the operation to ChatGPT. Submission IDs, pending status, failures and final post IDs are stored in `tiktok_state.json`.

## Media publication contract
Only approved real media may enter an active adapter. The engine validates:

- photograph/video type;
- absence of synthetic portrayal;
- subject match;
- source and direct source URL where applicable;
- credit and rights basis;
- editor approval;
- local approved-file path and file signature.

For networks that require a verified host, `build_social_media_assets.py` creates a deterministic projection under `https://valceaclar.ro/media/social/` with hash, byte size, credit and rights metadata.

## Virality Engine
Virality is a product objective, not permission to sensationalize. It optimizes story/channel fit, first-frame strength, proximity, useful specificity, save/share value, timing, series continuity, follow-up value and topic-fatigue avoidance.

Forbidden optimization includes fabricated urgency, invented exclusivity, unsupported claims, misleading thumbnails, rage bait, synthetic engagement, fake analytics, harassment or degradation of editorial gates.

## Independent editorial mixes
The same local story may become:

- Website: full verified article and source context.
- Facebook: stand-alone useful explanation plus a relevant community prompt.
- Instagram: a real-photo post or carousel summarizing what changes for residents.
- TikTok: a consented photo-mode summary or short script explaining the practical consequence.
- WhatsApp/Telegram: a concise alert with action, date and location.

This is not duplication; each is a native publication product derived from one evidence base.

## Generic vs local
CORE_GENERIC includes channel schemas, validation, fit scoring, atomization, cadence, visual provenance, state, retry, dedupe and correction propagation.

VALCEA_SPECIFIC includes account/page IDs, local series, local audiences and sources, credentials references, approved media and the verified `valceaclar.ro` media prefix.

A temporary or unavailable platform adapter may produce a durable outbox only. It may never delegate recurring or direct publication to ChatGPT.

## Zero-paid-dependency rule
Normal operation must not require paid LLM APIs, paid schedulers, paid social-management suites or paid hosting APIs. Free/native platform APIs may be used when available and verified. If one platform is unavailable, the engine continues the other channels and records the blocked reason.

## Current pilot
The unified workflow is `.github/workflows/valcea-clar-social-publishing.yml`, running server-side every 15 minutes and on relevant changes. The former standalone Facebook scheduler has been removed.

The active direct-adapter set is:

- Facebook — native Meta API;
- Instagram — native Meta Graph content-publishing flow, fail-closed on missing professional-account credentials;
- TikTok — Content Posting API, fail-closed on missing audit, credentials, verified media or per-post site consent.

The workflow builds channel-native packages, fetches approved photographs, creates public media assets, validates three CHANNEL_CONFIG files, compiles and self-tests every adapter, previews all queues, publishes eligible items outside pull requests, persists state independently and writes an auditable summary.

Threads, LinkedIn, YouTube Shorts, Telegram and WhatsApp remain blocked until verified adapters and credentials exist. They cannot fall back to ChatGPT.

## Acceptance for Social Publication Engine 1.0
PASS requires:

- website plus at least three social publications running from the same verified fact kernel;
- distinct channel-native outputs, not verbatim cross-posting;
- independent channel state and dedupe;
- real-media provenance gates;
- correction propagation;
- observed-metrics learning without fabricated analytics;
- virality tests that do not weaken safety/editorial gates;
- no mandatory paid API/subscription dependency;
- all recurring social execution owned by the CIVORA site engine;
- zero direct or scheduled publication from ChatGPT.
