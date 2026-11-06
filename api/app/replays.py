"""Recorded runs that anyone can watch without the access code (replay mode, ADR-025).

A replay is a real past conversation exported with `scripts/export_replay.py`: the exact UI-stream
chunks the browser received, plus the files the run produced. Replays are read-only data shipped
with the app, so they keep working when live runs are off, the budget is used up, or a visitor
has no access code. Only runs whose answers were checked against the database are published.

Layout:  <replays_dir>/<slug>/replay.json  and  <replays_dir>/<slug>/files/<name>
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.artifacts import ALLOWED_EXTENSIONS

logger = logging.getLogger(__name__)

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")
_SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def file_url(slug: str, name: str) -> str:
    return f"/api/replays/{slug}/files/{name}"


@dataclass(frozen=True)
class Replay:
    slug: str
    title: str
    question: str
    recorded_at: str
    model: str
    verified: str  # what was checked, shown to visitors
    runs: list[dict[str, Any]]
    order: int = 100  # position in the list (lower first)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.slug,
            "title": self.title,
            "question": self.question,
            "recorded_at": self.recorded_at,
            "model": self.model,
            "verified": self.verified,
        }


class ReplayStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._items: dict[str, Replay] = {}
        self.reload()

    def reload(self) -> None:
        items: dict[str, Replay] = {}
        if self._root.is_dir():
            for path in sorted(self._root.glob("*/replay.json")):
                slug = path.parent.name
                if not SLUG.match(slug):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    items[slug] = Replay(
                        slug=slug,
                        title=str(data["title"]),
                        question=str(data["question"]),
                        recorded_at=str(data["recorded_at"]),
                        model=str(data["model"]),
                        verified=str(data.get("verified", "")),
                        runs=list(data["runs"]),
                        order=int(data.get("order", 100)),
                    )
                except (OSError, ValueError, KeyError, TypeError):
                    logger.exception("skipping unreadable replay %s", path)
        self._items = dict(sorted(items.items(), key=lambda kv: (kv[1].order, kv[0])))

    def list(self) -> list[Replay]:
        return list(self._items.values())

    def get(self, slug: str) -> Replay | None:
        return self._items.get(slug) if SLUG.match(slug) else None

    def file(self, slug: str, name: str) -> Path | None:
        """A replay's file, or None. Same rules as artifacts: plain names, allowed types only."""
        if self.get(slug) is None or not _SAFE_FILE.match(name) or name != Path(name).name:
            return None
        if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            return None
        directory = (self._root / slug / "files").resolve()
        candidate = (directory / name).resolve()
        if candidate.parent != directory or not candidate.is_file():
            return None
        return candidate
