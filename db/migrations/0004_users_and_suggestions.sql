-- Accounts (ADR-028) and the landing page's suggestion box.

-- One row per signed-in person. `user_id` is ours and owns threads, runs and the usage budget
-- (app.threads.owner_id / app.usage_ledger.owner_id); the provider's id is only mapped to it, so
-- changing provider later does not orphan anyone's history.
CREATE TABLE app.users (
    user_id        text PRIMARY KEY CHECK (user_id ~ '^u_[a-f0-9]{24}$'),
    provider       text NOT NULL,
    provider_sub   text NOT NULL,
    live_access_at timestamptz,          -- set once the access code was entered
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_sub)
);

-- "What else should there be?" Anyone may write one; nobody reads them through the app.
-- No IP address, email or user id is stored.
CREATE TABLE app.suggestions (
    suggestion_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    body          text NOT NULL CHECK (char_length(body) BETWEEN 3 AND 2000),
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX suggestions_created_idx ON app.suggestions (created_at);

-- The schema's default privileges grant ALL to app_rw; narrow them.
REVOKE ALL ON app.users FROM app_rw;
GRANT SELECT, INSERT, UPDATE ON app.users TO app_rw;
REVOKE ALL ON app.suggestions FROM app_rw;
GRANT INSERT ON app.suggestions TO app_rw;  -- write-only for the app
