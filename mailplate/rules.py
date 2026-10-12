"""
Rule matching engine for mailplate profiles.

Rules are evaluated against a parsed email message to determine which
profile (if any) should be auto-selected.
"""

from __future__ import annotations

import re
from email.header import decode_header
from email.message import Message
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .profile import Profile, Rule


def _repair_surrogates(text: str) -> str:
    """
    Decode surrogate-escaped bytes embedded in *text* as UTF-8.

    The ``compat32`` email policy decodes raw 8-bit header bytes with
    ``surrogateescape``.  Runs of such surrogate code points are turned
    back into bytes and decoded as UTF-8, leaving all other characters
    untouched.

    Args:
        text: The possibly surrogate-escaped string.

    Returns:
        The repaired string.

    """
    if not any(0xDC80 <= ord(char) <= 0xDCFF for char in text):
        return text
    parts: list[str] = []
    buffered = bytearray()
    for char in text:
        code = ord(char)
        if 0xDC80 <= code <= 0xDCFF:
            buffered.append(code - 0xDC00)
            continue
        if buffered:
            parts.append(buffered.decode("utf-8", errors="replace"))
            buffered.clear()
        parts.append(char)
    if buffered:
        parts.append(buffered.decode("utf-8", errors="replace"))
    return "".join(parts)


def _decode_header_value(value: str) -> str:
    """
    Decode a raw header value to plain Unicode text.

    RFC 2047 encoded words are decoded using their declared charset, and
    raw 8-bit bytes (represented as surrogate escapes by the ``compat32``
    policy) are decoded as UTF-8.

    Args:
        value: The raw header value.

    Returns:
        The decoded header text.

    """
    parts: list[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "ascii", errors="replace"))
        else:
            parts.append(chunk)
    return _repair_surrogates("".join(parts))


def _get_header_value(message: Message, header_name: str) -> str:
    """
    Return the value of a single header, or an empty string.

    Args:
        message: The parsed email message.
        header_name: Case-insensitive header field name.

    Returns:
        The decoded header value, or ``""`` if absent.

    """
    lower = header_name.lower()
    for key, value in message.raw_items():
        if key.lower() == lower:
            return _decode_header_value(value)
    return ""


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
        if (value := _get_header_value(message, header_name))
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
