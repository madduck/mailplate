"""Tests for the rules module."""

from __future__ import annotations

from email.message import Message

from mailplate.profile import Profile, Rule
from mailplate.rules import _get_body, _get_header_value, profile_matches


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


class TestProfileMatches:
    """Tests for profile_matches."""

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

    def test_no_rules_matches_anything(self) -> None:
        """A profile with no rules matches everything."""
        profile = Profile(name="catchall", path=Path("catchall.mplt"))
        msg = self._make_message({"Subject": "Hi"}, "body")
        assert profile_matches(profile, msg) is True

    def test_header_rule_match(self) -> None:
        """A header rule matches when the header value matches."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="header", value="From:.*@example\\.com")],
        )
        msg = self._make_message({"From": "alice@example.com"})
        assert profile_matches(profile, msg) is True

    def test_header_rule_no_match(self) -> None:
        """A header rule does not match when the header value differs."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="header", value="From:.*@example\\.com")],
        )
        msg = self._make_message({"From": "alice@other.com"})
        assert profile_matches(profile, msg) is False

    def test_header_rule_missing_header(self) -> None:
        """A header rule does not match when the header is absent."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="header", value="From:.*@example\\.com")],
        )
        msg = self._make_message({})
        assert profile_matches(profile, msg) is False

    def test_header_rule_invalid_regex(self) -> None:
        """An invalid regex in a header rule returns False."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="header", value="From:**[invalid")],
        )
        msg = self._make_message({"From": "alice@example.com"})
        assert profile_matches(profile, msg) is False

    def test_header_rule_no_colon(self) -> None:
        """A header rule without a colon returns False."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="header", value="NoColonHere")],
        )
        msg = self._make_message({"From": "alice@example.com"})
        assert profile_matches(profile, msg) is False

    def test_body_rule_match(self) -> None:
        """A body rule matches when the body matches."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="body", value="urgent")],
        )
        msg = self._make_message({}, "This is urgent!")
        assert profile_matches(profile, msg) is True

    def test_body_rule_no_match(self) -> None:
        """A body rule does not match when the body doesn't match."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="body", value="urgent")],
        )
        msg = self._make_message({}, "This is not important")
        assert profile_matches(profile, msg) is False

    def test_body_rule_invalid_regex(self) -> None:
        """An invalid regex in a body rule returns False."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="body", value="**[invalid")],
        )
        msg = self._make_message({}, "body text")
        assert profile_matches(profile, msg) is False

    def test_all_rules_must_match_and(self) -> None:
        """All rules must match for the profile to match (AND)."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[
                Rule(kind="header", value="From:.*@company\\.com"),
                Rule(kind="body", value="internal"),
            ],
        )
        # Both match
        msg = self._make_message({"From": "alice@company.com"}, "internal memo")
        assert profile_matches(profile, msg) is True
        # Only header matches
        msg2 = self._make_message({"From": "alice@company.com"}, "external memo")
        assert profile_matches(profile, msg2) is False
        # Only body matches
        msg3 = self._make_message({"From": "alice@other.com"}, "internal memo")
        assert profile_matches(profile, msg3) is False

    def test_empty_message(self) -> None:
        """An empty message does not match rules."""
        profile = Profile(
            name="test",
            path=Path("test.mplt"),
            rules=[Rule(kind="body", value=".+")],
        )
        msg = self._make_message({}, "")
        assert profile_matches(profile, msg) is False


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


from pathlib import Path
