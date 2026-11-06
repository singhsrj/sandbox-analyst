"""Turn an exception from a run into a message a visitor can act on.

Only the exception CLASS is inspected, never its text: provider errors can echo request details,
and nothing from an exception message is allowed to reach the browser. The full error is logged
server-side with its traceback.
"""

from __future__ import annotations


def describe_run_error(exc: BaseException) -> str:
    name = type(exc).__name__
    module = type(exc).__module__.split(".")[0]

    if module == "e2b":
        return "The analysis sandbox is unavailable right now. Try again shortly."
    if module in {"psycopg", "psycopg_pool"}:
        return "The database is unavailable right now. Try again shortly."
    if "Authentication" in name or "PermissionDenied" in name:
        return (
            "The model provider rejected the server's credentials. This is a server problem, "
            "not something you did: the operator needs to renew the key."
        )
    if "RateLimit" in name:
        return "The model provider is rate limiting requests. Wait a minute and try again."
    if "Timeout" in name:
        return "The model took too long to respond. Try again, or ask a narrower question."
    if "Connection" in name:
        return "Could not reach the model provider. Try again shortly."
    return f"The run failed ({name})."
