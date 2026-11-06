"""Run the API: `uv run python -m app.serve [--host 127.0.0.1] [--port 8000] [--reload]`.

On Windows uvicorn defaults to the Proactor event loop, which psycopg's async mode cannot use
(the database pool then times out at startup). This entry point selects the Selector loop there
and keeps uvicorn's default everywhere else (Linux production).
"""

from __future__ import annotations

import argparse
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SandboxAnalyst API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
    args = parser.parse_args()
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop=loop,
        app_dir="api",
    )


if __name__ == "__main__":
    main()
