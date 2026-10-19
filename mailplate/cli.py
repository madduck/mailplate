"""
Command-line interface for mailplate.

Usage:

    Read an email draft from stdin, apply a profile, and write the
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
import os
import sys
from email.message import Message
from pathlib import Path

import click

from . import VERSION
from .merge import merge_profile, parse_email, serialize_email
from .profile import Profile, Rule, discover_profiles
from .rules import _match_rule, _match_rule_captures

log = logging.getLogger(__name__)


def _xdg_config_home() -> Path:
    """
    Return the user's configuration directory.

    Follows the XDG Base Directory Specification: ``$XDG_CONFIG_HOME``
    when it is set to an absolute path, otherwise ``~/.config``.

    Returns:
        The base directory for user configuration.

    """
    configured = os.environ.get("XDG_CONFIG_HOME")
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return Path.home() / ".config"


DEFAULT_PROFILE_DIRS = [
    _xdg_config_home() / "mailplate" / "profiles",
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


def _default_draft() -> Message:
    """
    Build the draft used when stdin is empty.

    The draft carries a single ``Content-Type: text/plain`` header, so
    that the result is a valid plain-text RFC5322 message (a message
    without any headers is not) that later merge steps can operate on.

    Returns:
        An empty plain-text message with a ``Content-Type`` header.

    """
    message = Message()
    message["Content-Type"] = "text/plain"
    return message


def _resolve_log_level(verbose: int, debug: bool, quiet: bool) -> int | None:
    """
    Resolve the logging level from the command-line flags.

    The most restrictive flag wins: ``--quiet`` beats ``--debug`` (or
    ``-vv``), which beats ``--verbose``. When no flag is given, ``None``
    is returned so that the caller leaves logging unconfigured.

    Args:
        verbose: Number of times ``--verbose`` was given.
        debug: Whether ``--debug`` was given.
        quiet: Whether ``--quiet`` was given.

    Returns:
        The logging level, or ``None`` for the default configuration.

    """
    if quiet:
        return logging.ERROR
    if debug or verbose >= 2:
        return logging.DEBUG
    if verbose == 1:
        return logging.INFO
    return None


def _pick_best_profile(
    profiles: list[Profile], message: Message
) -> tuple[Profile | None, dict[str, str]]:
    """
    Pick the best matching profile for a message.

    Only profiles carrying rules can "match": the "best" profile is the
    one with the highest total score (sum of matching rule weights),
    and it must score at least 1 to be selected. A rule with weight 0
    still contributes its captures but adds nothing to the score; a
    rule with a negative weight subtracts points, so a sufficiently
    negative rule can keep its profile from being selected. If multiple
    profiles have the same score, the first one encountered (by
    discovery order) wins.

    Profiles without rules are catch-alls. They are used only as a
    fallback when no rule-based profile produces a positive score; if
    several catch-alls exist, the first one wins. When neither a
    rule-based match nor a catch-all is available, ``None`` is returned
    so the caller can pass the input through unchanged.

    Alongside the chosen profile, any named capture groups from the
    winning profile's matching rules are returned as a flat dict.

    Args:
        profiles: List of available profiles.
        message: The parsed email message.

    Returns:
        A ``(profile, captures)`` pair. *profile* is ``None`` if no
        profile matches; *captures* is empty in that case or when the
        winner has no named groups in its rules.

    """
    best: Profile | None = None
    best_score = 0
    best_captures: dict[str, str] = {}
    catch_all: Profile | None = None

    log.info("evaluating %d profiles for auto-detection", len(profiles))
    for profile in profiles:
        if not profile.rules:
            log.debug(
                "profile %r (%s): no rules (catch-all, score 0)",
                profile.stem,
                profile.name,
            )
            # Remember the first catch-all; it is only applied if no
            # rule-based profile scores above zero.
            if catch_all is None:
                catch_all = profile
            continue

        details: list[str] = []
        score = 0
        for rule in profile.rules:
            matched = _match_rule_for_scoring(rule, message)
            if matched:
                score += rule.weight
                details.append(f"  \u2714 {rule.kind} = {rule.value}")
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
        # A zero score is not a match; require at least one matched point.
        if score > best_score:
            log.debug(
                "  \u2192 new best (previous best was %s)",
                best_score if best is not None else "none",
            )
            best = profile
            best_score = score

    # Fall back to the first catch-all only when nothing scored positively.
    if best is None and catch_all is not None:
        log.info(
            "no rule-based profile matched; falling back to catch-all %r (%s)",
            catch_all.stem,
            catch_all.name,
        )
        best = catch_all
    if best is not None:
        # Collect named captures from every matching rule of the winner.
        best_captures = _collect_captures(best, message)
        log.info(
            "selected profile %r (%s) with score %d",
            best.stem,
            best.name,
            best_score,
        )
    else:
        log.info("no matching profile found")
    return best, best_captures


def _collect_captures(profile: Profile, message: Message) -> dict[str, str]:
    """
    Collect named captures from every matching rule of a profile.

    Non-matching rules contribute nothing, and captures from all
    matching rules are merged in rule order.

    Args:
        profile: The profile whose rules to evaluate.
        message: The parsed email message.

    Returns:
        A dict of named captures (empty when no rule matches or none
        define named groups).

    """
    captures: dict[str, str] = {}
    for rule in profile.rules:
        captures.update(_match_rule_captures(rule, message))
    return captures


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
    count=True,
    help="Print progress to stderr (repeat for per-rule detail).",
)
@click.option(
    "--debug",
    "debug",
    is_flag=True,
    default=False,
    help="Print per-rule and capture detail to stderr.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    default=False,
    help="Only print errors to stderr.",
)
@click.option(
    "-p",
    "--profile",
    "profile_name",
    default=None,
    metavar="NAME",
    help="Explicit profile identifier (stem or relative path) to apply (disables auto-detection).",
)
@click.option(
    "-d",
    "--profile-dir",
    "profile_dirs",
    type=click.Path(exists=False, file_okay=False, path_type=Path),
    multiple=True,
    help="Additional directory to search for profile files (recursively).",
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
    verbose: int,
    debug: bool,
    quiet: bool,
) -> None:
    """
    Apply a mailplate profile to an email draft.

    Reads the draft from stdin, transforms it according to the selected
    profile, and writes the result to stdout (or to the file specified
    with --output). An empty stdin is not an error: the profile is then
    applied to a minimal message created from scratch.
    """
    level = _resolve_log_level(verbose, debug, quiet)
    if level is not None:
        logging.basicConfig(  # pragma: no cover
            level=level,
            format="%(levelname)s %(message)s",
            stream=sys.stderr,
        )  # pragma: no cover

    dirs = _resolve_profile_dirs(profile_dirs)
    profiles = discover_profiles(dirs)
    log.debug("discovered %d profile(s)", len(profiles))

    if list_profiles:
        if not profiles:
            click.echo("No profiles found.", err=True)  # pragma: no cover
            sys.exit(1)  # pragma: no cover
        for prof in profiles:
            click.echo(f"{prof.stem:20s}  {prof.name}")
        sys.exit(0)

    # Read the email draft from stdin. An empty stdin is not an error:
    # it stands for a message that is to be created from scratch.
    raw_data = sys.stdin.buffer.read()
    if raw_data:
        log.debug("read %d byte(s) from stdin", len(raw_data))
        message = parse_email(raw_data)
    else:
        log.debug("stdin is empty; starting from a minimal draft")
        message = _default_draft()

    # Determine which profile to apply.
    if profile_name:
        # Explicit profile name.
        profile = _find_profile_by_name(profiles, profile_name)
        if profile is None:
            click.echo(f"Error: profile {profile_name!r} not found.", err=True)
            sys.exit(1)
        log.debug("explicit profile: %r (%s)", profile.stem, profile.name)
        # The profile is selected explicitly, but its rules are still
        # evaluated so that named captures can be used in templates.
        captures = _collect_captures(profile, message)
    else:
        # Auto-detect the best profile.
        profile, captures = _pick_best_profile(profiles, message)

    if profile is None:
        # No profile matched (auto-detect) or none was specified;
        # pass the input through verbatim. There is nothing to pass on
        # when stdin was empty, so the minimal draft is written instead.
        log.debug("no profile selected — passing input through unchanged")
        passthrough = raw_data or serialize_email(message)
        if output:
            output.write_bytes(passthrough)
        else:
            sys.stdout.buffer.write(passthrough)
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
    Find a profile by its identifier or display name.

    A profile's identifier is its filename stem, or its path relative to
    the scanned directory for profiles discovered in subdirectories
    (both without the ``.mplt`` extension).

    Args:
        profiles: List of profiles to search.
        name: The identifier or display name to look for.

    Returns:
        The matching profile, or ``None``.

    """
    for prof in profiles:
        if prof.stem == name or prof.name == name:
            return prof
    return None


if __name__ == "__main__":
    main()  # pragma: no cover
