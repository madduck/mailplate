r"""
Profile model and file parsing for mailplate.

A profile defines how an RFC5322 email draft should be rewritten.
Profiles are stored as flat text files in a directory (typically
``$XDG_CONFIG_HOME/mailplate/profiles/``) and use an INI-like format::

    [profile]
    name = Work

    [rules]
    # Every matching rule adds its weight to the profile's score.
    From = .*@company\\.com
    List-Id = .*lists\\.company\\.com
    body = \\[company-internal\\]

    [variables]
    company = My Company Inc.
    team = Platform

    [headers]
    X-Mailer = mailplate/1.0
    Organization = {{ var:company }}

    [greeting]
    Hi {{ to_name | default("there") }},

    [closing]
    Best,
    {{ from_name }}

    [signature]
    {{ from_name }}
    {{ from_email }}
    My Company Inc.

Settings shared between profiles can be placed in a file named
``INCLUDE`` in any profile directory; it is merged into every profile
found in that directory and its subdirectories. See
:func:`load_profile` for the merge rules.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)


class ProfileError(Exception):
    """Raised when a profile file is malformed or cannot be loaded."""


@dataclass(frozen=True)
class Rule:
    """
    A single matching rule within a profile.

    Rules are matched independently: every matching rule adds its
    weight to the profile's score, and the profile with the highest
    total score wins (provided that score is at least 1).

    Attributes:
        kind: What aspect of the email to inspect.
        value: The value to match against. For ``header`` rules this is
            the canonical ``headername: regex`` form, with the field
            name lower-cased so that it is case-insensitive; for
            ``body`` and ``rcpt`` rules it is a plain regex.
        weight: How many points this rule contributes when it matches.
            May be zero to match a rule for its captures without
            affecting the profile score, or negative to penalise a
            profile. Defaults to 1.

    """

    kind: Literal["header", "body", "rcpt"]
    value: str
    weight: int = 1

    def __post_init__(self) -> None:
        """Validate the rule kind."""
        if self.kind not in ("header", "body", "rcpt"):
            msg = f"Unknown rule kind: {self.kind!r}"
            raise ProfileError(msg)


@dataclass
class Profile:
    """
    A mailplate profile loaded from a flat text file.

    Attributes:
        name: Human-readable profile name.
        path: Filesystem path of the profile.
        relative_path: Path of the profile relative to the directory it
            was discovered in, or ``None`` for profiles loaded directly
            from a path. See :attr:`stem`.
        rules: Rules used for auto-detection (scored by weight).
        headers: Mapping of header names to their values.
        helpers: Mapping of helper names to commands.
        variables: Mapping of variable names to values, available to
            templates as ``{{ var:<name> }}``.
        greeting: Lines to prepend to the body.
        closing: Lines to append before the signature.
        signature: Lines appended at the end of the message. Unlike
            the other sections, these are captured verbatim, including
            leading whitespace and blank lines.
        defined_sections: Names of the sections that were actually
            present in the profile text (lower-cased). This
            distinguishes a section that was omitted from one that was
            present but empty, which matters when merging an
            ``INCLUDE`` file with the profile that includes it.

    """

    name: str
    path: Path
    relative_path: Path | None = None
    rules: list[Rule] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    remove_headers: list[str] = field(default_factory=list)
    helpers: dict[str, str] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)
    greeting: list[str] = field(default_factory=list)
    closing: list[str] = field(default_factory=list)
    signature: list[str] = field(default_factory=list)
    defined_sections: set[str] = field(default_factory=set)

    @property
    def stem(self) -> str:
        """
        Return the profile identifier.

        Profiles discovered by :func:`discover_profiles` are identified
        by their path relative to the scanned directory, without the
        file extension, so that profiles with the same filename in
        different subdirectories stay distinct (e.g. ``work/foo`` for
        ``work/foo.mplt``). Profiles loaded directly from a path are
        identified by their filename stem.

        """
        if self.relative_path is not None:
            return self.relative_path.with_suffix("").as_posix()
        return self.path.stem


_SECTION_PATTERN = re.compile(r"^\[(\w+)\]\s*$")
#: A rule line: ``HeaderName[:weight] = regexp`` or ``body[:weight] = regexp``.
#: The weight may be zero or negative.
_RULE_LINE_PATTERN = re.compile(
    r"^(?P<name>[^=:\s]+)(?::(?P<weight>-?\d+))?\s*=\s*(?P<value>.*)$"
)
_HEADER_LINE_PATTERN = re.compile(r"^(.+?)\s*=\s*(.*)$")


def _parse_rule_line(line: str) -> Rule | None:
    """
    Try to parse a single rule line.

    Header rules use the field name as the key, optionally suffixed with
    a weight, e.g. ``From = regexp`` or ``From:5 = regexp``. Field
    names are case-insensitive and are normalised to lower case. Body
    rules use the reserved field name ``body``, e.g. ``body = regexp``
    or ``body:3 = regexp``; ``body`` is recognised case-insensitively
    too. The reserved field name ``rcpt`` matches against all of the
    To/Cc/Bcc headers at once, e.g. ``rcpt = regexp`` or ``rcpt:2 =
    regexp``. The weight defaults to 1 and may be zero or negative.

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
        if field == "rcpt":
            # ``rcpt`` matches the To/Cc/Bcc headers (see
            # mailplate.rules); the value is a plain regex.
            return Rule(kind="rcpt", value=value, weight=weight)
        if field == "header":
            # ``header`` is not a header rule anymore; it was the keyword
            # of the old syntax. Fail loudly rather than silently
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


