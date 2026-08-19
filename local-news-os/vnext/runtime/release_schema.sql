PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS release_candidates (
    instance_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    code_sha TEXT NOT NULL,
    artifact_fingerprint TEXT NOT NULL,
    schema_fingerprint TEXT NOT NULL,
    migration_fingerprint TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('CANDIDATE','VALIDATED','REJECTED','PROMOTED')),
    rejection_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, candidate_id),
    UNIQUE (instance_id, engine_version, artifact_fingerprint),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS release_state (
    instance_id TEXT PRIMARY KEY,
    current_candidate_id TEXT,
    current_engine_version TEXT NOT NULL,
    current_artifact_fingerprint TEXT NOT NULL DEFAULT '',
    previous_candidate_id TEXT,
    previous_engine_version TEXT,
    previous_artifact_fingerprint TEXT NOT NULL DEFAULT '',
    generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS release_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('REGISTER','VALIDATE','REJECT','PROMOTE','ROLLBACK')),
    candidate_id TEXT,
    from_engine_version TEXT,
    to_engine_version TEXT,
    artifact_fingerprint TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_release_candidates_status
  ON release_candidates(instance_id,status,updated_at);
CREATE INDEX IF NOT EXISTS idx_release_history_instance
  ON release_history(instance_id,history_id);

CREATE TRIGGER IF NOT EXISTS release_history_no_update
BEFORE UPDATE ON release_history
BEGIN
  SELECT RAISE(ABORT, 'release_history is append-only');
END;
CREATE TRIGGER IF NOT EXISTS release_history_no_delete
BEFORE DELETE ON release_history
BEGIN
  SELECT RAISE(ABORT, 'release_history is append-only');
END;
