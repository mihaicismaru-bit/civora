# Signal routing recovery — 2026-08-18

## Incident
At 14:01 Europe/Bucharest, the VÂLCEA CLAR signal layer had 65 pending primary-verification tasks but zero primary matches. A concrete routing defect was identified: `urs` matched the substring inside `concurs`, sending an APAVIL recruitment signal to the fire/rescue route.

## Recovery
- exact phrase/word matching is now the default;
- prefix matching is explicit with a trailing `*`;
- instance config may require any/all entity keywords before a route is selected;
- dedicated evidence-only primary targets can be registered without making them news sources;
- APAVIL hiring and CAS Vâlcea have dedicated T1 verification targets;
- regression cases protect APAVIL `concurs`, real `urs` alerts, and CJAS health-insurance routing.

## Safety
Signal routing and primary verification retain `publication_authority: NONE`. A primary match is still not a Fact Kernel and cannot publish directly. Strict publication-time and event-title corroboration remain mandatory before the next structured-fact gate.
