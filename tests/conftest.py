"""Shared pytest fixtures for the mailplate test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def default_profile_dirs(tmp_path: Path) -> list[Path]:
    """
    Provide isolated replacements for the CLI's default profile directories.

    The CLI falls back to ``~/.config/mailplate/profiles`` and
    ``/etc/mailplate/profiles``.  Tests must not read the host's real
    configuration, so both locations are relocated beneath the per-test
    temporary directory.

    Args:
        tmp_path: Per-test temporary directory supplied by pytest.

    Returns:
        The isolated user and system profile directories, in search
        order.

    """
    return [
        tmp_path / "config" / "mailplate" / "profiles",
        tmp_path / "etc" / "mailplate" / "profiles",
    ]


@pytest.fixture(autouse=True)
def _isolate_default_profile_dirs(
    default_profile_dirs: list[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Keep the host's real profile directories out of every test.

    Args:
        default_profile_dirs: The isolated directories to install.
        monkeypatch: pytest fixture used to patch the CLI module.

    """
    monkeypatch.setattr("mailplate.cli.DEFAULT_PROFILE_DIRS", default_profile_dirs)
