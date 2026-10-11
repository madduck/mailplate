"""Tests for the merge module."""

from __future__ import annotations

import copy
from email.message import Message
from pathlib import Path

import pytest

from mailplate.merge import (
    NotPlainTextError,
    _build_new_body,
    _ensure_plain_text,
    _get_body_for_merge,
    _strip_mime_headers,
    _strip_prefix,
    _strip_suffix,
    merge_profile,
    parse_email,
    serialize_email,
)
from mailplate.profile import Profile


class TestGetBodyForMerge:
    """Tests for _get_body_for_merge."""

    def test_simple_body(self) -> None:
        """A simple body is returned with whitespace stripped."""
        msg = Message()
        msg.set_payload("  Hello, world!\n\n")
        body = _get_body_for_merge(msg)
        assert body == "Hello, world!"

    def test_empty_body(self) -> None:
        """An empty body returns an empty string."""
        msg = Message()
        assert _get_body_for_merge(msg) == ""


class TestStripPrefix:
    """Tests for _strip_prefix."""

    def test_no_prefix(self) -> None:
        """Text without prefix is returned unchanged."""
        assert _strip_prefix("hello world", "greeting") == "hello world"

    def test_prefix_at_start(self) -> None:
        """Prefix followed by newline is stripped."""
        result = _strip_prefix("Hi,\nbody text", "Hi,")
        assert result == "body text"

    def test_exact_match(self) -> None:
        """Text that is exactly the prefix returns empty."""
        assert _strip_prefix("Hi,", "Hi,") == ""

    def test_empty_prefix(self) -> None:
        """Empty prefix returns the text unchanged."""
        assert _strip_prefix("hello", "") == "hello"

    def test_prefix_without_newline(self) -> None:
        """Prefix not followed by newline (not a separate block) is kept."""
        assert _strip_prefix("Hi, there", "Hi,") == "Hi, there"


class TestStripSuffix:
    """Tests for _strip_suffix."""

    def test_no_suffix(self) -> None:
        """Text without suffix is returned unchanged."""
        assert _strip_suffix("hello world", "suffix") == "hello world"

    def test_suffix_at_end(self) -> None:
        """Suffix preceded by newline is stripped."""
        result = _strip_suffix("body text\nBest,\nAlice", "Best,\nAlice")
        assert result == "body text"

    def test_exact_match(self) -> None:
        """Text that is exactly the suffix returns empty."""
        assert _strip_suffix("Best,\nAlice", "Best,\nAlice") == ""

    def test_empty_suffix(self) -> None:
        """Empty suffix returns the text unchanged."""
        assert _strip_suffix("hello", "") == "hello"

    def test_suffix_without_newline(self) -> None:
        """Suffix not preceded by newline (mid-line) is kept."""
        assert _strip_suffix("Best, Alice", "Alice") == "Best, Alice"


