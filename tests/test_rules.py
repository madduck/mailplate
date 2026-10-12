"""Tests for the rules module."""

from __future__ import annotations

import logging
from email.message import Message

import pytest

from mailplate.profile import Rule
from mailplate.rules import (
    _decode_header_value,
    _get_body,
    _get_header_value,
    _match_rule,
)


class TestGetHeaderValue:
    """Tests for _get_header_value."""

    def test_existing_header(self) -> None:
        """An existing header returns its value."""
        msg = Message()
        msg["Subject"] = "Hello"
        assert _get_header_value(msg, "Subject") == "Hello"

    def test_missing_header(self) -> None:
        """A missing header returns an empty string."""
        msg = Message()
        assert _get_header_value(msg, "Missing") == ""

    def test_case_insensitive(self) -> None:
        """Header lookup is case-insensitive."""
        msg = Message()
        msg["FROM"] = "alice@example.com"
        assert _get_header_value(msg, "From") == "alice@example.com"

    def test_encoded_header_is_decoded(self) -> None:
        """An RFC 2047 encoded header is returned as plain text."""
        msg = Message()
        msg["Subject"] = "=?utf-8?q?Uml=C3=A4ut?="
        assert _get_header_value(msg, "Subject") == "Umläut"

    def test_raw_8bit_header_is_decoded(self) -> None:
        """A surrogate-escaped raw 8-bit header is decoded as UTF-8."""
        msg = Message()
        raw = "Umläut".encode().decode("ascii", "surrogateescape")
        msg["Subject"] = raw
        assert _get_header_value(msg, "Subject") == "Umläut"


class TestDecodeHeaderValue:
    """Tests for _decode_header_value."""

    def test_ascii_value(self) -> None:
        """A plain ASCII value is returned unchanged."""
        assert _decode_header_value("Hello") == "Hello"

    def test_rfc2047_value(self) -> None:
        """An RFC 2047 encoded word is decoded."""
        assert _decode_header_value("=?utf-8?q?Uml=C3=A4ut?=") == "Umläut"

    def test_raw_8bit_value(self) -> None:
        """Surrogate-escaped bytes are decoded as UTF-8."""
        raw = "Umläut".encode().decode("ascii", "surrogateescape")
        assert _decode_header_value(raw) == "Umläut"

    def test_trailing_surrogates(self) -> None:
        """A value ending in surrogate escapes is decoded fully."""
        raw = "Umlä".encode().decode("ascii", "surrogateescape")
        assert _decode_header_value(raw) == "Umlä"


class TestGetBody:
    """Tests for _get_body."""

    def test_simple_body(self) -> None:
        """A simple message body is returned."""
        msg = Message()
        msg.set_payload("Hello, world!\n")
        body = _get_body(msg)
        assert body == "Hello, world!\n"

    def test_empty_body(self) -> None:
        """A message with no body returns empty string."""
        msg = Message()
        assert _get_body(msg) == ""

    def test_multipart_plain_text(self) -> None:
        """The first text/plain part of a multipart message is used."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText("Hello plain", "plain", "utf-8"))
        msg.attach(MIMEText("<p>Hello HTML</p>", "html", "utf-8"))
        body = _get_body(msg)
        assert "Hello plain" in body

    def test_multipart_no_plain(self) -> None:
        """A multipart message with no text/plain part returns empty."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText("<p>Hello</p>", "html", "utf-8"))
        body = _get_body(msg)
        assert body == ""


