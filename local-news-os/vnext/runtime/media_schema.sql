PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS media_assets (
    instance_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    media_kind TEXT NOT NULL CHECK (media_kind IN ('PHOTO','DOCUMENT_VISUAL','EDITORIAL_CARD')),
    storage_uri TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('USER_OWNED','OFFICIAL','OPEN_LICENSED','EXPLICIT_LICENSED','DOCUMENT_GENERATED','EDITORIAL_CARD')),
    source_url TEXT,
    rights_basis TEXT NOT NULL CHECK (rights_basis IN ('USER_OWNED','OFFICIAL_PRESS_USE','CC_BY','CC_BY_SA','CC0','PUBLIC_DOMAIN','EXPLICIT_LICENSE','DOCUMENT_DERIVATIVE','EDITORIAL_CARD')),
    license_code TEXT NOT NULL,
    credit TEXT NOT NULL,
    rights_evidence TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0,1)),
    depicts_real_scene INTEGER NOT NULL DEFAULT 1 CHECK (depicts_real_scene IN (0,1)),
    freshness_class TEXT NOT NULL CHECK (freshness_class IN ('EVERGREEN','SLOW_DECAY','FAST_DECAY','EVENT_ONLY')),
    captured_at TEXT,
    usage_scopes_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    content_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('READY','HELD','RETIRED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, asset_id),
    UNIQUE (instance_id, content_fingerprint),
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS media_bindings (
    instance_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('STORY','ENTITY')),
    target_id TEXT NOT NULL,
    specificity_class TEXT NOT NULL CHECK (specificity_class IN (
        'EVENT_DIRECT','SUBJECT_DIRECT','PLACE_DIRECT','CONTEXT_CURRENT','CONTEXT_ARCHIVE','DOCUMENT_VISUAL'
    )),
    context_disclosure TEXT NOT NULL DEFAULT '',
    provenance_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, binding_id),
    UNIQUE (instance_id, fingerprint),
    FOREIGN KEY (instance_id, asset_id) REFERENCES media_assets(instance_id, asset_id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id) REFERENCES publication_instances(instance_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS media_derivatives (
    instance_id TEXT NOT NULL,
    derivative_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    width INTEGER CHECK (width IS NULL OR width > 0),
    height INTEGER CHECK (height IS NULL OR height > 0),
    crop_json TEXT NOT NULL DEFAULT '{}',
    content_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, derivative_id),
    UNIQUE (instance_id, asset_id, variant),
    UNIQUE (instance_id, content_fingerprint),
    FOREIGN KEY (instance_id, asset_id) REFERENCES media_assets(instance_id, asset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS story_media_selections (
    instance_id TEXT NOT NULL,
    selection_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    usage_scope TEXT NOT NULL,
    selection_kind TEXT NOT NULL CHECK (selection_kind IN ('ASSET','EDITORIAL_CARD','NO_VISUAL')),
    asset_id TEXT,
    specificity_class TEXT,
    context_disclosure TEXT NOT NULL DEFAULT '',
    fallback_payload_json TEXT NOT NULL DEFAULT '{}',
    resolver_fingerprint TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, selection_id),
    UNIQUE (instance_id, story_id, usage_scope),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, asset_id) REFERENCES media_assets(instance_id, asset_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS media_debt (
    instance_id TEXT NOT NULL,
    debt_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    usage_scope TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OPEN','RESOLVED')),
    reason TEXT NOT NULL,
    selection_id TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    resolved_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, debt_id),
    UNIQUE (instance_id, story_id, usage_scope),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, selection_id) REFERENCES story_media_selections(instance_id, selection_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_media_assets_ready
    ON media_assets(instance_id, status, freshness_class, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_bindings_target
    ON media_bindings(instance_id, target_type, target_id, specificity_class);
CREATE INDEX IF NOT EXISTS idx_media_derivatives_asset
    ON media_derivatives(instance_id, asset_id, variant);
CREATE INDEX IF NOT EXISTS idx_story_media_selections_story
    ON story_media_selections(instance_id, story_id, usage_scope);
CREATE INDEX IF NOT EXISTS idx_media_debt_status
    ON media_debt(instance_id, status, updated_at DESC);
