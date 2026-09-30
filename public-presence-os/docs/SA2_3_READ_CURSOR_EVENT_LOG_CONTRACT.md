# S-A2.3 — Incremental Read Cursor + Event Log Contract

Status: SPECIFICATION LOCKED / LOCAL ONLY / LIVE WRITE OFF

This checkpoint defines the persistence-safe boundary that follows S-A2.2 normalized read-only records.

## Contract

Each lane keeps one internal stream keyed by platform + stable account identity. Every accepted normalized record receives a monotonically increasing sequence and deterministic event fingerprint. Replaying the same normalized record is a no-op and increments only the duplicate counter.

The cursor stores only internal stream state: next sequence, last accepted event id, accepted count, duplicate count. It contains no authentication material and no remote pagination token.

The event row stores only S-A2.2 normalized fields and the source-response SHA-256. Missing optional values remain UNKNOWN exactly as supplied by S-A2.2.

## Invariants

- append-only accepted-event order;
- idempotent replay by normalized-record fingerprint;
- exact stream identity match;
- deterministic cursor/event serialization;
- no credentials or authentication material in cursor/event persistence;
- no network execution;
- no public write;
- no deploy;
- global kill switch remains engaged.

## Recovery

Corrupt sequence, stream mismatch, or hash mismatch fails closed. A duplicate record is not an error and does not create a second accepted event.

## Next unit

S-A2.4 — read-observability snapshot compiler over the cursor/event log, with metrics that are unavailable represented as UNKNOWN.