class TestMatchRule:
    """Tests for _match_rule."""

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

    def test_header_rule_match(self) -> None:
        """A header rule matches when the header value matches."""
        rule = Rule(kind="header", value="From:.*@example\\.com")
        msg = self._make_message({"From": "alice@example.com"})
        assert _match_rule(rule, msg) is True

    def test_header_rule_no_match(self) -> None:
        """A header rule does not match when the header value differs."""
        rule = Rule(kind="header", value="From:.*@example\\.com")
        msg = self._make_message({"From": "alice@other.com"})
        assert _match_rule(rule, msg) is False

    def test_header_rule_case_insensitive(self) -> None:
        """A header rule matches regardless of field-name casing."""
        rule = Rule(kind="header", value="FROM: .*@example\\.com")
        msg = self._make_message({"fRoM": "alice@example.com"})
        assert _match_rule(rule, msg) is True

    def test_header_rule_missing_header(self) -> None:
        """A header rule does not match when the header is absent."""
        rule = Rule(kind="header", value="From:.*@example\\.com")
        msg = self._make_message({})
        assert _match_rule(rule, msg) is False

    def test_header_rule_invalid_regex(self) -> None:
        """An invalid regex in a header rule returns False."""
        rule = Rule(kind="header", value="From:**[invalid")
        msg = self._make_message({"From": "alice@example.com"})
        assert _match_rule(rule, msg) is False

    def test_header_rule_no_colon(self) -> None:
        """A header rule without a colon returns False."""
        rule = Rule(kind="header", value="NoColonHere")
        msg = self._make_message({"From": "alice@example.com"})
        assert _match_rule(rule, msg) is False

    def test_body_rule_match(self) -> None:
        """A body rule matches when the body matches."""
        rule = Rule(kind="body", value="urgent")
        msg = self._make_message({}, "This is urgent!")
        assert _match_rule(rule, msg) is True

    def test_body_rule_no_match(self) -> None:
        """A body rule does not match when the body doesn't match."""
        rule = Rule(kind="body", value="urgent")
        msg = self._make_message({}, "This is not important")
        assert _match_rule(rule, msg) is False

    def test_body_rule_invalid_regex(self) -> None:
        """An invalid regex in a body rule returns False."""
        rule = Rule(kind="body", value="**[invalid")
        msg = self._make_message({}, "body text")
        assert _match_rule(rule, msg) is False

    def test_rcpt_rule_matches_to(self) -> None:
        """A rcpt rule matches against the To header."""
        rule = Rule(kind="rcpt", value=".*@example\\.com")
        msg = self._make_message({"To": "alice@example.com"})
        assert _match_rule(rule, msg) is True

    def test_rcpt_rule_matches_cc(self) -> None:
        """A rcpt rule matches against the Cc header."""
        rule = Rule(kind="rcpt", value=".*@example\\.com")
        msg = self._make_message({"Cc": "alice@example.com"})
        assert _match_rule(rule, msg) is True

    def test_rcpt_rule_matches_bcc(self) -> None:
        """A rcpt rule matches against the Bcc header."""
        rule = Rule(kind="rcpt", value=".*@example\\.com")
        msg = self._make_message({"Bcc": "alice@example.com"})
        assert _match_rule(rule, msg) is True

    def test_rcpt_rule_matches_any_header(self) -> None:
        """A rcpt rule applies if the regex matches any To/Cc/Bcc header."""
        rule = Rule(kind="rcpt", value="@example\\.com")
        msg = self._make_message({"To": "alice@other.com", "Cc": "bob@example.com"})
        assert _match_rule(rule, msg) is True

    def test_rcpt_rule_no_match(self) -> None:
        """A rcpt rule does not match when no To/Cc/Bcc header matches."""
        rule = Rule(kind="rcpt", value=".*@example\\.com")
        msg = self._make_message({"To": "alice@other.com"})
        assert _match_rule(rule, msg) is False

    def test_rcpt_rule_missing_headers(self) -> None:
        """A rcpt rule does not match when no recipient headers exist."""
        rule = Rule(kind="rcpt", value=".*@example\\.com")
        msg = self._make_message({})
        assert _match_rule(rule, msg) is False

    def test_rcpt_rule_invalid_regex(self) -> None:
        """An invalid regex in a rcpt rule returns False."""
        rule = Rule(kind="rcpt", value="**[invalid")
        msg = self._make_message({"To": "alice@example.com"})
        assert _match_rule(rule, msg) is False

    def test_empty_message(self) -> None:
        """An empty message does not match rules."""
        rule = Rule(kind="body", value=".+")
        msg = self._make_message({}, "")
        assert _match_rule(rule, msg) is False


