# Architecture and gates

1. The authenticated browser remains the MySMIS authentication boundary.
2. The content script serializes artifact-bearing DOM elements only and performs no click.
3. Core discovery inventories all exposed candidates and blocks write-intent controls.
4. The background worker observes browser-created downloads and response metadata. It never asks
   for request headers and persists no Authorization or Cookie material.
5. Acquisition chooses the least invasive viable strategy: safe direct binary URL, browser download
   observation, proven read-only UI download, route metadata, manual intake, then optional CDP.
6. POST and ambiguous actions fail closed. CDP and automated traversal remain disabled until the
   persisted authorization/compliance gate explicitly permits them.
7. A later native agent must hash bytes, validate MIME/magic/size, spool restart-safely, upload to
   Drive, read back, then append the Artifact Registry and the correct branch SSOT.

No project code appears in the discovery implementation. Project numbers occur only in fixtures and
acceptance evidence.
