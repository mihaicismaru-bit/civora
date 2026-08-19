PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS knowledge_entities (
    instance_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'person','artist','organization','company','institution','event','venue','place',
        'project','public_money_item','document','story','media_asset'
    )),
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    slug TEXT NOT NULL,
    external_key TEXT,
    state TEXT NOT NULL CHECK (state IN ('PROVISIONAL','VERIFIED')),
    public_profile_allowed INTEGER NOT NULL DEFAULT 0 CHECK (public_profile_allowed IN (0,1)),
    facts_json TEXT NOT NULL DEFAULT '[]',
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, entity_id),
    UNIQUE (instance_id, entity_type, slug),
    UNIQUE (instance_id, entity_type, external_key),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS knowledge_entity_provenance (
    instance_id TEXT NOT NULL,
    provenance_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    evidence_url TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    observed_at TEXT,
    assertion TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, provenance_id),
    UNIQUE (instance_id, entity_id, evidence_fingerprint, assertion),
    FOREIGN KEY (instance_id, entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS knowledge_aliases (
    instance_id TEXT NOT NULL,
    alias_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    alias_text TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    evidence_url TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, alias_id),
    UNIQUE (instance_id, entity_id, normalized_alias),
    FOREIGN KEY (instance_id, entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS knowledge_edges (
    instance_id TEXT NOT NULL,
    edge_id TEXT NOT NULL,
    from_entity_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    to_entity_id TEXT NOT NULL,
    material INTEGER NOT NULL DEFAULT 1 CHECK (material IN (0,1)),
    public_claim_allowed INTEGER NOT NULL DEFAULT 1 CHECK (public_claim_allowed IN (0,1)),
    assertion_basis TEXT NOT NULL CHECK (assertion_basis = 'DIRECT_EVIDENCE'),
    evidence_url TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    observed_at TEXT,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, edge_id),
    UNIQUE (instance_id, from_entity_id, relationship, to_entity_id, evidence_fingerprint),
    FOREIGN KEY (instance_id, from_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, to_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS knowledge_story_enrichments (
    instance_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    publication_content_fingerprint TEXT NOT NULL,
    story_entity_id TEXT NOT NULL,
    resolved_mentions INTEGER NOT NULL DEFAULT 0,
    unresolved_mentions INTEGER NOT NULL DEFAULT 0,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, story_id, publication_content_fingerprint),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, story_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_entities_type_name
    ON knowledge_entities(instance_id, entity_type, normalized_name);
CREATE INDEX IF NOT EXISTS idx_knowledge_alias_lookup
    ON knowledge_aliases(instance_id, normalized_alias);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_from
    ON knowledge_edges(instance_id, from_entity_id, relationship);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_to
    ON knowledge_edges(instance_id, to_entity_id, relationship);

CREATE TRIGGER IF NOT EXISTS knowledge_entity_provenance_no_update
BEFORE UPDATE ON knowledge_entity_provenance
BEGIN
    SELECT RAISE(ABORT, 'knowledge_entity_provenance is append-only');
END;
CREATE TRIGGER IF NOT EXISTS knowledge_entity_provenance_no_delete
BEFORE DELETE ON knowledge_entity_provenance
BEGIN
    SELECT RAISE(ABORT, 'knowledge_entity_provenance is append-only');
END;
CREATE TRIGGER IF NOT EXISTS knowledge_edges_no_update
BEFORE UPDATE ON knowledge_edges
BEGIN
    SELECT RAISE(ABORT, 'knowledge_edges is append-only');
END;
CREATE TRIGGER IF NOT EXISTS knowledge_edges_no_delete
BEFORE DELETE ON knowledge_edges
BEGIN
    SELECT RAISE(ABORT, 'knowledge_edges is append-only');
END;
