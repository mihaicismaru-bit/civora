# CRAIOVA CLAR

CRAIOVA CLAR is the first greenfield publication built on **CLAR Core**.

The product is the newsroom output, not the framework. The acceptance path is:

`official source -> SourceItem -> FactPacket -> Story -> live site -> Facebook`

## Greenfield rules

- No story-specific hardcoding.
- No Craiova/Dolj conditionals inside `clar_core/`.
- No dependency on an open AI conversation for unattended production.
- Primary sources first; local media may later act as a signal radar.
- One canonical site publisher and, later, one canonical Facebook publisher.
- Real relevant photography preferred; no unrelated fallback image.
- Add a new source vertical only after the previous vertical produces a real end-to-end result.

## Legacy reuse policy

The existing `valcea-clar/` and `local-news-os/` trees remain reference implementations. Code is copied or adapted into CLAR Core only when it directly shortens the end-to-end path and can be expressed generically. No legacy workflow/state-machine architecture is inherited by default.
