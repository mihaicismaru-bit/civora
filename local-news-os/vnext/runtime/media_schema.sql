PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS media_assets (
    instance_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    asset_kind TEXT NOT NULL CHECK (asset_kind IN ('REAL_PHOTO','DOCUMENT_VISUAL','EDITORIAL_CARD')),
    origin_kind TEXT NOT NULL CHECK (origin_kind IN ('USER_OWNED','OFFICIAL','CREATIVE_COMMONS','PUBLIC_DOMAIN','LICENSED','GENERATED_EDITORIAL_CARD')),
    title TEXT NOT NULL DEFAULT '',
    storage_ref TEXT NOT NULL,
    source_url TEXT,
    source_asset_url TEXT,
    credit TEXT NOT NULL,
    rights_basis TEXT NOT NULL,
    license_code TEXT NOT NULL,
    rights_evidence_ref TEXT NOT NULL,
    rights_evidence_fingerprint TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    perceptual_hash TEXT,
    mime_type TEXT NOT NULL,
    width INTEGER CHECK (width IS NULL OR width > 0),
    height INTEGER CHECK (height IS NULL OR height > 0),
    captured_at TEXT,
    freshness_class TEXT NOT NULL CHECK (freshness_class IN ('EVERGREEN','SLOW_DECAY','FAST_DECAY','EVENT_ONLY')),
    synthetic INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0,1)),
    depicts_real_scene INTEGER NOT NULL DEFAULT 0 CHECK (depicts_real_scene IN (0,1)),
    status TEXT NOT NULL CHECK (status IN ('CANDIDATE','RIGHTS_VERIFIED','BLOCKED')),
    usage_scope_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, media_id),
    UNIQUE (instance_id, content_fingerprint),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS media_bindings (
    instance_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('STORY','ENTITY','EVENT','PLACE')),
    target_id TEXT NOT NULL,
    specificity_class TEXT NOT NULL CHECK (specificity_class IN ('EVENT_DIRECT','SUBJECT_DIRECT','PLACE_DIRECT','CONTEXT_CURRENT','CONTEXT_ARCHIVE','DOCUMENT_VISUAL')),
    relevance_score INTEGER NOT NULL CHECK (relevance_score BETWEEN 0 AND 100),
    context_disclosure TEXT NOT NULL DEFAULT '',
    usage_scope_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, binding_id),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id, media_id) REFERENCES media_assets(instance_id, media_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS media_derivatives (
    instance_id TEXT NOT NULL,
    derivative_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('SITE_HERO','OPEN_GRAPH','FACEBOOK','INSTAGRAM','THUMBNAIL')),
    storage_ref TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    crop_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, derivative_id),
    UNIQUE (instance_id, media_id, purpose, content_fingerprint),
    FOREIGN KEY (instance_id, media_id) REFERENCES media_assets(instance_id, media_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS story_media_assignments (
    instance_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    usage_scope TEXT NOT NULL CHECK (usage_scope IN ('SITE','SOCIAL')),
    media_id TEXT,
    derivative_id TEXT,
    assignment_status TEXT NOT NULL CHECK (assignment_status IN ('MEDIA_READY','EDITORIAL_CARD_REQUIRED','NO_VISUAL')),
    specificity_class TEXT NOT NULL CHECK (specificity_class IN ('EVENT_DIRECT','SUBJECT_DIRECT','PLACE_DIRECT','CONTEXT_CURRENT','CONTEXT_ARCHIVE','DOCUMENT_VISUAL','EDITORIAL_CARD','NO_VISUAL')),
    context_disclosure TEXT NOT NULL DEFAULT '',
    resolver_fingerprint TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, story_id, usage_scope),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, media_id) REFERENCES media_assets(instance_id, media_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, derivative_id) REFERENCES media_derivatives(instance_id, derivative_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_media_assets_status
    ON media_assets(instance_id, status, freshness_class, updated_at);
CREATE INDEX IF NOT EXISTS idx_media_bindings_target
    ON media_bindings(instance_id, target_type, target_id, specificity_class, relevance_score);
CREATE INDEX IF NOT EXISTS idx_media_bindings_media
    ON media_bindings(instance_id, media_id, target_type);
CREATE INDEX IF NOT EXISTS idx_media_derivatives_media
    ON media_derivatives(instance_id, media_id, purpose);
CREATE INDEX IF NOT EXISTS idx_story_media_status
    ON story_media_assignments(instance_id, assignment_status, updated_at);
