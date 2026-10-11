"""
Merge a mailplate profile into an RFC5322 email draft.

This module provides the core logic to rewrite an email message
according to a :class:`~mailplate.profile.Profile`: headers are
added or overridden, and the body is reconstructed with greeting,
closing, and signature blocks.
"""

from __future__ import annotations

import base64
import copy
from email import policy
from email.message import Message
from email.parser import BytesParser
from typing import TYPE_CHECKING

from .rules import _get_body
from .template import render_template

if TYPE_CHECKING:
    from .profile import Profile


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

    Args:
        message: The original parsed email.
        profile: The profile to apply.

    Returns:
        The reconstructed body string.

    """
    from mailplate.template import render_template

    original_body = _get_body_for_merge(message)

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

    parts: list[str] = []
    if rendered_greeting:
        parts.append(rendered_greeting)
    parts.append(original_body)
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


def merge_profile(message: Message, profile: Profile) -> Message:
    """
    Apply a profile to an email message and return a new message.

    The original message is not mutated; a deep copy is returned.

    Args:
        message: The original parsed email.
        profile: The profile to apply.

    Returns:
        A new :class:`Message` with the profile applied.

    """
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

    # 2. Build the new body.
    new_body = _build_new_body(result, profile)

    # 3. Replace the body payload.
    if result.is_multipart():
        _replace_multipart_body(result, new_body)
    else:
        result.set_payload(new_body, charset="utf-8")

    return result


def _replace_multipart_body(message: Message, new_body: str) -> None:
    """
    Replace the plain-text part of a multipart message with new body.

    For multipart messages, only the first ``text/plain`` leaf part is
    replaced; other parts (e.g. ``text/html``, attachments) are left
    untouched.

    Args:
        message: A multipart message.
        new_body: The new plain-text body content.

    """
    for part in message.walk():
        if not part.is_multipart() and part.get_content_type() == "text/plain":
            encoded = base64.b64encode(new_body.encode("utf-8")).decode("ascii")
            part.set_payload(encoded, charset="utf-8")
            return


def parse_email(data: bytes) -> Message:
    """
    Parse raw RFC5322 bytes into an email message.

    Args:
        data: The raw email bytes.

    Returns:
        A parsed :class:`Message`.

    """
    parser = BytesParser(policy=policy.default)
    return parser.parsebytes(data)


def serialize_email(message: Message) -> bytes:
    """
    Serialise an email message back to RFC5322 bytes.

    Args:
        message: The email message to serialise.

    Returns:
        The RFC5322 bytes.

    """
    return message.as_bytes(policy=policy.default)
