"""
Merge a mailplate profile into an RFC5322 email draft.

This module provides the core logic to rewrite an email message
according to a :class:`~mailplate.profile.Profile`: headers are
added or overridden, and the body is reconstructed with greeting,
closing, and signature blocks.
"""

from __future__ import annotations

import copy
from email import policy
from email.message import Message
from email.parser import BytesParser
from typing import TYPE_CHECKING

from .rules import _get_body
from .template import render_template

if TYPE_CHECKING:
    from .profile import Profile

#: Headers that belong to the MIME machinery and are stripped
#: from the output.
_MIME_HEADERS = {"mime-version", "content-type", "content-transfer-encoding"}


class NotPlainTextError(ValueError):
    """Raised when the input message is not a plain-text RFC5322 email."""


def _strip_prefix(text: str, prefix: str) -> str:
    """
    Remove *prefix* from the start of *text* if present.

    The prefix must be followed by a newline *or* be the entire text.

    Args:
        text: The string to strip from.
        prefix: The prefix to remove.

    Returns:
        The stripped string.

    """
    if not prefix:
        return text
    if text == prefix:
        return ""
    if text.startswith(prefix + "\n"):
        return text[len(prefix) + 1 :]
    return text


def _strip_suffix(text: str, suffix: str) -> str:
    """
    Remove *suffix* from the end of *text* if present.

    The suffix must be preceded by a newline *or* be the entire text.

    Args:
        text: The string to strip from.
        suffix: The suffix to remove.

    Returns:
        The stripped string.

    """
    if not suffix:
        return text
    if text == suffix:
        return ""
    if text.endswith("\n" + suffix):
        return text[: -(len(suffix) + 1)]
    return text


def _build_new_body(message: Message, profile: Profile) -> str:
    """
    Build the new body from a profile's greeting, closing, and signature.

    The body is constructed as::

        [greeting ...]
        [original body]
        [closing ...]
        [signature ...]

    Each section is rendered through the template engine so that
    ``{{ variable }}`` placeholders are substituted.

    The operation is **idempotent**: if the body already starts with the
    greeting and/or ends with the closing\u00b1signature block, those are
    stripped off first so that repeated applications of the same profile
    do not keep piling on extra decorations.

    Args:
        message: The original parsed email.
        profile: The profile to apply.

    Returns:
        The reconstructed body string.

    """
    body = _get_body_for_merge(message)

    # Each section is a list of lines; we join with newlines and render.
    greeting_text = "\n".join(profile.greeting)
    closing_text = "\n".join(profile.closing)
    signature_text = "\n".join(profile.signature)

    rendered_greeting = (
        render_template(greeting_text, message) if profile.greeting else ""
    )
    rendered_closing = render_template(closing_text, message) if profile.closing else ""
    rendered_signature = (
        render_template(signature_text, message) if profile.signature else ""
    )

    # --- idempotent strip ---
    # Remove greeting from the start if it is already there.
    body = _strip_prefix(body, rendered_greeting)

    # Build the combined suffix that would have been appended
    # (closing \u00b1 signature) and strip it if present.
    suffix_parts: list[str] = []
    if rendered_closing:
        suffix_parts.append(rendered_closing)
    if rendered_signature:
        suffix_parts.append(rendered_signature)
    combined_suffix = "\n".join(suffix_parts)
    body = _strip_suffix(body, combined_suffix)

    # --- reassemble ---
    parts: list[str] = []
    if rendered_greeting:
        parts.append(rendered_greeting)
    parts.append(body)
    if rendered_closing:
        parts.append(rendered_closing)
    if rendered_signature:
        parts.append(rendered_signature)

    return "\n".join(parts)


def _get_body_for_merge(message: Message) -> str:
    """
    Extract the plain-text body for merging purposes.

    This is a thin wrapper around the rules module's body extractor.

    Args:
        message: The parsed email message.

    Returns:
        The plain-text body, with trailing whitespace stripped.

    """
    return _get_body(message).strip()


def _ensure_plain_text(message: Message) -> None:
    """
    Validate that the message is a plain-text RFC5322 email.

    Raises:
        NotPlainTextError: If the message is multipart or has a
            Content-Type other than ``text/plain``.

    """
    if message.is_multipart():
        msg = (
            "Refusing to process a multipart message; "
            "mailplate only handles plain-text drafts."
        )
        raise NotPlainTextError(msg)
    ctype = message.get_content_type()
    if ctype not in ("text/plain", "text/"):
        msg = (
            f"Refusing a message with Content-Type {ctype!r}; "
            "mailplate only handles text/plain drafts."
        )
        raise NotPlainTextError(msg)


def _strip_mime_headers(message: Message) -> None:
    """Remove MIME-related headers from the message in-place."""
    for key in list(message.keys()):
        if key.lower() in _MIME_HEADERS:
            del message[key]


def merge_profile(message: Message, profile: Profile) -> Message:
    """
    Apply a profile to an email message and return a new message.

    The original message is not mutated; a deep copy is returned.

    Args:
        message: The original parsed email.
        profile: The profile to apply.

    Returns:
        A new :class:`Message` with the profile applied.

    Raises:
        NotPlainTextError: If *message* is not a plain-text draft.

    """
    _ensure_plain_text(message)

    # Deep-copy so we don't mutate the original.
    result: Message = copy.deepcopy(message)

    # 1. Set/override headers from the profile.
    for hdr_name, hdr_value in profile.headers.items():
        # Remove existing headers with the same name (case-insensitive).
        # We collect them first to avoid mutation-while-iterating issues.
        keys_to_replace: list[str] = [
            key for key in result if key.lower() == hdr_name.lower()
        ]
        for key in keys_to_replace:
            del result[key]
        result[hdr_name] = hdr_value

    # 2. Build the new body and set it as UTF-8 bytes so that
    #    compat32 serialisation does not force ASCII encoding.
    new_body = _build_new_body(result, profile)
    result.set_payload(new_body.encode("utf-8"))

    # 3. Strip MIME headers so the output is a plain RFC5322 message.
    _strip_mime_headers(result)

    return result


def parse_email(data: bytes) -> Message:
    """
    Parse raw RFC5322 bytes into an email message.

    Args:
        data: The raw email bytes.

    Returns:
        A parsed :class:`Message`.

    """
    parser = BytesParser(policy=policy.compat32)
    return parser.parsebytes(data)


def serialize_email(message: Message) -> bytes:
    """
    Serialise an email message back to RFC5322 bytes.

    Args:
        message: The email message to serialise.

    Returns:
        The RFC5322 bytes.

    """
    return message.as_bytes(policy=policy.compat32)
