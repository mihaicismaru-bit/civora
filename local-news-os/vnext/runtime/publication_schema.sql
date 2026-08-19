PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS story_publications (
    instance_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    canonical_path TEXT NOT NULL,
    current_revision INTEGER NOT NULL DEFAULT 1 CHECK (current_revision >= 1),
    current_content_fingerprint TEXT NOT NULL,
    published_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, story_id),
    UNIQUE (instance_id, publication_id),
    UNIQUE (instance_id, canonical_path),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS publication_revisions (
    instance_id TEXT NOT NULL,
    publication_revision_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    qa_decision_id TEXT NOT NULL,
    draft_fingerprint TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, publication_revision_id),
    UNIQUE (instance_id, publication_id, revision),
    UNIQUE (instance_id, story_id, content_fingerprint),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, qa_decision_id) REFERENCES editorial_qa_decisions(instance_id, decision_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, publication_id) REFERENCES story_publications(instance_id, publication_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_story_publications_recent
    ON story_publications(instance_id, published_at DESC, story_id);
CREATE INDEX IF NOT EXISTS idx_publication_revisions_story
    ON publication_revisions(instance_id, story_id, revision DESC);

CREATE TRIGGER IF NOT EXISTS publication_revisions_no_update
BEFORE UPDATE ON publication_revisions
BEGIN
    SELECT RAISE(ABORT, 'publication_revisions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS publication_revisions_no_delete
BEFORE DELETE ON publication_revisions
BEGIN
    SELECT RAISE(ABORT, 'publication_revisions is append-only');
END;
