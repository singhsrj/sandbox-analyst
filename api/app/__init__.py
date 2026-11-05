import asyncio
import sys

__version__ = "0.1.0"

# psycopg's async mode cannot run on Windows' default ProactorEventLoop. Linux (production) is
# unaffected; this keeps local development on Windows working for the CLI, API and tests.
if sys.platform == "win32":  # pragma: no cover - platform specific
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined,unused-ignore]
