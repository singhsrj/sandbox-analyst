-- Users' own databases (ADR-030). Postgres first; MySQL and SQL Server widen `engine` later.
--
-- The password is stored only as AES-256-GCM ciphertext (app/security/secret_box.py); the key is
-- not in the database. `catalog` is the schema snapshot the agent may query, `checks` the result
-- of the latest read-only privilege check (a connection whose checks fail cannot be used).
-- Deleting a connection sets `deleted_at` (recycle bin); after CONNECTION_TRASH_DAYS the API
-- purges it, which deletes its threads and runs through the foreign key below.

CREATE TABLE app.connections (
    connection_id     uuid PRIMARY KEY,
    owner_id          text NOT NULL,
    engine            text NOT NULL CHECK (engine IN ('postgres')),
    name              text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 60),
    host              text NOT NULL CHECK (char_length(host) BETWEEN 1 AND 253),
    port              integer NOT NULL CHECK (port BETWEEN 1024 AND 65535),
    database          text NOT NULL CHECK (char_length(database) BETWEEN 1 AND 63),
    username          text NOT NULL CHECK (char_length(username) BETWEEN 1 AND 63),
    schema_name       text NOT NULL CHECK (char_length(schema_name) BETWEEN 1 AND 63),
    tls_mode          text NOT NULL CHECK (tls_mode IN ('verify-full', 'require')),
    secret_ciphertext bytea NOT NULL,
    key_id            text NOT NULL,
    notes             text NOT NULL DEFAULT '' CHECK (char_length(notes) <= 2000),
    catalog           jsonb NOT NULL,
    checks            jsonb NOT NULL,
    checked_at        timestamptz NOT NULL,
    consented_at      timestamptz NOT NULL,  -- the owner agreed to how their data is processed
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    deleted_at        timestamptz
);
CREATE INDEX connections_owner_idx ON app.connections (owner_id, created_at);
CREATE INDEX connections_trash_idx ON app.connections (deleted_at) WHERE deleted_at IS NOT NULL;

-- NULL = the sample data. A thread keeps its data source for life.
ALTER TABLE app.threads
    ADD COLUMN connection_id uuid REFERENCES app.connections ON DELETE CASCADE;
CREATE INDEX threads_connection_idx ON app.threads (connection_id) WHERE connection_id IS NOT NULL;

REVOKE ALL ON app.connections FROM app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON app.connections TO app_rw;
