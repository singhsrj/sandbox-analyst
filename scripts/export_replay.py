"""Export a real conversation as a public replay (replay mode, ADR-025).

  uv run python scripts/export_replay.py --thread <thread_id> --slug march-revenue-dip \
      --title "Why did revenue drop in March 2025?" \
      --verified "South region and the March 3-29 window match the planted outage"

Reads the thread's stored runs (exactly the UI-stream chunks the browser received) from the app
database, copies the files the runs produced, and writes api/replays/<slug>/. Only publish runs
whose answers you have checked against the database: a replay is shown as a real, verified run.

Removed on export: Langfuse trace links (a private project visitors cannot open), and every run
summary field except `resumes` (SQL logs and usage are already visible in the chunks).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api")]

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.artifacts import artifact_path  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.replays import SLUG, file_url  # noqa: E402

ARTIFACT_PREFIX = "/api/threads/"


def clean_chunks(chunks: list[dict[str, Any]], slug: str, files: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk.get("type") == "data-artifacts":
            items = []
            for item in chunk["data"]["items"]:
                name = str(item["name"])
                files.add(name)
                items.append({**item, "url": file_url(slug, name)})
            chunk = {**chunk, "data": {**chunk["data"], "items": items}}
        elif chunk.get("type") == "data-run":
            chunk = {**chunk, "data": {**chunk["data"], "trace_url": None}}
        out.append(chunk)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--thread", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--verified", required=True, help="what you checked, shown to visitors")
    parser.add_argument("--order", type=int, default=100, help="position in the list (lower first)")
    args = parser.parse_args()
    if not SLUG.match(args.slug):
        raise SystemExit("slug: lowercase letters, digits and dashes, 2-60 characters")

    settings = get_settings()
    with psycopg.connect(settings.secret("app_database_url"), row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT run_id, question, status, model, final_answer, chunks, summary, created_at "
            "FROM app.runs WHERE thread_id = %s ORDER BY created_at",
            (args.thread,),
        ).fetchall()
    if not rows:
        raise SystemExit(f"no runs for thread {args.thread}")
    if rows[-1]["status"] != "ok":
        raise SystemExit(f"the last run ended with status {rows[-1]['status']}; not exporting")

    target = settings.replays_dir / args.slug
    if target.exists():
        shutil.rmtree(target)
    (target / "files").mkdir(parents=True)

    files: set[str] = set()
    runs = [
        {
            "run_id": str(r["run_id"]),
            "question": r["question"],
            "status": r["status"],
            "model": r["model"],
            "final_answer": r["final_answer"],
            "chunks": clean_chunks(r["chunks"], args.slug, files),
            "summary": {"resumes": bool((r["summary"] or {}).get("resumes"))},
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    for name in sorted(files):
        source = artifact_path(settings.artifacts_dir, args.thread, name)
        if source is None:
            raise SystemExit(f"file {name} is referenced but missing locally; not exporting")
        shutil.copyfile(source, target / "files" / name)

    replay = {
        "title": args.title,
        "question": rows[0]["question"],
        "recorded_at": rows[0]["created_at"].date().isoformat(),
        "model": rows[0]["model"],
        "verified": args.verified,
        "order": args.order,
        "runs": runs,
    }
    (target / "replay.json").write_text(json.dumps(replay, indent=1, default=str), encoding="utf-8")
    print(f"wrote {target} ({len(runs)} runs, {len(files)} files)")


if __name__ == "__main__":
    main()
