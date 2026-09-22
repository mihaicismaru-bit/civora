# VÂLCEA CLAR — S7 Production Loop Observation

S7 is **not a seventh formal development stage in the 22 September roadmap**. The source plan ends with exploitation validation: three complete editions and seven days of real operation. S7 is the operational extension used to run and observe that requirement.

## What S7 does

S7 uses the already-canonical production chain:

`sources/signals → fact kernel → editorial writer/integrity → canonical story → S3 visuals → S4/S5 reader experience → social → S1 delivery reconciliation → S6 governance`.

It does not own publishing and does not add a scheduler. Live Newsroom remains the canonical writer and its existing event-driven / five-minute recovery cadence remains unchanged.

## Observation ledger

`ops/production_cycles.json` records deliberate production cycles and material publication/update cycles. Routine polling with no editorial change is not journalled, preventing a five-minute heartbeat from masquerading as editorial evidence.

Each recorded cycle captures:
- discovery coverage and source health;
- newsroom decision and writer/integrity results;
- publication event proof when content changed;
- S1 delivery state;
- S3 visual state;
- S4/S5 reader experience;
- corrections;
- S6 governance blockers/warnings.

## Formal validation boundary

The ledger deliberately keeps `formal_validation_complete=false` until there is real evidence across the required calendar period. A single successful technical run cannot satisfy the source plan's requirement for three complete editions and seven days of operation.

S7 therefore has two different states:
- **OPERATIONAL** — the production loop has been run end-to-end and can be repeated;
- **FORMALLY VALIDATED** — only after the original exploitation-validation evidence exists.
