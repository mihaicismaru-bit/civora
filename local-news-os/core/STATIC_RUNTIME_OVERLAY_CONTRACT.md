# Static Runtime Overlay Contract

Dynamic newsroom rebuilds may replace the frontpage and individual story routes, but they must not silently remove configured independent static routes.

A production overlay is publishable only when all configured static routes are materialized in the same runtime snapshot before sitemap/robots finalization. Missing configured static routes are a fail-closed condition.

For instances whose dynamic renderer rebuilds the runtime directory from scratch, the overlay may restore an independently maintained static page only from a deterministic source pinned to the same checked-out revision (for example, the committed runtime artifact) or from the deterministic site export. It must not synthesize missing editorial content or weaken the indexing gate.

The final export must include explicit route-manifest entries for independent static pages as well as individual story routes.
