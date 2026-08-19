PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS scheduler_leases (
    instance_id TEXT PRIMARY KEY,
    lease_token TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS scheduler_jobs (
    instance_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    stage TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    desired_fingerprint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('PENDING','RUNNING','RETRY','DONE','NEEDS_ATTENTION','CANCELLED')),
    priority INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
    next_attempt_at TEXT NOT NULL,
    lease_token TEXT,
    tick_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (instance_id, job_id),
    UNIQUE (instance_id, dedupe_key),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS scheduler_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    tick_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('DONE','RETRY','NEEDS_ATTENTION','CANCELLED')),
    error_text TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    FOREIGN KEY (instance_id, job_id) REFERENCES scheduler_jobs(instance_id, job_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS scheduler_ticks (
    instance_id TEXT NOT NULL,
    tick_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','PASS','PARTIAL','FAILED','LEASE_BUSY')),
    discovered_jobs INTEGER NOT NULL DEFAULT 0,
    claimed_jobs INTEGER NOT NULL DEFAULT 0,
    completed_jobs INTEGER NOT NULL DEFAULT 0,
    retry_jobs INTEGER NOT NULL DEFAULT 0,
    needs_attention_jobs INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (instance_id, tick_id),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS scheduler_cursors (
    instance_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    cursor_value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, stage),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS scheduler_health (
    health_id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OK','DEGRADED','BLOCKED')),
    observed_at TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_due
    ON scheduler_jobs(instance_id, status, next_attempt_at, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_aggregate
    ON scheduler_jobs(instance_id, aggregate_type, aggregate_id, stage);
CREATE INDEX IF NOT EXISTS idx_scheduler_attempts_job
    ON scheduler_attempts(instance_id, job_id, attempt_id);
CREATE INDEX IF NOT EXISTS idx_scheduler_health_component
    ON scheduler_health(instance_id, component, health_id);

CREATE TRIGGER IF NOT EXISTS scheduler_attempts_no_update
BEFORE UPDATE ON scheduler_attempts
BEGIN
    SELECT RAISE(ABORT, 'scheduler_attempts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS scheduler_attempts_no_delete
BEFORE DELETE ON scheduler_attempts
BEGIN
    SELECT RAISE(ABORT, 'scheduler_attempts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS scheduler_health_no_update
BEFORE UPDATE ON scheduler_health
BEGIN
    SELECT RAISE(ABORT, 'scheduler_health is append-only');
END;

CREATE TRIGGER IF NOT EXISTS scheduler_health_no_delete
BEFORE DELETE ON scheduler_health
BEGIN
    SELECT RAISE(ABORT, 'scheduler_health is append-only');
END;