class TestMatchRuleCaptures:
    """Tests for _match_rule_captures."""

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

    def test_header_capture(self) -> None:
        """A header capture group is returned."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="header", value="From:.*@(?P<domain>[a-z.]+)")
        msg = self._make_message({"From": "a@example.com"})
        result = _match_rule_captures(rule, msg)
        assert result == {"domain": "example.com"}

    def test_capture_is_logged_at_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """A matching named group is logged at DEBUG level."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="header", value="From:.*@(?P<domain>[a-z.]+)")
        msg = self._make_message({"From": "a@example.com"})
        with caplog.at_level(logging.DEBUG, logger="mailplate.rules"):
            _match_rule_captures(rule, msg)
        assert "captured {'domain': 'example.com'}" in caplog.text

    def test_header_capture_case_insensitive(self) -> None:
        """A capture is returned regardless of field-name casing."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="header", value="FROM: .*@(?P<domain>[a-z.]+)")
        msg = self._make_message({"from": "a@example.com"})
        result = _match_rule_captures(rule, msg)
        assert result == {"domain": "example.com"}

    def test_body_capture(self) -> None:
        """A body capture group is returned."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="body", value="(?P<urgent>urgent)")
        msg = self._make_message({}, "This is urgent")
        result = _match_rule_captures(rule, msg)
        assert result == {"urgent": "urgent"}

    def test_no_match_returns_empty(self) -> None:
        """A non-matching rule returns an empty dict."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="header", value="X-Custom: (?P<val>\\d+)")
        msg = self._make_message({"From": "a@b.com"})
        result = _match_rule_captures(rule, msg)
        assert result == {}

    def test_invalid_regex_returns_empty(self) -> None:
        """An invalid regex returns an empty dict."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="header", value="From:**[invalid")
        msg = self._make_message({"From": "a@b.com"})
        result = _match_rule_captures(rule, msg)
        assert result == {}

    def test_header_no_colon_returns_empty(self) -> None:
        """A header rule without a colon returns an empty dict."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="header", value="NoColon")
        msg = self._make_message({"From": "a@b.com"})
        result = _match_rule_captures(rule, msg)
        assert result == {}

    def test_body_no_match_capture(self) -> None:
        """A non-matching body rule returns an empty dict."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="body", value="(?P<word>urgent)")
        msg = self._make_message({}, "nothing")
        result = _match_rule_captures(rule, msg)
        assert result == {}

    def test_body_invalid_regex_capture(self) -> None:
        """An invalid body regex returns an empty dict."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="body", value="**[invalid")
        msg = self._make_message({}, "body")
        result = _match_rule_captures(rule, msg)
        assert result == {}

    def test_rcpt_capture(self) -> None:
        """A matching rcpt rule returns its named captures."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="rcpt", value="(?P<addr>[^@]+)@example\\.com")
        msg = self._make_message({"Cc": "alice@example.com"})
        result = _match_rule_captures(rule, msg)
        assert result == {"addr": "alice"}

    def test_rcpt_no_match_capture(self) -> None:
        """A non-matching rcpt rule returns an empty dict."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="rcpt", value="(?P<addr>[^@]+)@example\\.com")
        msg = self._make_message({"To": "alice@other.com"})
        result = _match_rule_captures(rule, msg)
        assert result == {}

    def test_rcpt_invalid_regex_capture(self) -> None:
        """An invalid rcpt regex returns an empty dict."""
        from mailplate.rules import _match_rule_captures

        rule = Rule(kind="rcpt", value="**[invalid")
        msg = self._make_message({"To": "alice@example.com"})
        result = _match_rule_captures(rule, msg)
        assert result == {}
