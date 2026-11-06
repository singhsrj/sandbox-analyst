-- Token usage per run, for the daily budgets (M5).
-- Deliberately NOT linked to app.threads: deleting a thread deletes its runs (ON DELETE CASCADE),
-- and a budget must not be resettable by deleting conversations. No IP addresses are stored.
-- uuid key instead of a serial so app_rw needs no sequence privileges.

CREATE TABLE app.usage_ledger (
    entry_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id     text NOT NULL,
    thread_id    text NOT NULL,
    total_tokens bigint NOT NULL CHECK (total_tokens >= 0),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX usage_ledger_owner_idx ON app.usage_ledger (owner_id, created_at);
CREATE INDEX usage_ledger_created_idx ON app.usage_ledger (created_at);

-- Append-only for the application: the schema's default privileges grant ALL, so take back
-- everything except reading and inserting.
REVOKE ALL ON app.usage_ledger FROM app_rw;
GRANT SELECT, INSERT ON app.usage_ledger TO app_rw;
