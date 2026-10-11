"""
Command-line interface for mailplate.

Usage:

    Read an RFC5322 draft from stdin, apply a profile, and write the
    result to stdout::

        mailplate --profile work < draft.eml > rewritten.eml

    Auto-detect the best profile based on rules embedded in the profile
    files::

        mailplate < draft.eml > rewritten.eml

    List available profiles::

        mailplate --list-profiles
"""

from __future__ import annotations

import sys
from email.message import Message
from pathlib import Path

import click

from . import VERSION
from .merge import merge_profile, parse_email, serialize_email
from .profile import Profile, Rule, discover_profiles
from .rules import _match_rule

DEFAULT_PROFILE_DIRS = [
    Path.home() / ".config" / "mailplate" / "profiles",
    Path("/etc/mailplate/profiles"),
]


def _resolve_profile_dirs(extra: tuple[Path, ...] | None) -> list[Path]:
    """
    Build the list of directories to search for profiles.

    Extra dirs provided on the command line take precedence, followed by
    the user's config directory, then the system-wide directory.

    Args:
        extra: Additional directories from the ``--profile-dir`` option.

    Returns:
        A list of directory paths (may include non-existent directories).

    """
    dirs: list[Path] = []
    if extra:
        dirs.extend(extra)
    dirs.extend(DEFAULT_PROFILE_DIRS)
    return dirs


def _pick_best_profile(profiles: list[Profile], message: Message) -> Profile | None:
    """
    Pick the best matching profile for a message.

    The "best" profile is the one with the most matching rules.  If
    multiple profiles have the same number of matches, the first one
    encountered (by discovery order) wins.

    Args:
        profiles: List of available profiles.
        message: The parsed email message.

    Returns:
        The best matching profile, or ``None`` if none match.

    """
    best: Profile | None = None
    best_score = -1

    for profile in profiles:
        if profile.rules:
            score = sum(
                1 for rule in profile.rules if _match_rule_for_scoring(rule, message)
            )
            if score > best_score:
                best = profile
                best_score = score
        else:
            # A profile with no rules is a catch-all with score 0.
            if best_score < 0:
                best = profile
                best_score = 0

    return best


def _match_rule_for_scoring(rule: Rule, message: Message) -> bool:
    """
    Match a single rule for scoring purposes (import-avoidance wrapper).

    Args:
        rule: The rule to evaluate.
        message: The parsed email message.

    Returns:
        ``True`` if the rule matches.

    """
    return _match_rule(rule, message)


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(version=VERSION, prog_name="mailplate")
@click.option(
    "-p",
    "--profile",
    "profile_name",
    default=None,
    metavar="NAME",
    help="Explicit profile name to apply (disables auto-detection).",
)
@click.option(
    "-d",
    "--profile-dir",
    "profile_dirs",
    type=click.Path(exists=False, file_okay=False, path_type=Path),
    multiple=True,
    help="Additional directory to search for profile files.",
)
@click.option(
    "-l",
    "--list-profiles",
    is_flag=True,
    default=False,
    help="List available profiles and exit.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=True, writable=True, path_type=Path),
    default=None,
    help="Write output to FILE instead of stdout.",
)
def main(
    profile_name: str | None,
    profile_dirs: tuple[Path, ...],
    list_profiles: bool,
    output: Path | None,
) -> None:
    """
    Apply a mailplate profile to an RFC5322 email draft.

    Reads the draft from stdin, transforms it according to the selected
    profile, and writes the result to stdout (or to the file specified
    with ``--output``).
    """
    dirs = _resolve_profile_dirs(profile_dirs)
    profiles = discover_profiles(dirs)

    if list_profiles:
        if not profiles:
            click.echo("No profiles found.", err=True)
            sys.exit(1)
        for prof in profiles:
            click.echo(f"{prof.stem:20s}  {prof.name}")
        sys.exit(0)

    # Read the email draft from stdin.
    raw_data = sys.stdin.buffer.read()
    if not raw_data:
        click.echo("Error: no input data (stdin is empty).", err=True)
        sys.exit(1)

    message = parse_email(raw_data)

    # Determine which profile to apply.
    if profile_name:
        # Explicit profile name.
        profile = _find_profile_by_name(profiles, profile_name)
        if profile is None:
            click.echo(f"Error: profile {profile_name!r} not found.", err=True)
            sys.exit(1)
    else:
        # Auto-detect the best profile.
        profile = _pick_best_profile(profiles, message)
        if profile is None:
            click.echo(
                "Error: no profile matches and no profile specified.",
                err=True,
            )
            sys.exit(1)

    # Apply the profile.
    result = merge_profile(message, profile)
    serialized = serialize_email(result)

    if output:
        output.write_bytes(serialized)
    else:
        sys.stdout.buffer.write(serialized)


def _find_profile_by_name(profiles: list[Profile], name: str) -> Profile | None:
    """
    Find a profile by its stem (filename without extension).

    Args:
        profiles: List of profiles to search.
        name: The name (stem) to look for.

    Returns:
        The matching profile, or ``None``.

    """
    for prof in profiles:
        if prof.stem == name or prof.name == name:
            return prof
    return None


if __name__ == "__main__":
    main()
