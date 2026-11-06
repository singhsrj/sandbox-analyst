"""HTTP behaviour of the API with fake services (no network)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import Services
from app.auth import issue_token
from app.main import create_app
from app.ratelimit import RateLimiter
from app.service.chat import ChatService
from tests.fakes import FakeAgent, FakeSandboxes, FakeStore, recorded_events
from tests.helpers import make_settings

CODE = "open-sesame"
SECRET = "s" * 40
THREAD = "thread-abc-123"


def build(tmp_path: Path, **overrides: Any) -> tuple[TestClient, Services, FakeStore]:
    settings = make_settings(
        DEMO_ACCESS_CODE=CODE,
        SESSION_TOKEN_SECRET=SECRET,
        ARTIFACTS_DIR=str(tmp_path),
        CORS_ALLOW_ORIGINS="http://localhost:3000",
        **overrides,
    )
    store = FakeStore()
    sandboxes = FakeSandboxes()
    services = Services(
        settings=settings,
        store=store,  # type: ignore[arg-type]
        sandboxes=sandboxes,  # type: ignore[arg-type]
        chat=ChatService(settings, store, sandboxes, None),  # type: ignore[arg-type]
        login_limiter=RateLimiter(5),
        chat_limiter=RateLimiter(10),
    )
    return TestClient(create_app(services)), services, store


@pytest.fixture
def env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Services, FakeStore]]:
    from app.service import chat as chat_module

    async def fake_build_agent(*a: Any, **k: Any) -> Any:
        return FakeAgent(recorded_events(), "In 2025 there were 1,086 cancelled orders.")

    async def fake_collect(*a: Any, **k: Any) -> list[str]:
        return []

    monkeypatch.setattr(chat_module, "build_agent", fake_build_agent)
    monkeypatch.setattr(chat_module, "get_model", lambda *a, **k: object())
    monkeypatch.setattr(chat_module, "collect_outputs", fake_collect)
    monkeypatch.setattr(chat_module, "make_handler", lambda s: None)
    client, services, store = build(tmp_path)
    with client:
        yield client, services, store


def auth(services: Services, owner: str = "owner-aaaaaaaa") -> dict[str, str]:
    token, _ = issue_token(services.settings, owner)
    return {"Authorization": f"Bearer {token}"}


def chat_body(
    text: str = "How many orders were cancelled?", thread: str = THREAD
) -> dict[str, Any]:
    return {"id": thread, "messages": [{"role": "user", "parts": [{"type": "text", "text": text}]}]}


def read_sse(response: Any) -> list[str]:
    return [line for line in response.iter_lines() if line]


# ----------------------------------------------------------------------------- public
def test_health_reports_live_runs_enabled(env: tuple[TestClient, Services, FakeStore]) -> None:
    client, _, _ = env
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["live_runs_enabled"] is True and body["active_runs"] == 0


def test_examples_are_public(env: tuple[TestClient, Services, FakeStore]) -> None:
    client, _, _ = env
    questions = client.get("/api/examples").json()["questions"]
    assert len(questions) >= 5 and any("March 2025" in q for q in questions)


def test_cors_only_allows_the_configured_origin(
    env: tuple[TestClient, Services, FakeStore],
) -> None:
    client, _, _ = env
    ok = client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options(
        "/api/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


# ----------------------------------------------------------------------------- session
def test_correct_code_returns_a_working_token(env: tuple[TestClient, Services, FakeStore]) -> None:
    client, _, _ = env
    response = client.post("/api/session", json={"code": CODE, "client_id": "my-browser-id-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["client_id"] == "my-browser-id-1" and body["token"].count(".") == 1
    listed = client.get("/api/threads", headers={"Authorization": f"Bearer {body['token']}"})
    assert listed.status_code == 200


def test_wrong_code_is_rejected_without_a_token(
    env: tuple[TestClient, Services, FakeStore],
) -> None:
    client, _, _ = env
    response = client.post("/api/session", json={"code": "nope"})
    assert response.status_code == 401 and "token" not in response.json()


def test_login_attempts_are_rate_limited(env: tuple[TestClient, Services, FakeStore]) -> None:
    client, _, _ = env
    codes = [client.post("/api/session", json={"code": "nope"}).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    # even the right code is refused while limited (no oracle for brute force)
    blocked = client.post("/api/session", json={"code": CODE})
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


def test_login_is_disabled_when_no_code_is_configured(tmp_path: Path) -> None:
    settings = make_settings(ARTIFACTS_DIR=str(tmp_path))
    store = FakeStore()
    services = Services(
        settings=settings,
        store=store,  # type: ignore[arg-type]
        sandboxes=FakeSandboxes(),  # type: ignore[arg-type]
        chat=ChatService(settings, store, FakeSandboxes(), None),  # type: ignore[arg-type]
    )
    with TestClient(create_app(services)) as client:
        assert client.post("/api/session", json={"code": ""}).status_code in (422, 503)
        assert client.post("/api/session", json={"code": "x"}).status_code == 503
        assert client.get("/api/health").json()["live_runs_enabled"] is False


# ----------------------------------------------------------------------------- auth required
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/chat"),
        ("GET", "/api/threads"),
        ("GET", f"/api/threads/{THREAD}"),
        ("DELETE", f"/api/threads/{THREAD}"),
        ("GET", f"/api/threads/{THREAD}/artifacts/report.md"),
    ],
)
def test_protected_endpoints_require_a_valid_token(
    env: tuple[TestClient, Services, FakeStore], method: str, path: str
) -> None:
    client, services, _ = env
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.request(method, path, headers={"Authorization": "Basic abc"}).status_code == 401
    expired, _ = issue_token(services.settings, "owner-aaaaaaaa", now=0)
    assert (
        client.request(method, path, headers={"Authorization": f"Bearer {expired}"}).status_code
        == 401
    )


# ----------------------------------------------------------------------------- chat
def test_chat_streams_the_ai_sdk_protocol(env: tuple[TestClient, Services, FakeStore]) -> None:
    client, services, store = env
    with client.stream("POST", "/api/chat", json=chat_body(), headers=auth(services)) as response:
        assert response.status_code == 200
        assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "no-cache" in response.headers["cache-control"]
        frames = read_sse(response)

    assert frames[-1] == "data: [DONE]"
    payloads = [json.loads(f[6:]) for f in frames if f.startswith("data: ") and f != "data: [DONE]"]
    assert payloads[0]["type"] == "start" and payloads[-1] == {"type": "finish"}
    assert any(p["type"] == "tool-input-available" for p in payloads)
    assert any(p["type"] == "text-delta" and "1,086" in p["delta"] for p in payloads)
    assert len(store.runs) == 1 and store.threads[THREAD]["owner"] == "owner-aaaaaaaa"


def test_accepts_plain_content_messages_too(env: tuple[TestClient, Services, FakeStore]) -> None:
    client, services, store = env
    body = {"id": THREAD, "messages": [{"role": "user", "content": "plain text question"}]}
    with client.stream("POST", "/api/chat", json=body, headers=auth(services)) as response:
        assert response.status_code == 200
        read_sse(response)
    assert store.runs[0]["question"] == "plain text question"


@pytest.mark.parametrize(
    "body",
    [
        {"id": "short", "messages": [{"role": "user", "content": "hi"}]},
        {"id": "../../etc/passwd", "messages": [{"role": "user", "content": "hi"}]},
        {"id": THREAD, "messages": []},
        {"id": THREAD, "messages": [{"role": "assistant", "content": "only the model spoke"}]},
        {"id": THREAD, "messages": [{"role": "user", "parts": [{"type": "text", "text": "   "}]}]},
        {"id": THREAD, "messages": [{"role": "user", "content": "x" * 2001}]},
    ],
)
def test_malformed_or_oversized_requests_are_rejected(
    env: tuple[TestClient, Services, FakeStore], body: dict[str, Any]
) -> None:
    client, services, store = env
    response = client.post("/api/chat", json=body, headers=auth(services))
    assert response.status_code == 422 and not store.runs


def test_a_visitor_cannot_pick_an_unlisted_model(
    env: tuple[TestClient, Services, FakeStore],
) -> None:
    client, services, _ = env
    body = {**chat_body(), "model": "anthropic.claude-opus-5"}
    assert client.post("/api/chat", json=body, headers=auth(services)).status_code == 400


def test_chat_requests_are_rate_limited_per_visitor(
    env: tuple[TestClient, Services, FakeStore],
) -> None:
    client, services, _ = env
    services.chat_limiter = RateLimiter(2)
    statuses = []
    for i in range(3):
        r = client.post(
            "/api/chat", json=chat_body(thread=f"thread-rl-{i}000"), headers=auth(services)
        )
        statuses.append(r.status_code)
    assert statuses == [200, 200, 429]
    other = client.post(
        "/api/chat",
        json=chat_body(thread="thread-rl-9999"),
        headers=auth(services, "owner-bbbbbbbb"),
    )
    assert other.status_code == 200  # a different visitor is unaffected


def test_someone_elses_thread_cannot_be_used_or_read(
    env: tuple[TestClient, Services, FakeStore],
) -> None:
    client, services, _ = env
    with client.stream(
        "POST", "/api/chat", json=chat_body(), headers=auth(services, "owner-aaaaaaaa")
    ) as r:
        read_sse(r)
    intruder = auth(services, "owner-bbbbbbbb")
    assert client.post("/api/chat", json=chat_body(), headers=intruder).status_code == 404
    assert client.get(f"/api/threads/{THREAD}", headers=intruder).status_code == 404
    assert client.delete(f"/api/threads/{THREAD}", headers=intruder).status_code == 404
    assert client.get("/api/threads", headers=intruder).json() == {"threads": []}


# ----------------------------------------------------------------------------- threads
def test_thread_history_returns_replayable_runs(
    env: tuple[TestClient, Services, FakeStore],
) -> None:
    client, services, _ = env
    headers = auth(services)
    with client.stream("POST", "/api/chat", json=chat_body(), headers=headers) as r:
        read_sse(r)
    listing = client.get("/api/threads", headers=headers).json()["threads"]
    assert [t["thread_id"] for t in listing] == [THREAD] and listing[0]["title"].startswith(
        "How many"
    )
    detail = client.get(f"/api/threads/{THREAD}", headers=headers).json()
    (run,) = detail["runs"]
    assert run["question"].startswith("How many") and run["status"] == "ok"
    assert run["chunks"][0]["type"] == "start" and any(
        c["type"] == "data-run" for c in run["chunks"]
    )


def test_deleting_a_thread_removes_it_and_kills_its_sandbox(
    env: tuple[TestClient, Services, FakeStore],
) -> None:
    client, services, _ = env
    headers = auth(services)
    with client.stream("POST", "/api/chat", json=chat_body(), headers=headers) as r:
        read_sse(r)
    assert client.delete(f"/api/threads/{THREAD}", headers=headers).status_code == 204
    assert client.get(f"/api/threads/{THREAD}", headers=headers).status_code == 404
    assert THREAD in services.sandboxes.closed  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------- artifacts
def make_artifact(services: Services, name: str, data: bytes) -> None:
    folder = services.settings.artifacts_dir / THREAD / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)


def test_artifacts_are_served_safely(env: tuple[TestClient, Services, FakeStore]) -> None:
    client, services, store = env
    headers = auth(services)
    store.threads[THREAD] = {"owner": "owner-aaaaaaaa", "title": "t"}
    make_artifact(services, "chart.png", b"\x89PNG fake")
    make_artifact(services, "report.md", b"# Report <script>alert(1)</script>")

    png = client.get(f"/api/threads/{THREAD}/artifacts/chart.png", headers=headers)
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in png.headers["content-security-policy"]

    md = client.get(f"/api/threads/{THREAD}/artifacts/report.md", headers=headers)
    assert md.headers["content-type"].startswith("text/plain")  # never rendered as HTML


@pytest.mark.parametrize(
    "name",
    [
        "..%2F..%2F.env",
        "%2e%2e%2f%2e%2e%2fsecret",
        "..%5Csecret",
        "nope.png",
        ".hidden",
        "a%00.png",
    ],
)
def test_artifact_path_traversal_and_unknown_files_are_404(
    env: tuple[TestClient, Services, FakeStore], name: str
) -> None:
    client, services, store = env
    store.threads[THREAD] = {"owner": "owner-aaaaaaaa", "title": "t"}
    (services.settings.artifacts_dir / "secret").write_text("top secret")
    response = client.get(f"/api/threads/{THREAD}/artifacts/{name}", headers=auth(services))
    assert response.status_code in (404, 422) and "top secret" not in response.text


def test_artifacts_of_other_visitors_are_not_readable(
    env: tuple[TestClient, Services, FakeStore],
) -> None:
    client, services, store = env
    store.threads[THREAD] = {"owner": "owner-aaaaaaaa", "title": "t"}
    make_artifact(services, "chart.png", b"png")
    intruder = auth(services, "owner-bbbbbbbb")
    assert (
        client.get(f"/api/threads/{THREAD}/artifacts/chart.png", headers=intruder).status_code
        == 404
    )
