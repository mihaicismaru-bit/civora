# S-A2.3 — Incremental Read Cursor + Event Log Contract

Status: IMPLEMENTED / LOCAL ONLY / LIVE WRITE OFF

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

## Implementation

The executable module `src/public_presence_os/meta_read_event_log.py` now provides hash-bound cursors, append-only normalized events, deterministic record fingerprints and idempotent duplicate replay. The cursor advances only after a new accepted event; replay leaves the event set and accepted count unchanged and increments only `duplicate_count`.

## Recovery

Corrupt sequence, stream mismatch, cursor/event hash mismatch, or persisted duplicate events fail closed. A duplicate normalized record is a deterministic no-op and does not create a second accepted event.

## Next unit

S-A2.4 — read-observability snapshot compiler over the cursor/event log, with metrics that are unavailable represented as UNKNOWN.
