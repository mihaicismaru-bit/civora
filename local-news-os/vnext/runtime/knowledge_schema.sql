PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS knowledge_entities (
    instance_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'PERSON','ARTIST','ORGANIZATION','COMPANY','INSTITUTION','EVENT','VENUE','PLACE',
        'PROJECT','PUBLIC_MONEY_ITEM','DOCUMENT','STORY','MEDIA_ASSET'
    )),
    canonical_name TEXT NOT NULL,
    slug TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    attributes_json TEXT NOT NULL DEFAULT '{}',
    evidence_status TEXT NOT NULL CHECK (evidence_status IN ('CANDIDATE','EVIDENCE_BACKED')),
    provenance_json TEXT NOT NULL,
    is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0,1)),
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, entity_id),
    UNIQUE (instance_id, entity_type, slug),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS knowledge_aliases (
    instance_id TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, normalized_alias),
    FOREIGN KEY (instance_id, entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge_edges (
    instance_id TEXT NOT NULL,
    edge_id TEXT NOT NULL,
    subject_entity_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_entity_id TEXT NOT NULL,
    relation_basis TEXT NOT NULL CHECK (relation_basis IN ('DIRECT_EVIDENCE','DOCUMENTED_SOURCE')),
    attributes_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, edge_id),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id, subject_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, object_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS story_entity_links (
    instance_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    role TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, story_id, entity_id, role),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public_money_items (
    instance_id TEXT NOT NULL,
    money_item_id TEXT NOT NULL,
    payer_entity_id TEXT NOT NULL,
    beneficiary_entity_id TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    currency TEXT NOT NULL,
    purpose TEXT NOT NULL,
    project_entity_id TEXT,
    event_entity_id TEXT,
    document_entity_id TEXT,
    story_id TEXT,
    effective_date TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, money_item_id),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id, payer_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, beneficiary_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, project_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, event_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, document_entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS knowledge_timeline_events (
    instance_id TEXT NOT NULL,
    timeline_event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_date TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    story_id TEXT,
    provenance_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, timeline_event_id),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id, entity_id) REFERENCES knowledge_entities(instance_id, entity_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_knowledge_entities_type
    ON knowledge_entities(instance_id, entity_type, is_public, updated_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_entities_name
    ON knowledge_entities(instance_id, canonical_name);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_subject
    ON knowledge_edges(instance_id, subject_entity_id, predicate);
CREATE INDEX IF NOT EXISTS idx_knowledge_edges_object
    ON knowledge_edges(instance_id, object_entity_id, predicate);
CREATE INDEX IF NOT EXISTS idx_story_entity_links_entity
    ON story_entity_links(instance_id, entity_id, created_at);
CREATE INDEX IF NOT EXISTS idx_public_money_payer
    ON public_money_items(instance_id, payer_entity_id, effective_date);
CREATE INDEX IF NOT EXISTS idx_public_money_beneficiary
    ON public_money_items(instance_id, beneficiary_entity_id, effective_date);
CREATE INDEX IF NOT EXISTS idx_knowledge_timeline_entity
    ON knowledge_timeline_events(instance_id, entity_id, event_date DESC);
