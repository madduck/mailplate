"""Tests for the mailplate man page source."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
POD_SOURCE = ROOT / "mailplate.pod"


def test_manpage_renders() -> None:
    """pod2man renders the POD source into a valid man page."""
    pod2man = shutil.which("pod2man")
    if pod2man is None:
        pytest.skip("pod2man is not installed")
    result = subprocess.run(  # nosec B603
        [pod2man, "--section=1", "--name=mailplate", str(POD_SOURCE)],
        capture_output=True,
        check=True,
    )
    assert b".SH NAME" in result.stdout
    assert b"mailplate" in result.stdout
    assert b"\\-p" in result.stdout
