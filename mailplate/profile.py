r"""
Profile model and file parsing for mailplate.

A profile defines how an RFC5322 email draft should be rewritten.
Profiles are stored as flat text files in a directory (typically
``~/.config/mailplate/profiles/``) and use an INI-like format::

    [profile]
    name = Work

    [rules]
    # All rules must match for auto-detection (AND logic).
    From = .*@company\\.com
    List-Id = .*lists\\.company\\.com
    body = \\[company-internal\\]

    [headers]
    X-Mailer = mailplate/1.0
    Organization = My Company Inc.

    [greeting]
    Hi {{ to_name | default("there") }},

    [closing]
    Best,
    {{ from_name }}

    [signature]
    {{ from_name }}
    {{ from_email }}
    My Company Inc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


class ProfileError(Exception):
    """Raised when a profile file is malformed or cannot be loaded."""


@dataclass(frozen=True)
class Rule:
    """
    A single matching rule within a profile.

    All rules belonging to a profile must match for that profile to be
    auto-detected (AND logic).

    Attributes:
        kind: What aspect of the email to inspect.
        value: The value to match against.  For ``header`` rules this is
            the canonical ``headername: regex`` form, with the field
            name lower-cased so that it is case-insensitive; for
            ``body`` rules it is a plain regex.
        weight: How many points this rule contributes when it matches.

    """

    kind: Literal["header", "body"]
    value: str
    weight: int = 1

    def __post_init__(self) -> None:
        """Validate the rule kind."""
        if self.kind not in ("header", "body"):
            msg = f"Unknown rule kind: {self.kind!r}"
            raise ProfileError(msg)
        if self.weight < 1:
            msg = f"Rule weight must be >= 1, got {self.weight}"
            raise ProfileError(msg)


@dataclass
class Profile:
    """
    A mailplate profile loaded from a flat text file.

    Attributes:
        name: Human-readable profile name.
        path: Filesystem path of the profile.
        rules: Rules used for auto-detection (all must match).
        headers: Mapping of header names to their values.
        greeting: Lines to prepend to the body.
        closing: Lines to append before the signature.
        signature: Lines appended at the end of the message.

    """

    name: str
    path: Path
    rules: list[Rule] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    remove_headers: list[str] = field(default_factory=list)
    helpers: dict[str, str] = field(default_factory=dict)
    greeting: list[str] = field(default_factory=list)
    closing: list[str] = field(default_factory=list)
    signature: list[str] = field(default_factory=list)

    @property
    def stem(self) -> str:
        """Return the filename stem (name without suffix)."""
        return self.path.stem


_SECTION_PATTERN = re.compile(r"^\[(\w+)\]\s*$")
#: A rule line: ``HeaderName[:weight] = regexp`` or ``body[:weight] = regexp``.
_RULE_LINE_PATTERN = re.compile(
    r"^(?P<name>[^=:\s]+)(?::(?P<weight>\d+))?\s*=\s*(?P<value>.*)$"
)
_HEADER_LINE_PATTERN = re.compile(r"^(.+?)\s*=\s*(.*)$")


def _parse_rule_line(line: str) -> Rule | None:
    """
    Try to parse a single rule line.

    Header rules use the field name as the key, optionally suffixed with
    a weight, e.g. ``From = regexp`` or ``From:5 = regexp``.  Field
    names are case-insensitive and are normalised to lower case.  Body
    rules use the reserved field name ``body``, e.g. ``body = regexp``
    or ``body:3 = regexp``; ``body`` is recognised case-insensitively
    too.  The weight defaults to 1.

    Args:
        line: A line from the ``[rules]`` section.

    Returns:
        A :class:`Rule` instance, or ``None`` if the line does not match.

    Raises:
        ProfileError: If the removed ``header = ...`` syntax is used.

    """
    if match := _RULE_LINE_PATTERN.match(line):
        # Field names are case-insensitive, so compare and store them in
        # their lower-cased form.
        field = match.group("name").lower()
        weight_str = match.group("weight")
        value = match.group("value").strip()
        weight = int(weight_str) if weight_str else 1
        if field == "body":
            return Rule(kind="body", value=value, weight=weight)
        if field == "header":
            # ``header`` is not a header rule anymore; it was the keyword
            # of the old syntax.  Fail loudly rather than silently
            # treating it as a rule on a header literally named
            # "header".
            msg = (
                "The old 'header = HeaderName: regex' rule syntax is no "
                "longer supported; write 'HeaderName = regex' instead."
            )
            raise ProfileError(msg)
        # Header rules keep the canonical ``headername: regex`` form used
        # internally by the matching engine (see mailplate.rules).
        return Rule(kind="header", value=f"{field}: {value}".strip(), weight=weight)
    return None


def _parse_header_line(line: str) -> tuple[str, str] | None:
    """
    Try to parse a single header definition line.

    Args:
        line: A line from the ``[headers]`` section.

    Returns:
        A ``(name, value)`` tuple, or ``None`` if the line does not match.

    """
    if match := _HEADER_LINE_PATTERN.match(line):
        return (match.group(1).strip(), match.group(2).strip())
    return None


def load_profile(path: Path) -> Profile:
    """
    Load and parse a profile from a flat text file.

    Args:
        path: Path to the profile file.

    Returns:
        A populated :class:`Profile` instance.

    Raises:
        ProfileError: If the file cannot be parsed.
        OSError: If the file cannot be read.

    """
    text = path.read_text(encoding="utf-8")
    return _parse_profile(text, path)


def _parse_profile(text: str, path: Path) -> Profile:
    """
    Parse profile text into a :class:`Profile`.

    Args:
        text: Raw text content of the profile file.
        path: Filesystem path (used for metadata, not reading).

    Returns:
        A populated :class:`Profile`.

    Raises:
        ProfileError: If the text is malformed.

    """
    profile = Profile(name=path.stem, path=path)
    current_section: str | None = None

    for line in text.splitlines():
        stripped = line.strip()

        # Skip empty lines and comments.
        if not stripped or stripped.startswith("#"):
            continue

        # Section header.
        if match := _SECTION_PATTERN.match(stripped):
            current_section = match.group(1).lower()
            continue

        if current_section is None:
            msg = f"Content before any section header in {path}"
            raise ProfileError(msg)

        # Parse content based on section.
        if current_section == "profile":
            if stripped.startswith("name"):
                _name, _, value = stripped.partition("=")
                profile.name = value.strip()

        elif current_section == "rules":
            if rule := _parse_rule_line(stripped):
                profile.rules.append(rule)

        elif current_section == "headers":
            if header := _parse_header_line(stripped):
                profile.headers[header[0]] = header[1]

        elif current_section == "remove_headers":
            profile.remove_headers.append(stripped)

        elif current_section == "helpers":
            name, _, cmd = stripped.partition("=")
            profile.helpers[name.strip()] = cmd.strip()

        elif current_section in ("greeting", "closing", "signature"):
            getattr(profile, current_section).append(stripped)

        else:
            msg = f"Unknown section [{current_section}] in {path}"
            raise ProfileError(msg)

    return profile


def discover_profiles(
    directories: list[Path],
) -> list[Profile]:
    """
    Discover all profile files in the given directories.

    Profile files are recognised by the ``.mplt`` extension.

    Args:
        directories: List of directories to scan for profiles.

    Returns:
        A list of loaded :class:`Profile` instances, sorted by name.

    """
    profiles: list[Profile] = []
    seen: set[Path] = set()

    for directory in directories:
        if not directory.is_dir():
            continue
        for file_path in sorted(directory.iterdir()):
            if file_path.suffix == ".mplt" and file_path not in seen:
                seen.add(file_path)
                try:
                    profiles.append(load_profile(file_path))
                except ProfileError:
                    # Silently skip malformed profiles.
                    continue

    return profiles
