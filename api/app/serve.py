"""Run the API: `uv run python -m app.serve [--host 127.0.0.1] [--port 8000] [--reload]`.

On Windows uvicorn defaults to the Proactor event loop, which psycopg's async mode cannot use
(the database pool then times out at startup). This entry point selects the Selector loop there
and keeps uvicorn's default everywhere else (Linux production).
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SandboxAnalyst API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
    parser.add_argument(
        "--proxy-headers",
        action="store_true",
        help="behind a reverse proxy: take the client IP from X-Forwarded-For, trusting only "
        "FORWARDED_ALLOW_IPS (the proxy's network, never '*': uvicorn would then take the "
        "leftmost, client-controlled address)",
    )
    args = parser.parse_args()
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    trusted = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
    if args.proxy_headers and trusted.strip() == "*":
        raise SystemExit("FORWARDED_ALLOW_IPS='*' would let clients fake their IP; use a CIDR.")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop=loop,
        app_dir="api",
        proxy_headers=args.proxy_headers,
        forwarded_allow_ips=trusted if args.proxy_headers else None,
    )


if __name__ == "__main__":
    main()
