"""Pins the langchain-e2b / deepagents compatibility shim (see app/sandbox/e2b_backend.py)."""

from __future__ import annotations

import pytest
from langchain_e2b import AsyncE2BSandbox

from app.config import get_settings
from app.sandbox.e2b_backend import SafeAsyncE2BSandbox
from app.sandbox.manager import SandboxManager


def test_upstream_class_still_lacks_the_method_or_shim_is_unneeded() -> None:
    """If upstream gains _map_edit_error, this fails: delete the shim and this test."""
    assert not hasattr(AsyncE2BSandbox, "_map_edit_error")


def test_shim_maps_edit_errors_like_deepagents() -> None:
    result = SafeAsyncE2BSandbox._map_edit_error("string_not_found", "/home/user/a.py", "needle")
    assert result.error is not None and "String not found" in result.error
    missing = SafeAsyncE2BSandbox._map_edit_error("file_not_found", "/home/user/a.py", "x")
    assert missing.error is not None and "not found" in missing.error


@pytest.mark.integration
@pytest.mark.skipif(get_settings().e2b_api_key is None, reason="E2B key not configured")
async def test_failed_edit_returns_an_error_instead_of_crashing() -> None:
    async with SandboxManager(get_settings()) as manager:
        sandbox = await manager.get("test-edit-error")
        await sandbox.aupload_files([("/home/user/a.txt", b"hello world\n")])
        result = await sandbox.aedit("/home/user/a.txt", "text that is not there", "x")
        assert result.error is not None and "String not found" in result.error


@pytest.mark.integration
@pytest.mark.skipif(get_settings().e2b_api_key is None, reason="E2B key not configured")
async def test_sandbox_has_no_internet_no_secrets_and_survives_runaway_code() -> None:
    async with SandboxManager(get_settings()) as manager:
        sandbox = await manager.get("test-isolation")
        env = await sandbox.aexecute("env | cut -d= -f1")
        names = set(env.output.split())
        assert not any(k in names for k in ("E2B_API_KEY", "OPENAI_API_KEY", "ADMIN_DATABASE_URL"))
        assert not any("SECRET" in n or "PASSWORD" in n or "TOKEN" in n for n in names)

        net = await sandbox.aexecute("curl -sS -m 5 https://example.com", timeout=20)
        assert net.exit_code != 0  # DNS/egress blocked

        loop = await sandbox.aexecute("python3 -c 'while True: pass'", timeout=5)
        assert loop.exit_code != 0
        alive = await sandbox.aexecute("echo alive")
        assert alive.output.strip() == "alive"  # sandbox is still usable after the kill

        libs = await sandbox.aexecute("python3 -c 'import pandas, matplotlib, numpy; print(1)'")
        assert libs.output.strip() == "1"
