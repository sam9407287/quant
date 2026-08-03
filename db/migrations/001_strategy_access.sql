-- Strategy sharing between Google accounts (ADR-005 follow-up).
--
-- db/schema.sql only runs on a fresh volume, so this file exists to be
-- applied by hand to an already-running database:
--
--   railway connect Postgres < db/migrations/001_strategy_access.sql
--
-- It is idempotent — running it twice is a no-op.

CREATE TABLE IF NOT EXISTS strategy_access (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Whose strategies are being shared.
    owner_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Who gets to see them.
    grantee_id   UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status       TEXT        NOT NULL DEFAULT 'pending',
    message      TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at   TIMESTAMPTZ,
    -- Set when the owner has seen the request, so the nav badge can clear
    -- without the request itself being decided.
    seen_at      TIMESTAMPTZ,
    CONSTRAINT strategy_access_not_self CHECK (owner_id <> grantee_id),
    CONSTRAINT strategy_access_status
        CHECK (status IN ('pending', 'granted', 'denied', 'revoked')),
    -- One row per direction of a pair; re-requesting reuses it.
    CONSTRAINT strategy_access_pair UNIQUE (owner_id, grantee_id)
);

CREATE INDEX IF NOT EXISTS strategy_access_owner_idx
    ON strategy_access (owner_id, status);
CREATE INDEX IF NOT EXISTS strategy_access_grantee_idx
    ON strategy_access (grantee_id, status);
