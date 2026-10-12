"""
Merge a mailplate profile into an RFC5322 email draft.

This module provides the core logic to rewrite an email message
according to a :class:`~mailplate.profile.Profile`: headers are
added or overridden, and the body is reconstructed with greeting,
closing, and signature blocks.
"""

from __future__ import annotations

import copy
import re
from email import policy
from email.message import Message
from email.parser import BytesParser
from typing import TYPE_CHECKING

from .rules import _decode_header_value, _get_body
from .template import render_template

if TYPE_CHECKING:
    from .profile import Profile

#: Policy used for serialising drafts.  ``utf8=True`` makes the
#: generator emit non-ASCII header bodies verbatim as UTF-8 instead of
#: RFC 2047-encoding them.
_POLICY = policy.default.clone(utf8=True)

#: Headers that belong to the MIME machinery and are stripped
#: from the output.
_MIME_HEADERS = {"mime-version", "content-type", "content-transfer-encoding"}

#: The delimiter that separates the body from the signature
#: in an email draft (RFC 3676 flavour).
_SIGNATURE_RE = re.compile(r"^-- $", re.MULTILINE)


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


def _split_body_signature(text: str) -> tuple[str, str]:
    """
    Split *text* into (body, signature) at ``^-- $``.

    The delimiter line itself is consumed and not included in either
    part.  If no delimiter is found the entire text is the body and
    the signature is empty.

    Args:
        text: The full body text from the email.

    Returns:
        A ``(body, signature)`` pair.

    """
    match = _SIGNATURE_RE.search(text)
    if not match:
        return text, ""
    body = text[: match.start()]
    signature = text[match.end() :]
    # Strip trailing newline from the body side of the delimiter
    # so we don't get a double blank line.
    body = body.removesuffix("\n")
    # Strip leading newline from the signature side.
    signature = signature.lstrip("\n")
    return body, signature


def _build_new_body(
    message: Message, profile: Profile, captures: dict[str, str] | None = None
) -> str:
    """
    Build the new body from a profile's greeting, closing, and signature.

    The body is constructed as::

        [greeting ...]
        [body (without signature)]
        [closing ...]
        --\u00a0 (signature delimiter)
        [profile signature ...]

    The greeting and closing manipulation is applied **only** to the
    body part; any signature that was present in the original draft is
    discarded and replaced by the profile's ``[signature]`` section (if
    any).

    Args:
        message: The original parsed email.
        profile: The profile to apply.
        captures: Named capture groups from matching rules, injected
            into the template context.

    Returns:
        The reconstructed body string.

    """
    full_text = _get_body_for_merge(message)
    body, _draft_sig = _split_body_signature(full_text)

    # Each section is a list of lines; we join with newlines and render.
    greeting_text = "\n".join(profile.greeting)
    closing_text = "\n".join(profile.closing)
    sig_text = "\n".join(profile.signature)

    rendered_greeting = (
        render_template(greeting_text, message, profile.helpers, captures=captures)
        if profile.greeting
        else ""
    )
    rendered_closing = (
        render_template(closing_text, message, profile.helpers, captures=captures)
        if profile.closing
        else ""
    )
    rendered_sig = (
        render_template(sig_text, message, profile.helpers, captures=captures)
        if profile.signature
        else ""
    )

    # --- idempotent strip ---
    # Remove greeting from the start of the body if it is already there.
    body = _strip_prefix(body, rendered_greeting)
    # Remove closing from the end of the body if already present.
    body = _strip_suffix(body, rendered_closing)

    # --- reassemble ---
    parts: list[str] = []
    if rendered_greeting:
        parts.append(rendered_greeting)
    parts.append(body)
    if rendered_closing:
        parts.append(rendered_closing)
    out = "\n".join(parts)

    if rendered_sig:
        out += "\n-- \n" + rendered_sig
    elif _draft_sig:
        out += "\n-- \n" + _draft_sig

    return out


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


