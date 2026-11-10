"""Deliver the agent's output files, and check the final answer's claims about them.

Why this exists: in testing, gpt-oss-120b repeatedly wrote "chart.png (exported)" in its answer
without ever calling export_artifact. A prompt instruction did not fix it, so delivery is now
deterministic: everything the agent saves under /home/user/outputs/ is collected when the run
ends. `unverified_file_claims` then records any chart/report the answer mentions that was not
actually delivered (a faithfulness failure we want to measure, not hide).
"""

from __future__ import annotations

import logging
import posixpath
import re

from app.artifacts import ArtifactError, ArtifactStore
from app.sandbox.manager import OUTPUT_DIR, SandboxManager

logger = logging.getLogger(__name__)

# Only deliverable-style files are checked: charts and the report. Data CSVs are routinely
# mentioned as inputs ("loaded monthly.csv"), which would cause false alarms.
_CLAIM_PATTERN = re.compile(r"[A-Za-z0-9_\-]+\.(?:png|jpe?g)|report\.md", re.IGNORECASE)


async def collect_outputs(
    sandboxes: SandboxManager, thread_id: str, artifacts: ArtifactStore
) -> list[str]:
    """Copy every file in the sandbox's outputs directory into the artifact store."""
    if thread_id not in sandboxes.active_threads:
        return []
    try:
        sandbox = await sandboxes.get(thread_id)
        listing = await sandbox.aexecute(f"find {OUTPUT_DIR} -maxdepth 1 -type f", timeout=30)
        paths = [
            line.strip()
            for line in listing.output.splitlines()
            if line.strip().startswith(f"{OUTPUT_DIR}/")
        ]
        collected: list[str] = []
        for response in await sandbox.adownload_files(paths):
            if response.error or response.content is None:
                continue
            try:
                artifacts.save(posixpath.basename(response.path), response.content)
                collected.append(posixpath.basename(response.path))
            except ArtifactError as exc:
                logger.warning("output skipped %s: %s", response.path, exc)
        return collected
    except Exception:  # delivering outputs must never fail the run itself
        logger.exception("collecting outputs failed")
        return []


async def missing_file_claims(
    sandboxes: SandboxManager, thread_id: str, artifacts: ArtifactStore, answer: str
) -> list[str]:
    """Collect what the agent has saved so far, then name the files `answer` claims but lacks.

    Used mid-run (before the answer is accepted) so the agent can be asked to fix the claim.
    """
    await collect_outputs(sandboxes, thread_id, artifacts)
    return unverified_file_claims(answer, artifacts.all_names())


def unverified_file_claims(answer: str, delivered_names: set[str]) -> list[str]:
    """Chart/report file names the answer mentions that were not actually delivered."""
    mentioned = {m.group(0) for m in _CLAIM_PATTERN.finditer(answer)}
    lowered = {n.lower() for n in delivered_names}
    return sorted(name for name in mentioned if name.lower() not in lowered)
