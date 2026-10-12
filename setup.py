"""Build hooks that render the mailplate man page from its POD source."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent
POD_SOURCE = ROOT / "mailplate.pod"
MAN_TARGET = ROOT / "mailplate.1"


def build_manpage() -> None:
    """Render mailplate.1 from mailplate.pod using pod2man."""
    pod2man = shutil.which("pod2man")
    if pod2man is None:
        msg = "pod2man not found; cannot build the mailplate man page"
        raise RuntimeError(msg)
    command = [
        pod2man,
        "--section=1",
        "--center=User Commands",
        "--release=mailplate",
        "--name=mailplate",
        str(POD_SOURCE),
    ]
    with MAN_TARGET.open("wb") as target:
        subprocess.run(command, stdout=target, check=True)  # nosec B603


class BuildPy(build_py):
    """Render the man page before building the Python package."""

    def run(self) -> None:
        """Generate the man page, then run the default build."""
        build_manpage()
        super().run()


class Sdist(sdist):
    """Render the man page before creating the source distribution."""

    def run(self) -> None:
        """Generate the man page, then run the default sdist."""
        build_manpage()
        super().run()


setup(
    cmdclass={"build_py": BuildPy, "sdist": Sdist},
    data_files=[("share/man/man1", ["mailplate.1"])],
)
