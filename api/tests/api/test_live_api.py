"""M3 acceptance: the full stack against real Neon, E2B, Bedrock and Langfuse.

Skipped without credentials. Costs real model tokens (about 150-250k), so it is marked
`integration` and excluded from CI. Ground truth comes from the database, never from constants.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

settings = get_settings()
pytestmark = pytest.mark.integration
needs_everything = pytest.mark.skipif(
    not all(
        [
            settings.app_database_url,
            settings.analyst_database_url,
            settings.e2b_api_key,
            settings.bedrock_api_key,
            settings.demo_access_code,
            settings.session_token_secret,
        ]
    ),
    reason="live credentials not configured",
)


def cancelled_orders(year: int) -> int:
    with psycopg.connect(settings.secret("analyst_database_url"), prepare_threshold=None) as conn:
        row = conn.execute(
            "SELECT count(*) FROM analytics.orders WHERE status = 'cancelled' "
            "AND order_date >= %s AND order_date < %s",
            (f"{year}-01-01", f"{year + 1}-01-01"),
        ).fetchone()
    assert row is not None
    return int(row[0])


def ask(
    client: TestClient, headers: dict[str, str], thread: str, text: str
) -> list[dict[str, Any]]:
    body = {"id": thread, "messages": [{"role": "user", "parts": [{"type": "text", "text": text}]}]}
    with client.stream("POST", "/api/chat", json=body, headers=headers, timeout=400) as response:
        assert response.status_code == 200, response.read()
        frames = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert frames[-1] == "data: [DONE]"
    return [json.loads(f[6:]) for f in frames[:-1]]


def answer_text(chunks: list[dict[str, Any]]) -> str:
    return "".join(c["delta"] for c in chunks if c["type"] == "text-delta")


@needs_everything
def test_two_turns_in_one_thread_end_to_end() -> None:
    thread = f"it-{uuid.uuid4().hex[:12]}"
    truth_2025, truth_2024 = cancelled_orders(2025), cancelled_orders(2024)

    with TestClient(create_app()) as client:
        session = client.post("/api/session", json={"code": settings.secret("demo_access_code")})
        assert session.status_code == 200
        headers = {"Authorization": f"Bearer {session.json()['token']}"}
        services = client.app.state.services  # type: ignore[attr-defined]

        # ---------- turn 1: a question that needs SQL + a chart ----------
        first = ask(
            client,
            headers,
            thread,
            "How many orders were cancelled in 2025? Also save a simple bar chart of order "
            "counts by status for 2025 as status_2025.png under /home/user/outputs/. Be brief.",
        )
        run1 = next(c for c in first if c["type"] == "data-run")["data"]
        assert run1["status"] == "ok", run1
        text1 = answer_text(first).replace(",", "")
        assert str(truth_2025) in text1, f"expected {truth_2025} in: {text1[:300]}"
        assert any(
            c["type"] == "tool-input-available" and c["toolName"] == "run_sql" for c in first
        )
        assert run1["usage"]["total_tokens"] > 0 and run1["model"] == settings.model

        artifacts = next(c for c in first if c["type"] == "data-artifacts")["data"]["items"]
        chart = next(a for a in artifacts if a["name"].endswith(".png"))
        download = client.get(chart["url"], headers=headers)
        assert download.status_code == 200 and download.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert run1["unverified_file_claims"] == []

        sandbox_id = services.sandboxes.sandbox_id(thread)
        assert sandbox_id and (
            await_thread := client.get(f"/api/threads/{thread}", headers=headers)
        )
        assert await_thread.status_code == 200

        # ---------- turn 2: relies on memory of turn 1 and reuses the sandbox ----------
        second = ask(
            client, headers, thread, "And how many were cancelled in 2024? Just the number."
        )
        run2 = next(c for c in second if c["type"] == "data-run")["data"]
        assert run2["status"] == "ok", run2
        assert str(truth_2024) in answer_text(second).replace(",", "")
        assert services.sandboxes.sandbox_id(thread) == sandbox_id  # same sandbox, files kept

        # ---------- history is persisted and replayable ----------
        detail = client.get(f"/api/threads/{thread}", headers=headers).json()
        assert [r["status"] for r in detail["runs"]] == ["ok", "ok"]
        assert detail["runs"][0]["chunks"][0]["type"] == "start"
        assert detail["thread"]["title"].startswith("How many orders were cancelled")
        assert (
            client.get("/api/threads", headers=headers).json()["threads"][0]["thread_id"] == thread
        )

        # ---------- cleanup: deleting the thread kills its sandbox ----------
        assert client.delete(f"/api/threads/{thread}", headers=headers).status_code == 204
        assert services.sandboxes.sandbox_id(thread) is None

    # leaving the app context shut everything down; nothing may remain running
    assert services.sandboxes.active_threads == []
