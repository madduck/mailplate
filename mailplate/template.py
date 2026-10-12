"""
Template engine for mailplate profiles.

Profiles can contain ``{{ variable }}`` placeholders that get filled in
with data extracted from the input email.  The following variables are
available:

``{{ body }}``
    The original plain-text body of the email.
``{{ from }}``
    The full ``From`` header value.
``{{ from_name }}``
    The display-name portion of the ``From`` address.
``{{ from_email }}``
    The email-address portion of the ``From`` address.
``{{ to }}``
    The full ``To`` header value.
``{{ to_name }}``
    The display-name portion of the first ``To`` address.
``{{ to_email }}``
    The email-address portion of the first ``To`` address.
``{{ subject }}``
    The ``Subject`` header value.
``{{ date }}``
    The ``Date`` header value.
``{{ header:<name> }}``
    The value of any arbitrary header named ``<name>``.
``{{ env:<var> }}``
    The value of the environment variable ``<var>``.
``{{ helper:<name> }}``
    Invoke a helper command defined in the profile's ``[helpers]``
    section and insert its stdout.
``{{ rule:<name> }}``
    Named capture group from a matching rule's regexp.

Filters can be chained with the pipe (``|``) syntax:

``{{ to_name | default("there") }}``
    Use ``to_name`` if available, otherwise fall back to ``"there"``.
"""

from __future__ import annotations

import os
import re
import shlex

# The command is split with shlex.split and run without a shell, so commands
# from user-supplied profiles cannot be interpreted by a shell.
import subprocess  # nosec: B404
from email.message import Message
from email.utils import getaddresses, parseaddr
from typing import Any

from .rules import _decode_header_value, _get_body, _get_header_value

#: Maximum time (seconds) a helper command may run before being killed.
_HELPER_TIMEOUT = 5.0


def _extract_name_and_email(address: str) -> tuple[str, str]:
    """
    Split an RFC5322 address into (display_name, email_address).

    Args:
        address: A single RFC5322 address (e.g. ``John Doe <john@e.com>``).

    Returns:
        A ``(name, email)`` tuple.  Either component may be empty.

    """
    name, email = parseaddr(address)
    return name, email


def _first_address_name(addresses: str) -> str:
    """
    Return the display name of the first real address in a header.

    Args:
        addresses: A comma-separated list of RFC5322 addresses.

    Returns:
        The display name of the first address, or empty string.

    """
    parsed = getaddresses([addresses])
    if parsed:
        return parsed[0][0]
    return ""  # pragma: no cover (getaddresses always returns >= 1)


def _first_address_email(
    addresses: str,
) -> str:
    """
    Return the email of the first real address in a header.

    Args:
        addresses: A comma-separated list of RFC5322 addresses.

    Returns:
        The email of the first address, or empty string.

    """
    parsed = getaddresses([addresses])
    if parsed:
        return parsed[0][1]
    return ""  # pragma: no cover (getaddresses always returns >= 1)


def _apply_filter(value: str, filter_expr: str) -> str:
    """
    Apply a single filter to a value.

    Supported filters:

    - ``default("fallback")`` – return ``value`` if non-empty, else the
      fallback string.

    Args:
        value: The current value.
        filter_expr: The filter expression (e.g. ``default("X")``).

    Returns:
        The filtered value.

    """
    filter_expr = filter_expr.strip()
    if filter_expr.startswith("default(") and filter_expr.endswith(")"):
        inner = filter_expr[len("default(") : -1].strip()
        # Remove surrounding quotes.
        if (
            inner.startswith('"') and inner.endswith('"')
        ) or (  # pragma: no cover (branch complexity)
            inner.startswith("'") and inner.endswith("'")
        ):
            inner = inner[1:-1]
        return value if value else inner
    # Unknown filter – return the value unchanged.
    return value


_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*([\w<>.:-]+?)(?:\s*\|\s*(\w+(?:\([^)]*\))?))?\s*\}\}"
)


def _run_helper(command: str) -> str:
    """
    Execute a helper command and return its stdout.

    The command string is split with :func:`shlex.split` to avoid
    shell injection.  If the command exits with a non-zero status,
    times out, or cannot be run, an error message is returned instead
    so that rendering can continue.

    Args:
        command: The command line to run (e.g. ``fortune -n2``).

    Returns:
        The stripped stdout of the command.

    """
    try:
        args = shlex.split(command)
        result = subprocess.run(  # nosec B603
            args,
            check=False,
            capture_output=True,
            timeout=_HELPER_TIMEOUT,
            text=True,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"[helper error: {exc}]"
    if result.returncode != 0:
        return f"[helper exited with status {result.returncode}]"
    return result.stdout.rstrip("\n")


def _get_variable(name: str, context: dict[str, Any]) -> str:
    """
    Look up a variable in the context.

    Supports the ``header:<name>``, ``env:<var>``,
    ``helper:<name>``, and ``rule:<name>`` namespaced variables.

    Args:
        name: The variable name.
        context: The rendering context.

    Returns:
        The variable value, or ``""`` if not found.

    """
    if name.startswith("header:"):
        header_name = name[len("header:") :]
        return context.get("_headers", {}).get(header_name.lower(), "")  # type: ignore[no-any-return]
    if name.startswith("env:"):
        var_name = name[len("env:") :]
        val = os.environ.get(var_name)
        return val if val is not None else ""
    if name.startswith("helper:"):
        helper_name = name[len("helper:") :]
        helpers = context.get("_helpers", {})
        command = helpers.get(helper_name)
        if command is None:
            return f"[unknown helper: {helper_name}]"
        return _run_helper(command)
    if name.startswith("rule:"):
        capture_name = name[len("rule:") :]
        captures = context.get("_captures", {})
        return captures.get(capture_name, "")  # type: ignore[no-any-return]
    return str(context.get(name, ""))


def render_template(
    template: str,
    message: Message,
    helpers: dict[str, str] | None = None,
    captures: dict[str, str] | None = None,
) -> str:
    """
    Render a template string against a parsed email message.

    Args:
        template: The template text with ``{{ variable }}`` placeholders.
        message: The parsed email to extract data from.
        helpers: Optional mapping of helper names to commands.
        captures: Named capture groups from matching rules, injected
            as top-level context variables.

    Returns:
        The rendered string.

    """
    # Build the rendering context from the message.
    from_hdr = _get_header_value(message, "From")
    to_hdr = _get_header_value(message, "To")
    from_name, from_email = _extract_name_and_email(from_hdr)
    to_name = _first_address_name(to_hdr)
    to_email = _first_address_email(to_hdr)

    # Collect all headers for {{ header:... }} lookups.
    all_headers: dict[str, str] = {}
    for key, value in message.raw_items():
        lower = key.lower()
        if lower not in all_headers:
            all_headers[lower] = _decode_header_value(value)

    context: dict[str, Any] = {
        "body": _get_body(message),
        "from": from_hdr,
        "from_name": from_name,
        "from_email": from_email,
        "to": to_hdr,
        "to_name": to_name,
        "to_email": to_email,
        "subject": _get_header_value(message, "Subject"),
        "date": _get_header_value(message, "Date"),
        "_headers": all_headers,
        "_helpers": helpers or {},
        "_captures": captures or {},
    }

    def _replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        raw_value = _get_variable(var_name, context)
        if filter_expr := match.group(2):
            return _apply_filter(raw_value, filter_expr)
        return raw_value

    return _PLACEHOLDER_RE.sub(_replacer, template)
