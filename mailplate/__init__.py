"""mailplate: a Unix-style filter for RFC5322 email drafts."""

from __future__ import annotations

__all__ = ["VERSION"]

VERSION: str | None

try:
    from ._version import __version__ as _version

    VERSION = _version
except ImportError:
    VERSION = None
