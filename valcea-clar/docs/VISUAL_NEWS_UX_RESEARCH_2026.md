# VÂLCEA CLAR — VISUAL NEWS UX RESEARCH 2026

Date: 2026-09-22
Status: CANONICAL_RESEARCH_BASELINE
Benchmarks reviewed live: WSJ, NYT, Le Monde, Financial Times, DER SPIEGEL.

## Current audience/product signals
- News discovery continues shifting toward social/video/platform surfaces; direct news-site use is comparatively more valuable because it carries trust, habit and brand identity.
- Smartphone-first behavior is now the dominant baseline for most non-legacy audiences.
- The role of the owned site is therefore not to imitate a social feed; it should provide clarity, hierarchy, context, trust and durable navigation.

## Visual patterns shared by strong news products

### 1. Editorial hierarchy before component chrome
Strong news sites rely on scale, typography, whitespace, rules and alignment rather than boxed cards everywhere.
Recommendation: VÂLCEA CLAR should feel like a digital newspaper, not a SaaS dashboard.

### 2. Two-font logic without brand-copying
- high-contrast serif/display voice for headlines and longform;
- neutral sans-serif for navigation, metadata, labels and utility.
Use system/native stacks to avoid performance/font-loading dependency.

### 3. Restrained palette
- near-black text;
- warm paper/off-white background;
- one editorial accent;
- muted greys for metadata.
Avoid multiple decorative colors and gradients in news surfaces.

### 4. Asymmetric lead composition
The lead should visually dominate with a larger headline/image plane and a tighter supporting rail.
Do not make every story card equal.

### 5. Image discipline
Large imagery only when real/relevant.
Text-only stories are valid.
No placeholder/editorial-card imagery on the site merely to preserve symmetry.

### 6. Compact navigation + sticky behavior
Desktop: masthead + two editorial rows.
Mobile: compact/sticky header with horizontal scroll for products/topics.
Avoid giant hamburger-only navigation when the core sections fit visibly.

### 7. Trust metadata is visual, not buried
Product type, section, byline, published/updated state, reading time, image credit and sources should be visible but quiet.

### 8. Article reading surface
- narrow readable measure;
- 18–20px body copy on desktop, ~18px mobile;
- generous line-height;
- strong headline/deck separation;
- no decorative clutter around paragraphs.

### 9. Section separators instead of cards
Use thin rules, typographic groupings and spacing.
Reserve background panels for special utility/explainer contexts.

### 10. Responsive editorial density
Desktop may be dense but organized.
Mobile should reduce simultaneous columns, increase tap targets and preserve hierarchy.

## VÂLCEA CLAR visual direction

### Identity
- warm paper background, white/near-white article surfaces;
- near-black ink;
- deep wine-red editorial accent;
- strong serif headline stack: Iowan Old Style / Charter / Georgia fallbacks;
- system sans UI stack;
- zero external font dependency.

### Homepage
- larger masthead with tighter vertical footprint;
- sticky two-level navigation;
- lead grid ~2:1 with clear supporting rail;
- news strips become flat editorial rows, not cards;
- section titles larger and cleaner;
- product tiles restrained with typography/rules, not bordered boxes;
- subtle alternating section rhythm only where it helps scanability.

### Article
- stronger headline/deck contrast;
- visible reading-time and publication metadata;
- image credit visually separated from body;
- body max measure ~720–760px;
- sources/related modules visually quieter but clear;
- product type expressed through small typographic accents, not themed page colors.

### Mobile
- brand remains visible;
- nav scrolls horizontally;
- no horizontal body overflow;
- one-column story stream;
- hero image may bleed to viewport edges only on article/home lead, not every card;
- large tap targets.

## Avoid
- glassmorphism;
- gradients as decorative filler;
- excessive rounded cards;
- app-dashboard iconography;
- large drop shadows;
- animated UI that competes with reading;
- generic stock-image density;
- visually encoding editorial confidence by arbitrary color.

## Acceptance
Theme refresh is complete only when:
- existing content hierarchy remains readable without JS;
- mobile is coherent at <=620px;
- no card-placeholder regression;
- canonical navigation and sitemap routes remain unchanged;
- article metadata/source/related-story contracts survive;
- build, verifier and live readback pass.
