"""Deliverables pulled out of the sandbox (charts, CSVs, reports) and kept on the backend.

M2 stores them on local disk under settings.artifacts_dir/<thread_id>/artifacts/. M3 serves them
through the API; production may move them to S3 behind the same interface.
"""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".csv", ".md", ".txt", ".json"}  # no html/svg (XSS)
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


class ArtifactError(ValueError):
    """The file cannot be exported. The message is safe to show to the model."""


@dataclass(frozen=True)
class Artifact:
    name: str
    path: Path
    size: int
    mime: str


class ArtifactStore:
    def __init__(self, root: Path, thread_id: str) -> None:
        self._dir = root / _safe_part(thread_id) / "artifacts"
        self._items: dict[str, Artifact] = {}

    def save(self, name: str, data: bytes) -> Artifact:
        safe = _SAFE_NAME.sub("_", Path(name).name).strip("._") or "artifact"
        ext = Path(safe).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ArtifactError(
                f"File type '{ext or '(none)'}' cannot be exported. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            )
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ArtifactError(
                f"File is too large ({len(data):,} bytes; max {MAX_ARTIFACT_BYTES:,})."
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._dir / safe
        unchanged = target.is_file() and target.read_bytes() == data
        if not unchanged:
            target.write_bytes(data)
        artifact = Artifact(
            safe, target, len(data), mimetypes.guess_type(safe)[0] or "application/octet-stream"
        )
        if not unchanged:  # files left over from earlier turns are not "new" deliverables
            self._items[safe] = artifact
        return artifact

    def list(self) -> list[Artifact]:
        """Files that are new or changed in this turn."""
        return list(self._items.values())

    def all_names(self) -> set[str]:
        """Every delivered file in this thread, including those from earlier turns."""
        return {p.name for p in self._dir.iterdir() if p.is_file()} if self._dir.is_dir() else set()


def artifact_path(root: Path, thread_id: str, name: str) -> Path | None:
    """Path of a delivered artifact, or None. Rejects anything that is not a plain file name."""
    if not _SAFE_FILE.match(name) or name != Path(name).name:
        return None
    directory = (root / _safe_part(thread_id) / "artifacts").resolve()
    candidate = (directory / name).resolve()
    if candidate.parent != directory or not candidate.is_file():
        return None
    return candidate


def _safe_part(value: str) -> str:
    return _SAFE_NAME.sub("_", value)[:80] or "thread"
