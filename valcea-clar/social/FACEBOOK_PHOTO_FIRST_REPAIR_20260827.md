# VÂLCEA CLAR Facebook photo-first repair — 2026-08-27

Incident: new Facebook link-fallback posts were created before their GitHub Pages story routes were publicly available, so Facebook cached `Page not found · GitHub Pages` previews. The fallback also consumed the canonical story publication key, preventing a later real-photo publication from replacing the broken preview.

Verified repair performed before this note was created:
- `story-auto-bjai-valcea-evenimente-def3753e2a99`: broken fallback post deleted; story returned to HOLD until a validated photograph exists.
- `story-maciuca-ziua-regalitatii-2027-colocviu-bjai-20260827`: broken fallback post deleted; story returned to the normal photo-first queue. Canonical `story_visuals.json` contains the approved public-domain King Michael archival context photograph for this story.

Durable rule in this branch:
- Facebook text+link fallback is disabled by default and requires explicit runtime opt-in plus explicit per-item opt-in.
- Even when explicitly enabled, a fallback must pass live public readback: canonical VÂLCEA CLAR story URL, HTTP 200, no GitHub Pages 404 body, canonical tag, and OpenGraph URL.
- Missing photo therefore holds Facebook publication instead of producing a broken or synthetic preview.

This receipt contains no credentials or private Facebook data beyond the already tracked story identifiers.
