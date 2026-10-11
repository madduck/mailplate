"""Tests for the merge module."""

from __future__ import annotations

import copy
from email.message import Message
from pathlib import Path

from mailplate.merge import (
    _build_new_body,
    _get_body_for_merge,
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
        # Decode the payload properly (it may be base64-encoded by the policy).
        payload = result.get_payload(decode=True)
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

    def test_multipart_body_replaced(self) -> None:
        """The plain-text part of a multipart message is replaced."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText("Old body", "plain", "utf-8"))
        msg.attach(MIMEText("<p>Old HTML</p>", "html", "utf-8"))
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            greeting=["New greeting"],
        )
        result = merge_profile(msg, profile)
        # The plain-text part should be updated.
        found_greeting = False
        for part in result.walk():
            if not part.is_multipart() and part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    body_text = payload.decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    if "New greeting" in body_text:
                        found_greeting = True
                        break
        assert found_greeting, "New greeting should be in the plain-text part"


class TestParseAndSerialize:
    """Tests for parse_email and serialize_email."""

    def test_roundtrip(self) -> None:
        """Parsing and serialising preserves the message."""
        raw = b"Subject: Test\r\n\r\nHello, world!\r\n"
        msg = parse_email(raw)
        assert msg["Subject"] == "Test"
        result = serialize_email(msg)
        # After round-trip, headers should match (line endings may vary).
        assert b"Subject: Test" in result

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
