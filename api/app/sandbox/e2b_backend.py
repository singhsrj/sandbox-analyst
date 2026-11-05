"""Compatibility shim for langchain-e2b 0.0.6 + deepagents 0.6.x.

Bug: `langchain_e2b.AsyncE2BSandbox` calls `self._map_edit_error(...)` when an `edit_file` fails
(for example the model quotes text that is not in the file), but deepagents 0.6.x exposes that
helper only as a module-level function. The agent run then crashes with
`AttributeError: 'AsyncE2BSandbox' object has no attribute '_map_edit_error'`.

Fix: a subclass that provides the method by delegating to deepagents. Remove this shim once
langchain-e2b is released against a deepagents version where the two agree (see
tests/sandbox/test_e2b_backend.py, which fails if the shim stops being needed or stops working).
"""

from __future__ import annotations

from deepagents.backends.protocol import EditResult
from deepagents.backends.sandbox import _map_edit_error
from langchain_e2b import AsyncE2BSandbox


class SafeAsyncE2BSandbox(AsyncE2BSandbox):
    @staticmethod
    def _map_edit_error(error: str, file_path: str, old_string: str) -> EditResult:
        return _map_edit_error(error, file_path, old_string)
