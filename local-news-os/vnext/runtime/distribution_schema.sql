PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS channel_products (
    instance_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    desired_revision INTEGER NOT NULL CHECK (desired_revision >= 1),
    product_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    media_selection_id TEXT,
    product_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('READY','HELD','SUPERSEDED')),
    hold_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, product_id),
    UNIQUE (instance_id, story_id, channel_id, desired_revision, product_fingerprint),
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, media_selection_id) REFERENCES story_media_selections(instance_id, selection_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS delivery_ledger (
    instance_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    desired_revision INTEGER NOT NULL CHECK (desired_revision >= 1),
    product_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('READY','HELD','DELIVERING','PUBLISHED','ERROR','BLOCKED_EXTERNAL','SUPERSEDED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    external_object_id TEXT,
    remote_verified INTEGER NOT NULL DEFAULT 0 CHECK (remote_verified IN (0,1)),
    last_error TEXT NOT NULL DEFAULT '',
    next_retry_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, delivery_id),
    UNIQUE (instance_id, story_id, channel_id),
    FOREIGN KEY (instance_id, product_id) REFERENCES channel_products(instance_id, product_id) ON DELETE RESTRICT,
    FOREIGN KEY (instance_id, story_id) REFERENCES stories(instance_id, story_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    instance_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    adapter_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('SUCCESS_UNVERIFIED','ERROR','BLOCKED_EXTERNAL')),
    response_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    attempted_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, attempt_id),
    UNIQUE (instance_id, delivery_id, attempt_number),
    FOREIGN KEY (instance_id, delivery_id) REFERENCES delivery_ledger(instance_id, delivery_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS delivery_remote_receipts (
    instance_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    external_object_id TEXT NOT NULL,
    remote_url TEXT,
    verified INTEGER NOT NULL CHECK (verified IN (0,1)),
    verification_method TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance_id, receipt_id),
    UNIQUE (instance_id, delivery_id, external_object_id, verified_at),
    FOREIGN KEY (instance_id, delivery_id) REFERENCES delivery_ledger(instance_id, delivery_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_channel_products_story
    ON channel_products(instance_id, story_id, channel_id, desired_revision DESC);
CREATE INDEX IF NOT EXISTS idx_delivery_ledger_status
    ON delivery_ledger(instance_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_delivery_attempts_delivery
    ON delivery_attempts(instance_id, delivery_id, attempt_number DESC);
CREATE INDEX IF NOT EXISTS idx_delivery_receipts_delivery
    ON delivery_remote_receipts(instance_id, delivery_id, verified_at DESC);

CREATE TRIGGER IF NOT EXISTS delivery_attempts_no_update
BEFORE UPDATE ON delivery_attempts
BEGIN
    SELECT RAISE(ABORT, 'delivery_attempts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS delivery_attempts_no_delete
BEFORE DELETE ON delivery_attempts
BEGIN
    SELECT RAISE(ABORT, 'delivery_attempts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS delivery_remote_receipts_no_update
BEFORE UPDATE ON delivery_remote_receipts
BEGIN
    SELECT RAISE(ABORT, 'delivery_remote_receipts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS delivery_remote_receipts_no_delete
BEFORE DELETE ON delivery_remote_receipts
BEGIN
    SELECT RAISE(ABORT, 'delivery_remote_receipts is append-only');
END;