def _dedupe(items: list[str]) -> list[str]:
    """
    Return *items* with duplicates removed, keeping the first occurrence.

    Args:
        items: The list to deduplicate.

    Returns:
        A new list preserving the original order.

    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _merge_fragment(base: Profile, overlay: Profile) -> Profile:
    """
    Merge a more specific profile fragment into a less specific one.

    Rules, helpers, variables, headers, and ``remove_headers``
    accumulate, with ``overlay`` winning on name collisions.
    ``greeting``, ``closing``, and ``signature`` are single-valued: the ``overlay`` definition
    replaces the ``base`` one whenever the corresponding section is
    present in ``overlay`` (even if it is empty). ``overlay`` also
    supplies the metadata (name, path, relative path) of the result.

    Args:
        base: The less specific profile.
        overlay: The more specific profile.

    Returns:
        The merged :class:`Profile`. ``base`` is modified in place and
        returned.

    """
    seen_rules: set[Rule] = set()
    merged_rules: list[Rule] = []
    for rule in [*base.rules, *overlay.rules]:
        if rule in seen_rules:
            continue
        seen_rules.add(rule)
        merged_rules.append(rule)
    base.rules = merged_rules

    base.headers.update(overlay.headers)
    base.helpers.update(overlay.helpers)
    base.variables.update(overlay.variables)
    base.remove_headers = _dedupe([*base.remove_headers, *overlay.remove_headers])

    for section in ("greeting", "closing", "signature"):
        if section in overlay.defined_sections:
            setattr(base, section, list(getattr(overlay, section)))

    base.defined_sections |= overlay.defined_sections
    base.name = overlay.name
    base.path = overlay.path
    base.relative_path = overlay.relative_path
    return base


def _include_paths(path: Path, root: Path) -> list[Path]:
    """
    List the ``INCLUDE`` files that apply to a profile.

    For a profile at ``root/foo/bar/prof.mplt`` this yields
    ``root/INCLUDE``, ``root/foo/INCLUDE``, and
    ``root/foo/bar/INCLUDE``, least specific first.

    Args:
        path: Path of the profile file.
        root: Root directory of the profile scan.

    Returns:
        A list of candidate ``INCLUDE`` paths. The list is empty when
        *path* does not live under *root*.

    """
    try:
        relative = path.parent.relative_to(root)
    except ValueError:
        return []
    paths = [root / "INCLUDE"]
    current = root
    for part in relative.parts:
        current = current / part
        paths.append(current / "INCLUDE")
    return paths


def load_profile(path: Path, *, include_root: Path | None = None) -> Profile:
    """
    Load and parse a profile from a flat text file.

    When *include_root* is given, any ``INCLUDE`` files between that
    root and the profile's own directory are merged in, least specific
    first, before the profile itself is applied on top.

    Args:
        path: Path to the profile file.
        include_root: Root directory to resolve ``INCLUDE`` files
            against. When ``None`` no includes are applied.

    Returns:
        A populated :class:`Profile` instance.

    Raises:
        ProfileError: If the file (or one of its includes) cannot be
            parsed.
        OSError: If a file cannot be read.

    """
    text = path.read_text(encoding="utf-8")
    profile = _parse_profile(text, path)
    if include_root is None:
        return profile

    fragments: list[Profile] = []
    for include_path in _include_paths(path, include_root):
        if not include_path.is_file():
            continue
        include_text = include_path.read_text(encoding="utf-8")
        fragments.append(_parse_profile(include_text, include_path, is_include=True))
    fragments.append(profile)

    merged = fragments[0]
    for fragment in fragments[1:]:
        merged = _merge_fragment(merged, fragment)
    return merged


def _parse_profile(text: str, path: Path, *, is_include: bool = False) -> Profile:
    """
    Parse profile text into a :class:`Profile`.

    Lines in the ``[signature]`` section are captured verbatim: leading
    whitespace and blank lines are preserved rather than stripped.

    Args:
        text: Raw text content of the profile file.
        path: Filesystem path (used for metadata, not reading).
        is_include: Whether the text comes from an ``INCLUDE`` file, in
            which case a ``[profile]`` section is rejected.

    Returns:
        A populated :class:`Profile`.

    Raises:
        ProfileError: If the text is malformed.

    """
    profile = Profile(name=path.stem, path=path)
    current_section: str | None = None

    for line in text.splitlines():
        stripped = line.strip()

        # Section header.
        if match := _SECTION_PATTERN.match(stripped):
            current_section = match.group(1).lower()
            if is_include and current_section == "profile":
                msg = (
                    f"The [profile] section is not allowed in an INCLUDE file ({path})"
                )
                raise ProfileError(msg)
            profile.defined_sections.add(current_section)
            continue

        # Skip empty lines and comments, except inside the signature
        # section, which is copied verbatim (blank lines and all).
        if current_section != "signature" and (
            not stripped or stripped.startswith("#")
        ):
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

        elif current_section == "variables":
            name, _, value = stripped.partition("=")
            profile.variables[name.strip()] = value.strip()

        elif current_section in ("greeting", "closing"):
            getattr(profile, current_section).append(stripped)

        elif current_section == "signature":
            # Preserve the raw line so that leading whitespace and
            # intentionally blank lines survive verbatim.
            profile.signature.append(line)

        else:
            msg = f"Unknown section [{current_section}] in {path}"
            raise ProfileError(msg)

    return profile


def discover_profiles(
    directories: list[Path],
) -> list[Profile]:
    """
    Discover all profile files in the given directories.

    Profile files are recognised by the ``.mplt`` extension and are
    searched for recursively, so profiles may live either directly in a
    scanned directory or in any of its subdirectories. All discovered
    profiles are treated alike regardless of their nesting depth. Each
    profile's :attr:`~Profile.stem` is its path relative to the scanned
    directory (without the ``.mplt`` extension), so profiles in
    different subdirectories do not collide. Any ``INCLUDE`` files
    between a scanned directory and a profile are merged into it (see
    :func:`load_profile`); ``INCLUDE`` files are not discovered as
    profiles themselves.

    Args:
        directories: List of directories to scan for profiles.

    Returns:
        A list of loaded :class:`Profile` instances, sorted by path
        within each scanned directory. When the same file is reachable
        through several scan roots, the first root that discovers it
        determines its relative path.

    """
    profiles: list[Profile] = []
    seen: set[Path] = set()

    for directory in directories:
        if not directory.is_dir():
            continue
        for file_path in sorted(directory.rglob("*.mplt")):
            # Resolve before deduplicating so that the same file found
            # through nested scan roots is only loaded once.
            canonical = file_path.resolve()
            if canonical in seen:
                continue
            seen.add(canonical)
            try:
                profile = load_profile(file_path, include_root=directory)
            except (OSError, ProfileError) as exc:
                # Warn about malformed profiles and include files, then
                # skip them rather than aborting the whole run.
                log.warning("skipping %s: %s", file_path, exc)
                continue
            # Remember where the profile sits relative to the scanned
            # directory so its identifier reflects the subdirectory.
            profile.relative_path = file_path.relative_to(directory)
            profiles.append(profile)

    return profiles
