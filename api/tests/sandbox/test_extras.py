"""Pure-Python extras copied into the sandbox (it has no internet, so it cannot pip install)."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.sandbox.manager import SANDBOX_EXTRAS, SandboxManager, _extra_sources


def test_every_extra_is_available_to_copy_from_our_environment() -> None:
    sources = _extra_sources()
    modules = {p.split("/")[0].removesuffix(".py") for p in sources if ".dist-info" not in p}
    assert modules == set(SANDBOX_EXTRAS)
    assert any(p.startswith("tabulate-") and p.endswith(".dist-info/METADATA") for p in sources)
    assert all(content for content in sources.values())


@pytest.mark.integration
@pytest.mark.skipif(get_settings().e2b_api_key is None, reason="E2B key not configured")
async def test_dataframe_to_markdown_works_inside_the_real_sandbox() -> None:
    """Found in production: report tables via to_markdown() failed on a missing 'tabulate'."""
    async with SandboxManager(get_settings()) as manager:
        sandbox = await manager.get("test-extras")
        result = await sandbox.aexecute(
            "python3 -c \"import pandas as pd; print(pd.DataFrame({'a': [1]}).to_markdown())\""
        )
    assert result.exit_code == 0, result.output
    assert "|    |   a |" in result.output
