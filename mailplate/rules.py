"""Rule matching engine for mailplate profiles.

Rules are evaluated against a parsed email message to determine which
profile (if any) should be auto-selected.
"""

from __future__ import annotations

import re
from email.message import Message
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mailplate.profile import Profile, Rule


def _get_header_value(message: Message, header_name: str) -> str:
    """Return the value of a single header, or an empty string.

    Args:
        message: The parsed email message.
        header_name: Case-insensitive header field name.

    Returns:
        The header value, or ``""`` if absent.

    """
    return message.get(header_name, "")


def _get_body(message: Message) -> str:
    """Extract the plain-text body from a message.

    For multipart messages, the first ``text/plain`` part is used.
    For single-part messages, the payload itself is treated as the body.

    Args:
        message: The parsed email message.

    Returns:
        The plain-text body content.

    """
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and not part.is_multipart():
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    return payload.decode("utf-8", errors="replace")
                if isinstance(payload, str):
                    return payload
        return ""
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        return payload
    return ""


def _match_rule(rule: Rule, message: Message) -> bool:
    """Check whether a single rule matches the given message.

    Args:
        rule: The rule to evaluate.
        message: The parsed email message.

    Returns:
        ``True`` if the rule matches.

    """
    if rule.kind == "header":
        # Rule value format: "HeaderName: regex"
        colon_pos = rule.value.find(":")
        if colon_pos == -1:
            return False
        header_name = rule.value[:colon_pos].strip()
        regex_str = rule.value[colon_pos + 1 :].strip()
        value = _get_header_value(message, header_name)
        try:
            return bool(re.search(regex_str, value))
        except re.error:
            return False

    # rule.kind is Literal["header", "body"] so this handles "body".
    body = _get_body(message)
    try:
        return bool(re.search(rule.value, body))
    except re.error:
        return False


def profile_matches(profile: Profile, message: Message) -> bool:
    """Check whether a profile's rules all match the given message.

    All rules of the profile must match (AND semantics).

    Args:
        profile: The profile to evaluate.
        message: The parsed email message.

    Returns:
        ``True`` if all rules match.

    """
    if not profile.rules:
        # A profile with no rules matches everything (catch-all).
        return True
    return all(_match_rule(rule, message) for rule in profile.rules)
