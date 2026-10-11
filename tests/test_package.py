"""Tests for the mailplate package root."""

from __future__ import annotations

import importlib
from unittest.mock import patch


def test_version_fallback() -> None:
    """When _version.py cannot be imported, VERSION is None."""
    with patch.dict("sys.modules", {"mailplate._version": None}):
        import mailplate

        importlib.reload(mailplate)
        assert mailplate.VERSION is None
