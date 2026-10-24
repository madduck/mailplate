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
    _split_body_signature,
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


class TestSplitBodySignature:
    """Tests for _split_body_signature."""

    def test_no_delimiter(self) -> None:
        """Text without a signature delimiter is returned as body only."""
        body, sig = _split_body_signature("Hello world")
        assert body == "Hello world"
        assert sig == ""

    def test_with_signature(self) -> None:
        """Text after ``^-- $`` is returned as the signature."""
        body, sig = _split_body_signature("Body text\n-- \nSig text")
        assert body == "Body text"
        assert sig == "Sig text"

    def test_trailing_newline_on_body_side(self) -> None:
        """Trailing newline on the body side of the delimiter is stripped."""
        body, _sig = _split_body_signature("Body\n-- \nSig")
        assert body == "Body"

    def test_leading_newline_on_sig_side(self) -> None:
        """Leading newlines on the signature side are stripped."""
        _body, sig = _split_body_signature("Body\n-- \n\n\nSig")
        assert sig == "Sig"

    def test_blank_line_on_body_side(self) -> None:
        """All trailing newlines before the delimiter are stripped."""
        body, _sig = _split_body_signature("Body\n\n-- \nSig")
        assert body == "Body"


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
        assert result == "Hello\n"

    def test_with_greeting(self) -> None:
        """Greeting is prepended to the body."""
        profile = Profile(name="test", path=Path("test.mplt"), greeting=["Hi there,"])
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == "Hi there,\nBody text\n"

    def test_with_closing(self) -> None:
        """Closing is appended after the body."""
        profile = Profile(
            name="test", path=Path("test.mplt"), closing=["Best,", "Alice"]
        )
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == "Body text\nBest,\nAlice\n"

    def test_with_signature(self) -> None:
        """Signature is appended after the delimiter."""
        profile = Profile(
            name="test", path=Path("test.mplt"), signature=["--", "Alice"]
        )
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == "Body text\n\n-- \n--\nAlice\n"

    def test_blank_line_added_when_body_ends_with_newline(self) -> None:
        """A single trailing newline still gets a blank line before the
        delimiter."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            closing=["Best,", ""],
            signature=["Alice"],
        )
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == "Body text\nBest,\n\n-- \nAlice\n"

    def test_no_extra_blank_line_when_already_present(self) -> None:
        """No blank line is added if the body already ends with one."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            closing=["Best,", "", ""],
            signature=["Alice"],
        )
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == "Body text\nBest,\n\n-- \nAlice\n"

    def test_signature_with_empty_body(self) -> None:
        """An empty body becomes one blank line above the delimiter."""
        profile = Profile(name="test", path=Path("test.mplt"), signature=["Alice"])
        msg = self._make_message({}, "")
        result = _build_new_body(msg, profile)
        assert result == "\n\n-- \nAlice\n"

    def test_empty_body_without_signature(self) -> None:
        """An empty body without a signature stays one blank line."""
        profile = Profile(name="test", path=Path("test.mplt"))
        msg = self._make_message({}, "")
        result = _build_new_body(msg, profile)
        assert result == "\n"

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
        assert result == "Hi Bob,\nMeeting tomorrow?\nBest,\n\n-- \nAlice\n"

    def test_variable_substitution(self) -> None:
        """Template variables in sections are rendered."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            greeting=["Hi {{ to_name }},"],
        )
        msg = self._make_message({"To": "Bob <bob@e.com>"}, "Hello")
        result = _build_new_body(msg, profile)
        assert result == "Hi Bob,\nHello\n"

    def test_idempotent_greeting(self) -> None:
        """Greeting is not added again if the body already starts with it."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            greeting=["Hi {{ to_name }},"],
        )
        msg = self._make_message({"To": "Bob <bob@e.com>"}, "Hi Bob,\nAlready greeted")
        result = _build_new_body(msg, profile)
        assert result == "Hi Bob,\nAlready greeted\n"

    def test_variables_rendered_in_all_sections(self) -> None:
        """Profile variables are available in greeting, closing, and sig."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            variables={"company": "Example Inc.", "team": "Platform"},
            greeting=["Hi from the {{ var:team }} team,"],
            closing=["Best from {{ var:company }},"],
            signature=["{{ var:company }}"],
        )
        msg = self._make_message({}, "Body text")
        result = _build_new_body(msg, profile)
        assert result == (
            "Hi from the Platform team,\n"
            "Body text\n"
            "Best from Example Inc.,\n"
            "\n-- \n"
            "Example Inc.\n"
        )

    def test_idempotent_closing(self) -> None:
        """Closing is not added again if the body already ends with it."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            closing=["Best,"],
        )
        msg = self._make_message(
            {"From": "Alice <alice@e.com>"},
            "Some text\nBest,",
        )
        result = _build_new_body(msg, profile)
        assert result == "Some text\nBest,\n"

    def test_idempotent_signature(self) -> None:
        """Signature is always replaced by the profile's, never duplicated."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            signature=["{{ from_name }}"],
        )
        msg = self._make_message(
            {"From": "Alice <alice@e.com>"},
            "Body\n-- \nOld sig",
        )
        result = _build_new_body(msg, profile)
        assert result == "Body\n\n-- \nAlice\n"

    def test_draft_signature_preserved_if_profile_has_none(self) -> None:
        """When the profile has no signature section, the draft's signature
        is preserved."""
        profile = Profile(name="test", path=Path("test.mplt"))
        msg = self._make_message({}, "Body\n-- \nDraft sig")
        result = _build_new_body(msg, profile)
        assert result == "Body\n\n-- \nDraft sig\n"

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

    def test_headers_render_variables(self) -> None:
        """Profile variables are available in header values."""
        msg = self._make_message({"Subject": "Test"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            variables={"org": "Example Inc."},
            headers={"Organization": "{{ var:org }}"},
        )
        result = merge_profile(msg, profile)
        assert result["Organization"] == "Example Inc."

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

    def test_headers_removed(self) -> None:
        """Headers listed in remove_headers are deleted."""
        msg = self._make_message(
            {"Subject": "Keep", "X-Old": "gone", "X-Obsolete": "also-gone"}
        )
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            remove_headers=["X-Old", "x-obsolete"],
        )
        result = merge_profile(msg, profile)
        assert result["Subject"] == "Keep"
        assert "X-Old" not in result
        assert "X-Obsolete" not in result

    def test_priority_headers_lead_in_canonical_order(self) -> None:
        """Priority headers always lead the output in canonical order."""
        msg = self._make_message(
            {
                "Return-Path": "<alice@example.com>",
                "Subject": "Old",
                "From": "Alice <alice@example.com>",
                "Date": "Thu, 01 Jan 2026 00:00:00 +0000",
                "To": "Bob <bob@example.com>",
            }
        )
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"Subject": "New", "X-Mailer": "mailplate/1.0"},
        )
        result = merge_profile(msg, profile)
        # Missing priority headers are emitted empty; the rest keeps the
        # input order, and profile headers not in the input come last.
        assert list(result.keys()) == [
            "From",
            "To",
            "Cc",
            "Bcc",
            "Subject",
            "Reply-To",
            "Message-ID",
            "Return-Path",
            "Date",
            "X-Mailer",
        ]
        assert result["Subject"] == "New"
        assert result["Cc"] == ""

    def test_serialised_priority_headers_have_trailing_space(self) -> None:
        """Empty priority headers serialise with a space after the colon."""
        msg = self._make_message({"Subject": "T"})
        profile = Profile(name="test", path=Path("test.mplt"))
        out = serialize_email(merge_profile(msg, profile))
        assert out.startswith(
            b"From: \nTo: \nCc: \nBcc: \nSubject: T\nReply-To: \nMessage-ID: \n\n"
        )

    def test_input_priority_headers_reordered(self) -> None:
        """Priority headers present in the input are put in canonical order."""
        msg = self._make_message(
            {
                "Message-ID": "<1@example.com>",
                "Bcc": "hidden@example.com",
                "To": "Bob",
                "From": "Alice",
            }
        )
        profile = Profile(name="test", path=Path("test.mplt"))
        result = merge_profile(msg, profile)
        assert list(result.keys()) == [
            "From",
            "To",
            "Cc",
            "Bcc",
            "Subject",
            "Reply-To",
            "Message-ID",
        ]

    def test_profile_priority_header_overrides_input(self) -> None:
        """A priority header set by the profile wins over the input."""
        msg = self._make_message({"From": "Alice", "Reply-To": "old@example.com"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"Reply-To": "new@example.com", "cc": "carol@example.com"},
        )
        result = merge_profile(msg, profile)
        assert result["Reply-To"] == "new@example.com"
        # A profile header spelled in lower case keeps the canonical
        # spelling of the priority slot.
        assert result.get_all("Cc") == ["carol@example.com"]
        assert list(result.keys())[:3] == ["From", "To", "Cc"]

    def test_removed_priority_header_is_emitted_empty(self) -> None:
        """A removed priority header is still present, but empty."""
        msg = self._make_message({"From": "Alice", "Cc": "carol@example.com"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            remove_headers=["Cc"],
        )
        result = merge_profile(msg, profile)
        assert result["Cc"] == ""
        assert list(result.keys()) == [
            "From",
            "To",
            "Cc",
            "Bcc",
            "Subject",
            "Reply-To",
            "Message-ID",
        ]

    def test_override_keeps_original_case_and_position(self) -> None:
        """An overridden non-priority header stays where the input put it."""
        msg = self._make_message({"X-First": "1", "subject": "Old", "X-Last": "2"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"Subject": "New"},
        )
        result = merge_profile(msg, profile)
        assert result["Subject"] == "New"
        assert list(result.keys())[-2:] == ["X-First", "X-Last"]
        assert "Subject" in list(result.keys())[:7]

    def test_duplicate_header_collapsed_at_first_position(self) -> None:
        """Duplicate overridden headers collapse at the first occurrence."""
        msg = self._make_message({"X-First": "1", "X-Tag": "first", "X-Last": "2"})
        msg.add_header("X-Tag", "second")
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"X-Tag": "only"},
        )
        result = merge_profile(msg, profile)
        assert result.get_all("X-Tag") == ["only"]
        assert list(result.keys())[-3:] == ["X-First", "X-Tag", "X-Last"]

    def test_duplicate_input_header_keeps_first_value(self) -> None:
        """A repeated input header keeps its first value and position."""
        msg = self._make_message({"X-First": "1"})
        msg.add_header("X-Tag", "first")
        msg.add_header("X-Tag", "second")
        profile = Profile(name="test", path=Path("test.mplt"))
        result = merge_profile(msg, profile)
        assert result.get_all("X-Tag") == ["first"]

    def test_removal_preserves_order_of_remaining_headers(self) -> None:
        """Removing a header does not reorder the remaining ones."""
        msg = self._make_message({"A": "1", "X-Old": "gone", "B": "2", "C": "3"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            remove_headers=["X-Old"],
        )
        result = merge_profile(msg, profile)
        assert list(result.keys())[7:] == ["A", "B", "C"]

    def test_header_added_when_absent_appended(self) -> None:
        """A profile header not in the input is appended at the end."""
        msg = self._make_message({"From": "Alice", "To": "Bob"})
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"X-One": "1", "X-Two": "2"},
        )
        result = merge_profile(msg, profile)
        assert list(result.keys())[-2:] == ["X-One", "X-Two"]

    def test_header_value_template(self) -> None:
        """Header values are rendered through the template engine."""
        msg = self._make_message(
            {"Subject": "Hello World", "From": "alice@example.com"},
        )
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={
                "X-Orig-Subject": "{{ subject }}",
                "X-From-Domain": "{{ header:From }}",
            },
        )
        result = merge_profile(msg, profile)
        assert result["X-Orig-Subject"] == "Hello World"
        assert result["X-From-Domain"] == "alice@example.com"

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


class TestUtf8HeaderOutput:
    """Non-ASCII header bodies are written verbatim as UTF-8."""

    def test_parsed_header_roundtrip_is_utf8(self) -> None:
        """A parsed non-ASCII header is not RFC 2047-encoded on output."""
        raw = "Subject: Umläut\n\nBody\n".encode()
        msg = parse_email(raw)
        result = serialize_email(msg)
        assert b"Subject: Uml\xc3\xa4ut" in result
        assert b"=?" not in result

    def test_existing_header_stays_utf8_after_merge(self) -> None:
        """A non-overridden header keeps its raw UTF-8 value after merging."""
        raw = ("Subject: Umläut\nTo: Jörg <joerg@example.com>\n\nBody\n").encode()
        msg = parse_email(raw)
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"X-Mailer": "mailplate"},
        )
        result = serialize_email(merge_profile(msg, profile))
        assert b"Subject: Uml\xc3\xa4ut" in result
        assert b"=?" not in result

    def test_profile_header_is_utf8(self) -> None:
        """A non-ASCII profile header is written as plain UTF-8."""
        msg = parse_email(b"Subject: Test\n\nBody\n")
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"X-Accent": "café"},
        )
        result = serialize_email(merge_profile(msg, profile))
        assert b"X-Accent: caf\xc3\xa9" in result
        assert b"=?" not in result

    def test_template_substitution_is_utf8(self) -> None:
        """A non-ASCII value substituted into a header stays UTF-8."""
        raw = "Subject: Umläut\n\nBody\n".encode()
        msg = parse_email(raw)
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"X-Orig": "{{ subject }}"},
        )
        result = serialize_email(merge_profile(msg, profile))
        assert b"X-Orig: Uml\xc3\xa4ut" in result
        assert b"=?" not in result

    def test_rfc2047_header_is_decoded(self) -> None:
        """An RFC 2047 encoded input header is output as plain UTF-8."""
        raw = b"Subject: =?utf-8?q?Uml=C3=A4ut?=\n\nBody\n"
        result = serialize_email(parse_email(raw))
        assert b"Subject: Uml\xc3\xa4ut" in result
        assert b"=?" not in result

    def test_structured_headers_are_not_normalised(self) -> None:
        """Merging preserves the raw form of address and date headers."""
        raw = (
            b"Date: Thu, 01 Jan 2026 00:00:00 +0000 (UTC)\n"
            b"From: john(comment)@example.com\n"
            b"\nBody\n"
        )
        msg = parse_email(raw)
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            headers={"X-Test": "1"},
        )
        result = serialize_email(merge_profile(msg, profile))
        assert b"Date: Thu, 01 Jan 2026 00:00:00 +0000 (UTC)" in result
        assert b"From: john(comment)@example.com" in result
