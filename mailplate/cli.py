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

import logging
import sys
from email.message import Message
from pathlib import Path

import click

from . import VERSION
from .merge import merge_profile, parse_email, serialize_email
from .profile import Profile, Rule, discover_profiles
from .rules import _match_rule, _match_rule_captures

log = logging.getLogger(__name__)

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
        for d in extra:
            log.debug("using extra profile directory: %s", d)
    dirs.extend(DEFAULT_PROFILE_DIRS)
    for d in dirs:
        log.debug("search path: %s", d)
    return dirs


def _pick_best_profile(
    profiles: list[Profile], message: Message
) -> tuple[Profile | None, dict[str, str]]:
    """
    Pick the best matching profile for a message.

    The "best" profile is the one with the highest total score (sum of
    matching rule weights).  If multiple profiles have the same score,
    the first one encountered (by discovery order) wins.

    Alongside the chosen profile, any named capture groups from the
    winning profile's matching rules are returned as a flat dict.

    Args:
        profiles: List of available profiles.
        message: The parsed email message.

    Returns:
        A ``(profile, captures)`` pair.  *profile* is ``None`` if no
        profile matches; *captures* is empty in that case or when the
        winner has no named groups in its rules.

    """
    best: Profile | None = None
    best_score = -1
    best_captures: dict[str, str] = {}

    log.debug("evaluating %d profiles for auto-detection", len(profiles))
    for profile in profiles:
        if profile.rules:
            details: list[str] = []
            score = 0
            captures: dict[str, str] = {}
            for rule in profile.rules:
                matched = _match_rule_for_scoring(rule, message)
                if matched:
                    score += rule.weight
                    details.append(f"  \u2714 {rule.kind} = {rule.value}")
                    captures.update(_match_rule_captures(rule, message))
                else:
                    details.append(f"  \u2718 {rule.kind} = {rule.value}")
            log.debug(
                "profile %r (%s): score %d/%d\n%s",
                profile.stem,
                profile.name,
                score,
                len(profile.rules),
                "\n".join(details),
            )
            if score > best_score:
                log.debug(
                    "  \u2192 new best (previous best was %s)",
                    best_score if best_score >= 0 else "none",
                )
                best = profile
                best_score = score
                best_captures = captures
        else:
            log.debug(
                "profile %r (%s): no rules (catch-all, score 0)",
                profile.stem,
                profile.name,
            )
            if best_score < 0:
                log.debug(
                    "  \u2192 selected as catch-all (no rule-based profile matched)"
                )
                best = profile
                best_score = 0

    if best is not None:
        log.debug(
            "selected profile %r (%s) with score %d",
            best.stem,
            best.name,
            best_score,
        )
    else:
        log.debug("no matching profile found")
    return best, best_captures


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
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Print diagnostic information to stderr.",
)
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
    verbose: bool,
) -> None:
    """
    Apply a mailplate profile to an RFC5322 email draft.

    Reads the draft from stdin, transforms it according to the selected
    profile, and writes the result to stdout (or to the file specified
    with ``--output``).
    """
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s %(message)s",
            stream=sys.stderr,
        )

    dirs = _resolve_profile_dirs(profile_dirs)
    profiles = discover_profiles(dirs)
    log.debug("discovered %d profile(s)", len(profiles))

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
    log.debug("read %d byte(s) from stdin", len(raw_data))

    message = parse_email(raw_data)

    # Determine which profile to apply.
    if profile_name:
        # Explicit profile name.
        profile = _find_profile_by_name(profiles, profile_name)
        if profile is None:
            click.echo(f"Error: profile {profile_name!r} not found.", err=True)
            sys.exit(1)
        log.debug("explicit profile: %r (%s)", profile.stem, profile.name)
        captures: dict[str, str] = {}
    else:
        # Auto-detect the best profile.
        log.debug("auto-detecting profile from %d candidate(s)", len(profiles))
        profile, captures = _pick_best_profile(profiles, message)
        if captures:
            log.debug(
                "named captures from rules: %s",
                ", ".join(f"{k}={v!r}" for k, v in captures.items()),
            )

    if profile is None:
        # No profile matched (auto-detect) or none was specified;
        # pass the input through verbatim.
        log.debug("no profile selected — passing input through unchanged")
        if output:
            output.write_bytes(raw_data)
        else:
            sys.stdout.buffer.write(raw_data)
        return

    # Apply the profile.
    log.debug(
        "applying profile %r (%s): %d header(s), greeting=%s, closing=%s, signature=%s",
        profile.stem,
        profile.name,
        len(profile.headers),
        "yes" if profile.greeting else "no",
        "yes" if profile.closing else "no",
        "yes" if profile.signature else "no",
    )
    result = merge_profile(message, profile, captures)
    serialized = serialize_email(result)

    if output:
        log.debug("writing %d byte(s) to %s", len(serialized), output)
        output.write_bytes(serialized)
    else:
        log.debug("writing %d byte(s) to stdout", len(serialized))
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