def _apply_headers(
    message: Message,
    original: Message,
    profile: Profile,
    captures: dict[str, str],
) -> None:
    """
    Apply profile headers to *message* in-place, preserving input order.

    Existing headers keep their original position even when the profile
    overrides their value.  If the input repeats a header that the
    profile overrides, the duplicates are collapsed into a single value
    at the position of the first occurrence.  Headers that are not
    present in the input are appended in profile order.  Headers listed
    in ``profile.remove_headers`` are dropped.

    Header values are rendered through the template engine so that
    placeholders like ``{{ subject }}``, ``{{ header:X-Custom }}``, or
    ``{{ helper:get_quote }}`` are expanded.  Rendering is evaluated
    against *original* so that placeholders refer to the untouched
    input rather than values already overridden.  Existing headers are
    copied verbatim; :func:`serialize_email` is responsible for
    emitting non-ASCII content as plain UTF-8.

    Args:
        message: The message to modify in-place.
        original: The untouched input used as template context.
        profile: The profile whose headers to apply.
        captures: Named capture groups from matching rules.

    """
    # Render every profile header up-front, keyed by lower-case name so
    # that lookups are case-insensitive.
    rendered: dict[str, tuple[str, str]] = {}
    for name, value in profile.headers.items():
        rendered[name.lower()] = (
            name,
            render_template(value, original, profile.helpers, captures=captures),
        )

    removed = {name.lower() for name in profile.remove_headers}

    # Walk the original headers in order, substituting overrides in place
    # and dropping duplicates of an overridden header.
    ordered: list[tuple[str, str]] = []
    replaced: set[str] = set()
    for name, value in original.raw_items():
        lower = name.lower()
        if lower in removed:
            continue
        if lower in rendered:
            if lower in replaced:
                continue
            name, value = rendered[lower]
            replaced.add(lower)
        ordered.append((name, value))

    # Append profile headers that were absent from the input, in the
    # order in which they appear in the profile.
    for lower, (name, value) in rendered.items():
        if lower not in replaced:
            ordered.append((name, value))

    # The public API cannot reorder existing headers, so rebuild the
    # header list: clear every header, then re-insert in the desired
    # order.  The payload is left untouched.
    for key in {name.lower() for name in message}:
        del message[key]
    for name, value in ordered:
        message[name] = value


def merge_profile(
    message: Message, profile: Profile, captures: dict[str, str] | None = None
) -> Message:
    """
    Apply a profile to an email message and return a new message.

    The original message is not mutated; a deep copy is returned.

    Args:
        message: The original parsed email.
        profile: The profile to apply.
        captures: Named capture groups from matching rules, injected
            into the template context.

    Returns:
        A new :class:`Message` with the profile applied.

    Raises:
        NotPlainTextError: If *message* is not a plain-text draft.

    """
    _ensure_plain_text(message)

    # Deep-copy so we don't mutate the original.
    result: Message = copy.deepcopy(message)

    # 1. Set/override/remove headers from the profile, preserving the
    #    order in which the input declared them.  Header values are
    #    rendered through the template engine so that placeholders like
    #    {{ subject }}, {{ header:X-Custom }}, or
    #    {{ helper:get_quote }} are expanded.
    captures = captures or {}
    _apply_headers(result, message, profile, captures)

    # 2. Build the new body and set it as UTF-8 bytes so that the body
    #    round-trips unchanged regardless of the message's declared
    #    charset.
    new_body = _build_new_body(result, profile, captures)
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


def _decode_headers(message: Message) -> None:
    """
    Replace every header value in *message* with its decoded Unicode form.

    RFC 2047 encoded words and raw 8-bit values are both decoded so that
    the subsequent serialisation can emit plain UTF-8.

    Args:
        message: The message whose headers to decode in-place.

    """
    decoded = [
        (name, _decode_header_value(value)) for name, value in message.raw_items()
    ]
    for key in {name.lower() for name in message}:
        del message[key]
    for name, value in decoded:
        message[name] = value


def serialize_email(message: Message) -> bytes:
    """
    Serialise an email message back to RFC5322 bytes.

    Non-ASCII header bodies are written verbatim as UTF-8 instead of
    being RFC 2047-encoded.  The message is not modified.

    Args:
        message: The email message to serialise.

    Returns:
        The RFC5322 bytes.

    """
    result: Message = copy.deepcopy(message)
    _decode_headers(result)
    return result.as_bytes(policy=_POLICY)
