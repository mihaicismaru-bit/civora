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

CREATE TABLE IF NOT EXISTS primary_targets (
    instance_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    source_id TEXT,
    url TEXT NOT NULL,
    intended_role TEXT NOT NULL CHECK (intended_role = 'PRIMARY'),
    origin TEXT NOT NULL CHECK (origin IN ('SOURCE_PACK', 'DYNAMIC_DISCOVERY')),
    status TEXT NOT NULL CHECK (status IN ('CANDIDATE', 'VALIDATED', 'DISABLED')),
    authority_class TEXT NOT NULL,
    match_terms_json TEXT NOT NULL DEFAULT '[]',
    claim_kinds_json TEXT NOT NULL DEFAULT '[]',
    confidence INTEGER NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
    publication_authority TEXT NOT NULL CHECK (publication_authority = 'NONE'),
    validation_evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, target_id),
    UNIQUE (instance_id, url),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS verification_tasks (
    instance_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    claim_kind TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    entity_context TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL CHECK (state IN ('PENDING', 'TARGETS_READY', 'NEEDS_DISCOVERY')),
    required_role TEXT NOT NULL CHECK (required_role = 'PRIMARY'),
    discovery_request_json TEXT NOT NULL DEFAULT '{}',
    publication_authority TEXT NOT NULL CHECK (publication_authority = 'NONE'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, task_id),
    UNIQUE (instance_id, signal_id, claim_key),
    FOREIGN KEY (instance_id, signal_id) REFERENCES signals(instance_id, signal_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS verification_task_targets (
    instance_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    match_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, task_id, target_id),
    FOREIGN KEY (instance_id, task_id) REFERENCES verification_tasks(instance_id, task_id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id, target_id) REFERENCES primary_targets(instance_id, target_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS verification_results (
    instance_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('SUPPORTS', 'CONTRADICTS', 'INCONCLUSIVE')),
    evidence_url TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    normalized_claim_json TEXT NOT NULL DEFAULT '{}',
    confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    source_observed_at TEXT,
    publication_authority TEXT NOT NULL CHECK (publication_authority = 'NONE'),
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, result_id),
    UNIQUE (instance_id, task_id, target_id, evidence_fingerprint, verdict),
    FOREIGN KEY (instance_id, task_id) REFERENCES verification_tasks(instance_id, task_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, target_id) REFERENCES primary_targets(instance_id, target_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, signal_id) REFERENCES signals(instance_id, signal_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS fact_kernels (
    instance_id TEXT NOT NULL,
    kernel_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state = 'READY'),
    material_fact_ready INTEGER NOT NULL CHECK (material_fact_ready = 1),
    fact_kernel_ready INTEGER NOT NULL CHECK (fact_kernel_ready = 1),
    publication_authority TEXT NOT NULL CHECK (publication_authority = 'NONE'),
    facts_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, kernel_id),
    UNIQUE (instance_id, signal_id),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id, signal_id) REFERENCES signals(instance_id, signal_id) ON DELETE RESTRICT,
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

CREATE TABLE IF NOT EXISTS story_drafts (
    instance_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    kernel_id TEXT NOT NULL,
    newsworthiness_event_id INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    state TEXT NOT NULL CHECK (state = 'DRAFTED'),
    headline TEXT NOT NULL,
    dek TEXT NOT NULL,
    body_blocks_json TEXT NOT NULL,
    factbox_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    source_references_json TEXT NOT NULL,
    follow_up_json TEXT NOT NULL,
    section TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    entity_bindings_json TEXT NOT NULL DEFAULT '[]',
    publication_authority TEXT NOT NULL CHECK (publication_authority = 'NONE'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, story_id),
    UNIQUE (instance_id, kernel_id),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, kernel_id) REFERENCES fact_kernels(instance_id, kernel_id) ON DELETE RESTRICT,
    FOREIGN KEY (newsworthiness_event_id) REFERENCES runtime_events(event_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS editorial_qa_decisions (
    instance_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    draft_fingerprint TEXT NOT NULL,
    draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
    decision_fingerprint TEXT NOT NULL,
    editorial_class TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('QA_PASSED', 'HUMAN_REVIEW', 'HOLD')),
    gates_json TEXT NOT NULL,
    duplicate_story_id TEXT,
    publication_authority TEXT NOT NULL CHECK (publication_authority = 'NONE'),
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, decision_id),
    UNIQUE (instance_id, story_id, draft_fingerprint, decision_fingerprint),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, duplicate_story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
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
CREATE INDEX IF NOT EXISTS idx_verification_tasks_state
    ON verification_tasks(instance_id, state, updated_at);
CREATE INDEX IF NOT EXISTS idx_verification_tasks_signal
    ON verification_tasks(instance_id, signal_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_primary_targets_status
    ON primary_targets(instance_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_verification_results_signal
    ON verification_results(instance_id, signal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_verification_results_task
    ON verification_results(instance_id, task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_fact_kernels_signal
    ON fact_kernels(instance_id, signal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_story_drafts_kernel
    ON story_drafts(instance_id, kernel_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_editorial_qa_story
    ON editorial_qa_decisions(instance_id, story_id, created_at);
CREATE INDEX IF NOT EXISTS idx_editorial_qa_outcome
    ON editorial_qa_decisions(instance_id, outcome, created_at);

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