class TestBuildNewBody:
    """Tests for _build_new_body."""

    def _make_message(
        self, headers: dict[str, str] | None = None, body: str = ""
    ) -> Message:
        """Create a simple email message."""
        msg = Message()
        if headers:
            for name, value in headers.items():
                msg[name] = value
        if body:
            msg.set_payload(body)
        return msg

    def test_no_sections(self) -> None:
        """A profile with no greeting/closing/signature returns just the body."""
        profile = Profile(name="test", path=Path("test.mplt"))
        msg = self._make_message({}, "Hello")
        result = _build_new_body(msg, profile)
        assert result == "Hello"

    def test_with_greeting(self) -> None:
        """Greeting is prepended to the body."""
        profile = Profile(name="test", path=Path("test.mplt"), greeting=["Hi there,"])
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == "Hi there,\nBody text"

    def test_with_closing(self) -> None:
        """Closing is appended after the body."""
        profile = Profile(
            name="test", path=Path("test.mplt"), closing=["Best,", "Alice"]
        )
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == "Body text\nBest,\nAlice"

    def test_with_signature(self) -> None:
        """Signature is appended after the closing."""
        profile = Profile(
            name="test", path=Path("test.mplt"), signature=["--", "Alice"]
        )
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == "Body text\n--\nAlice"

    def test_all_sections(self) -> None:
        """All sections are combined in order."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            greeting=["Hi {{ to_name }},"],
            closing=["Best,"],
            signature=["{{ from_name }}"],
        )
        msg = self._make_message(
            {"From": "Alice <alice@e.com>", "To": "Bob <bob@e.com>"},
            "Meeting tomorrow?",
        )
        result = _build_new_body(msg, profile)
        assert result == "Hi Bob,\nMeeting tomorrow?\nBest,\nAlice"

    def test_variable_substitution(self) -> None:
        """Template variables in sections are rendered."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            greeting=["Hi {{ to_name }},"],
        )
        msg = self._make_message({"To": "Bob <bob@e.com>"}, "Hello")
        result = _build_new_body(msg, profile)
        assert result == "Hi Bob,\nHello"

    def test_idempotent_greeting(self) -> None:
        """Greeting is not added again if the body already starts with it."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            greeting=["Hi {{ to_name }},"],
        )
        msg = self._make_message({"To": "Bob <bob@e.com>"}, "Hi Bob,\nAlready greeted")
        result = _build_new_body(msg, profile)
        assert result == "Hi Bob,\nAlready greeted"

    def test_idempotent_closing_and_signature(self) -> None:
        """Closing+signature is not added again if the body already ends with it."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            closing=["Best,"],
            signature=["{{ from_name }}"],
        )
        msg = self._make_message(
            {"From": "Alice <alice@e.com>"},
            "Some text\nBest,\nAlice",
        )
        result = _build_new_body(msg, profile)
        assert result == "Some text\nBest,\nAlice"

    def test_idempotent_full_roundtrip(self) -> None:
        """A second application of the same profile yields the same result."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            greeting=["Hi {{ to_name }},"],
            closing=["Best,"],
            signature=["{{ from_name }}"],
        )
        msg = self._make_message(
            {"From": "Alice <alice@e.com>", "To": "Bob <bob@e.com>"},
            "Meeting tomorrow?",
        )
        first = _build_new_body(msg, profile)
        # Simulate a second run: treat first result as the new body.
        msg2 = self._make_message(
            {"From": "Alice <alice@e.com>", "To": "Bob <bob@e.com>"},
            first,
        )
        second = _build_new_body(msg2, profile)
        assert first == second


class TestEnsurePlainText:
    """Tests for _ensure_plain_text."""

    def test_simple_message_passes(self) -> None:
        """A plain message with no Content-Type passes."""
        msg = Message()
        msg["Subject"] = "Test"
        msg.set_payload("Hello")
        _ensure_plain_text(msg)  # should not raise

    def test_explicit_text_plain_passes(self) -> None:
        """A message with Content-Type: text/plain passes."""
        msg = Message()
        msg["Content-Type"] = "text/plain"
        msg.set_payload("Hello")
        _ensure_plain_text(msg)

    def test_multipart_raises(self) -> None:
        """A multipart message raises NotPlainTextError."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText("body", "plain", "utf-8"))
        with pytest.raises(NotPlainTextError, match="multipart"):
            _ensure_plain_text(msg)

    def test_html_raises(self) -> None:
        """A message with Content-Type text/html raises."""
        msg = Message()
        msg["Content-Type"] = "text/html"
        msg.set_payload("<p>Hello</p>")
        with pytest.raises(NotPlainTextError, match="text/html"):
            _ensure_plain_text(msg)


