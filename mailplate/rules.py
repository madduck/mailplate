"""
Rule matching engine for mailplate profiles.

Rules are evaluated against a parsed email message to determine which
profile (if any) should be auto-selected.
"""

from __future__ import annotations

import re
from email.message import Message
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .profile import Profile, Rule


def _get_header_value(message: Message, header_name: str) -> str:
    """
    Return the value of a single header, or an empty string.

    Args:
        message: The parsed email message.
        header_name: Case-insensitive header field name.

    Returns:
        The header value, or ``""`` if absent.

    """
    return message.get(header_name, "")


def _get_body(message: Message) -> str:
    """
    Extract the plain-text body from a message.

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
                if isinstance(payload, str):  # pragma: no cover
                    return payload  # pragma: no cover
        return ""
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        return payload  # pragma: no cover
    return ""  # pragma: no cover


def _get_rcpt_values(message: Message) -> list[str]:
    """
    Return the values of all To/Cc/Bcc headers of a message.

    Args:
        message: The parsed email message.

    Returns:
        The header values, in To/Cc/Bcc order; empty strings are
        omitted.

    """
    return [
        value
        for header_name in ("To", "Cc", "Bcc")
        if (value := message.get(header_name, ""))
    ]


def _match_rule(rule: Rule, message: Message) -> bool:
    """
    Check whether a single rule matches the given message.

    Args:
        rule: The rule to evaluate.
        message: The parsed email message.

    Returns:
        ``True`` if the rule matches.

    """
    if rule.kind == "header":
        # Rule value format: "headername: regex" (field name lower-cased).
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

    if rule.kind == "rcpt":
        # The rule applies if the regex matches any of the To/Cc/Bcc
        # headers.
        try:
            return any(
                re.search(rule.value, value) for value in _get_rcpt_values(message)
            )
        except re.error:
            return False

    # rule.kind is Literal["header", "body", "rcpt"] so this handles "body".
    body = _get_body(message)
    try:
        return bool(re.search(rule.value, body))
    except re.error:
        return False


def _match_rule_captures(rule: Rule, message: Message) -> dict[str, str]:
    """
    Match a rule and return any named capture groups.

    The returned dict maps group name to the captured substring
    (or ``""`` if the rule does not match or has no named groups).

    Args:
        rule: The rule to evaluate.
        message: The parsed email message.

    Returns:
        A dict of named captures.  Empty if the rule doesn't match.

    """
    if rule.kind == "header":
        colon_pos = rule.value.find(":")
        if colon_pos == -1:
            return {}
        header_name = rule.value[:colon_pos].strip()
        regex_str = rule.value[colon_pos + 1 :].strip()
        value = _get_header_value(message, header_name)
        try:
            m = re.search(regex_str, value)
        except re.error:
            return {}
        if not m:
            return {}
        return {k: v for k, v in m.groupdict().items() if v is not None}

    if rule.kind == "rcpt":
        # The rule applies if the regex matches any of the To/Cc/Bcc
        # headers; captures are taken from the first matching header.
        for value in _get_rcpt_values(message):
            try:
                m = re.search(rule.value, value)
            except re.error:
                return {}
            if m:
                return {k: v for k, v in m.groupdict().items() if v is not None}
        return {}

    body = _get_body(message)
    try:
        m = re.search(rule.value, body)
    except re.error:
        return {}
    if not m:
        return {}
    return {k: v for k, v in m.groupdict().items() if v is not None}


def profile_matches(profile: Profile, message: Message) -> bool:
    """
    Check whether a profile's rules all match the given message.

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
