"""Replay mode: public, read-only recorded runs and their files."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import Services
from app.main import create_app
from app.replays import ReplayStore
from app.service.chat import ChatService
from tests.fakes import FakeSandboxes, FakeStore
from tests.helpers import make_settings

REPLAY = {
    "title": "Cancelled orders in 2025",
    "question": "How many orders were cancelled in 2025?",
    "recorded_at": "2026-11-06",
    "model": "openai.gpt-oss-120b",
    "verified": "1,086 matches the database",
    "runs": [{"run_id": "r1", "question": "q", "status": "ok", "chunks": [{"type": "start"}]}],
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "replays" / "cancelled-orders"
    (folder / "files").mkdir(parents=True)
    (folder / "replay.json").write_text(json.dumps(REPLAY), encoding="utf-8")
    (folder / "files" / "chart.png").write_bytes(b"\x89PNG fake")
    (folder / "files" / "page.html").write_text("<script>alert(1)</script>")
    (tmp_path / "replays" / "broken").mkdir()
    (tmp_path / "replays" / "broken" / "replay.json").write_text("{not json")
    (tmp_path / "replays" / "Bad_Slug").mkdir()
    (tmp_path / "replays" / "Bad_Slug" / "replay.json").write_text(json.dumps(REPLAY))
    (tmp_path / "secret.txt").write_text("top secret")
    return tmp_path / "replays"


def test_store_loads_valid_replays_and_skips_broken_ones(root: Path) -> None:
    store = ReplayStore(root)
    assert [r.slug for r in store.list()] == ["cancelled-orders"]
    assert store.get("broken") is None and store.get("Bad_Slug") is None


@pytest.mark.parametrize(
    "name", ["../../secret.txt", "..", "page.html", "missing.png", ".hidden", "a/b.png"]
)
def test_store_only_serves_plain_allowed_files(root: Path, name: str) -> None:
    assert ReplayStore(root).file("cancelled-orders", name) is None


def test_a_missing_folder_means_no_replays(tmp_path: Path) -> None:
    assert ReplayStore(tmp_path / "nope").list() == []


@pytest.fixture
def client(root: Path, tmp_path: Path) -> Any:
    settings = make_settings(ARTIFACTS_DIR=str(tmp_path / "runs"), REPLAYS_DIR=str(root))
    store = FakeStore()
    services = Services(
        settings=settings,
        store=store,  # type: ignore[arg-type]
        sandboxes=FakeSandboxes(),  # type: ignore[arg-type]
        chat=ChatService(settings, store, FakeSandboxes(), None),  # type: ignore[arg-type]
        replays=ReplayStore(root),
    )
    with TestClient(create_app(services)) as c:
        yield c


def test_replays_are_public(client: TestClient) -> None:
    listing = client.get("/api/replays").json()["replays"]
    assert listing == [
        {
            "id": "cancelled-orders",
            "title": REPLAY["title"],
            "question": REPLAY["question"],
            "recorded_at": "2026-11-06",
            "model": "openai.gpt-oss-120b",
            "verified": "1,086 matches the database",
        }
    ]
    detail = client.get("/api/replays/cancelled-orders").json()
    assert detail["runs"][0]["chunks"] == [{"type": "start"}]
    assert client.get("/api/replays/nope").status_code == 404


def test_replay_files_are_served_safely(client: TestClient) -> None:
    png = client.get("/api/replays/cancelled-orders/files/chart.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in png.headers["content-security-policy"]
    for bad in ("page.html", "..%2F..%2Fsecret.txt", "missing.png"):
        response = client.get(f"/api/replays/cancelled-orders/files/{bad}")
        assert response.status_code == 404 and "top secret" not in response.text


def test_export_rewrites_file_links_and_drops_private_trace_links() -> None:
    script = Path(__file__).parents[3] / "scripts" / "export_replay.py"
    spec = importlib.util.spec_from_file_location("export_replay", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    files: set[str] = set()
    chunks = [
        {
            "type": "data-artifacts",
            "id": "a",
            "data": {"items": [{"name": "c.png", "url": "/api/threads/t/artifacts/c.png"}]},
        },
        {
            "type": "data-run",
            "id": "run",
            "data": {"trace_url": "https://cloud.langfuse.com/project/x/traces/y"},
        },
    ]
    cleaned = module.clean_chunks(chunks, "my-replay", files)
    assert cleaned[0]["data"]["items"][0]["url"] == "/api/replays/my-replay/files/c.png"
    assert cleaned[1]["data"]["trace_url"] is None
    assert files == {"c.png"}


def test_replays_are_listed_in_their_set_order(tmp_path: Path) -> None:
    for slug, order in (("b-second", 2), ("a-last", 100), ("c-first", 1)):
        folder = tmp_path / slug
        folder.mkdir()
        (folder / "replay.json").write_text(json.dumps({**REPLAY, "order": order}))
    assert [r.slug for r in ReplayStore(tmp_path).list()] == ["c-first", "b-second", "a-last"]
