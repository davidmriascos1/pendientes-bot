CREATE TABLE IF NOT EXISTS pendings (
    id               INTEGER PRIMARY KEY,
    chat_id          INTEGER NOT NULL,
    created_by       INTEGER NOT NULL,
    title            TEXT    NOT NULL,
    state            TEXT    NOT NULL DEFAULT 'OPEN',
    created_at       TEXT    NOT NULL,
    resolved_at      TEXT,
    resolved_by      INTEGER
);
