PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS publication_instances (
    instance_id TEXT PRIMARY KEY,
    canonical_domain TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    runtime_owner TEXT NOT NULL CHECK (runtime_owner = 'site_application'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stories (
    instance_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    headline TEXT,
    canonical_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, story_id),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS signals (
    instance_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_role TEXT NOT NULL CHECK (source_role IN ('DISCOVERY', 'PRIMARY', 'BOTH')),
    source_item_fingerprint TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_published_at TEXT,
    state TEXT NOT NULL CHECK (state = 'DISCOVERED'),
    publication_authority TEXT NOT NULL CHECK (publication_authority = 'NONE'),
    material_fact_ready INTEGER NOT NULL DEFAULT 0 CHECK (material_fact_ready = 0),
    fact_kernel_ready INTEGER NOT NULL DEFAULT 0 CHECK (fact_kernel_ready = 0),
    claim_hints_json TEXT NOT NULL DEFAULT '[]',
    entity_hints_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, signal_id),
    UNIQUE (instance_id, fingerprint),
    UNIQUE (instance_id, source_id, source_item_fingerprint),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS runtime_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    reason TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    engine_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_runtime_events_aggregate
    ON runtime_events(instance_id, aggregate_type, aggregate_id, event_id);

CREATE INDEX IF NOT EXISTS idx_stories_state
    ON stories(instance_id, state, updated_at);

CREATE INDEX IF NOT EXISTS idx_signals_state
    ON signals(instance_id, state, updated_at);

CREATE INDEX IF NOT EXISTS idx_signals_source
    ON signals(instance_id, source_id, updated_at);

CREATE TRIGGER IF NOT EXISTS runtime_events_no_update
BEFORE UPDATE ON runtime_events
BEGIN
    SELECT RAISE(ABORT, 'runtime_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS runtime_events_no_delete
BEFORE DELETE ON runtime_events
BEGIN
    SELECT RAISE(ABORT, 'runtime_events is append-only');
END;
