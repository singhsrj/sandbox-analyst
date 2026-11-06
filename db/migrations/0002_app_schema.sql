-- Application data (separate from the analytics schema the agent can query).
-- LangGraph's checkpoint tables are created by the app itself (checkpointer.setup()) in this schema.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.threads (
    thread_id  text PRIMARY KEY CHECK (thread_id ~ '^[A-Za-z0-9_-]{8,64}$'),
    owner_id   text NOT NULL,
    title      text NOT NULL,
    sandbox_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX threads_owner_idx ON app.threads (owner_id, updated_at DESC);

-- One row per question/answer turn. `chunks` holds the (coalesced) UI stream so a turn can be
-- replayed exactly as the user saw it; `summary` holds usage, timing, trace link, SQL, artifacts.
CREATE TABLE app.runs (
    run_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id    text NOT NULL REFERENCES app.threads ON DELETE CASCADE,
    question     text NOT NULL,
    status       text NOT NULL,
    provider     text NOT NULL,
    model        text NOT NULL,
    final_answer text NOT NULL DEFAULT '',
    chunks       jsonb NOT NULL DEFAULT '[]',
    summary      jsonb NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX runs_thread_idx ON app.runs (thread_id, created_at);