class TestStripMimeHeaders:
    """Tests for _strip_mime_headers."""

    def test_mime_headers_removed(self) -> None:
        """MIME-Version, Content-Type, CTE are stripped."""
        msg = Message()
        msg["Subject"] = "Test"
        msg["MIME-Version"] = "1.0"
        msg["Content-Type"] = "text/plain; charset=utf-8"
        msg["Content-Transfer-Encoding"] = "base64"
        _strip_mime_headers(msg)
        assert "Subject" in msg
        assert "MIME-Version" not in msg
        assert "Content-Type" not in msg
        assert "Content-Transfer-Encoding" not in msg


class TestMergeProfile:
    """Tests for merge_profile."""

    def _make_message(
        self, headers: dict[str, str] | None = None, body: str = ""
    ) -> Message:
        """Create a simple email message."""
        msg = Message()
        if headers:
            for name, value in headers.items():
                msg[name] = value
        if body:
            msg.set_payload(body)
        return msg

    def test_multipart_raises(self) -> None:
        """merge_profile raises on multipart input."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText("body", "plain", "utf-8"))
        profile = Profile(name="test", path=Path("test.mplt"))
        with pytest.raises(NotPlainTextError):
            merge_profile(msg, profile)

    def test_headers_are_set(self) -> None:
        """Profile headers are added to the message."""
        msg = self._make_message({"Subject": "Test"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"X-Mailer": "mailplate/1.0"},
        )
        result = merge_profile(msg, profile)
        assert result["X-Mailer"] == "mailplate/1.0"
        # Original headers are preserved.
        assert result["Subject"] == "Test"

    def test_headers_override(self) -> None:
        """Profile headers override existing ones."""
        msg = self._make_message({"Subject": "Old"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"Subject": "New Subject"},
        )
        result = merge_profile(msg, profile)
        assert result["Subject"] == "New Subject"

    def test_headers_override_case_insensitive(self) -> None:
        """Header override is case-insensitive."""
        msg = self._make_message({"subject": "old"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"Subject": "new"},
        )
        result = merge_profile(msg, profile)
        assert result["Subject"] == "new"

    def test_body_is_replaced(self) -> None:
        """The body is replaced with greeting + body + closing + signature."""
        msg = self._make_message({}, "Original body")
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            greeting=["Hi,"],
            signature=["--", "Me"],
        )
        result = merge_profile(msg, profile)
        payload = result.get_payload()
        body = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
        assert "Hi," in body
        assert "Original body" in body
        assert "--" in body
        assert "Me" in body

    def test_original_not_mutated(self) -> None:
        """The original message is not mutated."""
        msg = self._make_message({"Subject": "Original"}, "Body")
        original_copy = copy.deepcopy(msg)
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"Subject": "Changed"},
        )
        merge_profile(msg, profile)
        assert msg["Subject"] == original_copy["Subject"]

    def test_output_has_no_mime_headers(self) -> None:
        """The merged result has no MIME-Version, Content-Type, or CTE."""
        msg = self._make_message({"Subject": "Test"}, "Body")
        profile = Profile(name="test", path=Path("test.mplt"))
        result = merge_profile(msg, profile)
        assert "MIME-Version" not in result
        assert "Content-Type" not in result
        assert "Content-Transfer-Encoding" not in result


class TestParseAndSerialize:
    """Tests for parse_email and serialize_email."""

    def test_roundtrip(self) -> None:
        """Parsing and serialising preserves the message."""
        raw = b"Subject: Test\r\n\r\nHello, world!\r\n"
        msg = parse_email(raw)
        assert msg["Subject"] == "Test"
        result = serialize_email(msg)
        assert b"Subject: Test" in result
        assert b"Hello, world!" in result
        # No MIME headers are introduced.
        assert b"MIME-Version" not in result

    def test_empty_message(self) -> None:
        """An empty message can be parsed."""
        msg = parse_email(b"")
        assert msg is not None

    def test_no_body(self) -> None:
        """A message with just headers is parsed."""
        raw = b"Subject: Test\r\nFrom: a@b.com\r\n\r\n"
        msg = parse_email(raw)
        assert msg["Subject"] == "Test"
        assert msg["From"] == "a@b.com"
