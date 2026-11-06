# Recorded runs (replay mode)

Each folder is one real conversation exported with `scripts/export_replay.py` and served read-only at `/api/replays` to visitors without an access code. Only runs whose answers were checked against the database are published; the `verified` field says what was checked. See ADR-025.
