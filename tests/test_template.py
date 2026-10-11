"""Tests for the template module."""

from __future__ import annotations

import os
from email.message import Message

from mailplate.template import (
    _apply_filter,
    _extract_name_and_email,
    _first_address_email,
    _first_address_name,
    _get_variable,
    render_template,
)


class TestExtractNameAndEmail:
    """Tests for _extract_name_and_email."""

    def test_full_address(self) -> None:
        """A full address with name and email."""
        name, email = _extract_name_and_email("John Doe <john@example.com>")
        assert name == "John Doe"
        assert email == "john@example.com"

    def test_email_only(self) -> None:
        """An email-only address."""
        name, email = _extract_name_and_email("john@example.com")
        assert name == ""
        assert email == "john@example.com"

    def test_name_only(self) -> None:
        """A name-only string returns only the email portion (no @ sign)."""
        name, email = _extract_name_and_email("John Doe")
        # parseaddr("John Doe") returns ("", "John") - treats "John" as local part.
        assert name == ""
        assert email == "John"

    def test_empty(self) -> None:
        """An empty string returns empty name and email."""
        name, email = _extract_name_and_email("")
        assert name == ""
        assert email == ""


class TestFirstAddressName:
    """Tests for _first_address_name."""

    def test_single_address(self) -> None:
        """Single address with name."""
        result = _first_address_name("Alice <alice@example.com>")
        assert result == "Alice"

    def test_multiple_addresses(self) -> None:
        """First name from multiple addresses."""
        result = _first_address_name("Alice <alice@e.com>, Bob <bob@e.com>")
        assert result == "Alice"

    def test_no_real_address(self) -> None:
        """No address returns empty string."""
        result = _first_address_name("")
        assert result == ""


class TestFirstAddressEmail:
    """Tests for _first_address_email."""

    def test_single_address(self) -> None:
        """Single address email."""
        result = _first_address_email("Alice <alice@example.com>")
        assert result == "alice@example.com"

    def test_multiple_addresses(self) -> None:
        """First email from multiple addresses."""
        result = _first_address_email("Alice <alice@e.com>, Bob <bob@e.com>")
        assert result == "alice@e.com"

    def test_no_real_address(self) -> None:
        """Empty input returns empty string."""
        result = _first_address_email("")
        assert result == ""


class TestApplyFilter:
    """Tests for _apply_filter."""

    def test_default_with_value(self) -> None:
        """default filter returns the value when non-empty."""
        result = _apply_filter("Alice", 'default("there")')
        assert result == "Alice"

    def test_default_without_value(self) -> None:
        """default filter returns the fallback when value is empty."""
        result = _apply_filter("", 'default("there")')
        assert result == "there"

    def test_default_single_quotes(self) -> None:
        """default filter supports single quotes."""
        result = _apply_filter("", "default('there')")
        assert result == "there"

    def test_unknown_filter(self) -> None:
        """Unknown filters return the value unchanged."""
        result = _apply_filter("hello", "upper()")
        assert result == "hello"


class TestGetVariable:
    """Tests for _get_variable."""

    def test_simple_variable(self) -> None:
        """A simple variable returns its context value."""
        result = _get_variable("name", {"name": "Alice"})
        assert result == "Alice"

    def test_missing_variable(self) -> None:
        """A missing variable returns empty string."""
        result = _get_variable("missing", {})
        assert result == ""

    def test_header_variable(self) -> None:
        """A header: variable looks up the header in context."""
        context = {"_headers": {"subject": "Hello"}}
        result = _get_variable("header:Subject", context)
        assert result == "Hello"

    def test_header_variable_missing(self) -> None:
        """A missing header: variable returns empty string."""
        context: dict[str, object] = {"_headers": {}}
        result = _get_variable("header:Missing", context)
        assert result == ""

    def test_env_variable(self) -> None:
        """An env: variable looks up the environment."""
        os.environ["TEST_MAILPLATE"] = "test_value"
        try:
            result = _get_variable("env:TEST_MAILPLATE", {})
            assert result == "test_value"
        finally:
            del os.environ["TEST_MAILPLATE"]

    def test_env_variable_missing(self) -> None:
        """A missing env: variable returns empty string."""
        result = _get_variable("env:NONEXISTENT_VAR", {})
        assert result == ""


class TestRenderTemplate:
    """Tests for render_template."""

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

    def test_no_placeholders(self) -> None:
        """Text without placeholders is returned unchanged."""
        msg = self._make_message()
        result = render_template("Hello, world!", msg)
        assert result == "Hello, world!"

    def test_subject_placeholder(self) -> None:
        """The subject placeholder is replaced."""
        msg = self._make_message({"Subject": "Meeting"})
        result = render_template("Subject: {{ subject }}", msg)
        assert result == "Subject: Meeting"

    def test_from_placeholder(self) -> None:
        """The from placeholder is replaced."""
        msg = self._make_message({"From": "Alice <alice@example.com>"})
        result = render_template("From: {{ from }}", msg)
        assert result == "From: Alice <alice@example.com>"

    def test_from_name_placeholder(self) -> None:
        """The from_name placeholder is replaced."""
        msg = self._make_message({"From": "Alice <alice@example.com>"})
        result = render_template("From: {{ from_name }}", msg)
        assert result == "From: Alice"

    def test_from_email_placeholder(self) -> None:
        """The from_email placeholder is replaced."""
        msg = self._make_message({"From": "Alice <alice@example.com>"})
        result = render_template("Email: {{ from_email }}", msg)
        assert result == "Email: alice@example.com"

    def test_to_placeholder(self) -> None:
        """The to placeholder is replaced."""
        msg = self._make_message({"To": "Bob <bob@example.com>"})
        result = render_template("To: {{ to }}", msg)
        assert result == "To: Bob <bob@example.com>"

    def test_to_name_placeholder(self) -> None:
        """The to_name placeholder is replaced."""
        msg = self._make_message({"To": "Bob <bob@example.com>"})
        result = render_template("Hi {{ to_name }}!", msg)
        assert result == "Hi Bob!"

    def test_body_placeholder(self) -> None:
        """The body placeholder is replaced."""
        msg = self._make_message({}, "Hello, this is the body.")
        result = render_template("Body:\n{{ body }}", msg)
        assert result == "Body:\nHello, this is the body."

    def test_date_placeholder(self) -> None:
        """The date placeholder is replaced."""
        msg = self._make_message({"Date": "Mon, 01 Jan 2024 00:00:00 +0000"})
        result = render_template("Date: {{ date }}", msg)
        assert result == "Date: Mon, 01 Jan 2024 00:00:00 +0000"

    def test_default_filter_with_value(self) -> None:
        """The default filter uses the value when present."""
        msg = self._make_message({"To": "Bob <bob@e.com>"})
        result = render_template('Hi {{ to_name | default("there") }}!', msg)
        assert result == "Hi Bob!"

    def test_default_filter_without_value(self) -> None:
        """The default filter uses the fallback when value is empty."""
        msg = self._make_message({})
        result = render_template('Hi {{ to_name | default("there") }}!', msg)
        assert result == "Hi there!"

    def test_multiple_placeholders(self) -> None:
        """Multiple placeholders in one template are replaced."""
        msg = self._make_message(
            {"From": "Alice <alice@e.com>", "To": "Bob <bob@e.com>"},
            "Hey!",
        )
        result = render_template(
            "From: {{ from_name }}\nTo: {{ to_name }}\n\n{{ body }}",
            msg,
        )
        assert result == "From: Alice\nTo: Bob\n\nHey!"

    def test_header_placeholder(self) -> None:
        """The header: placeholder looks up any header."""
        msg = self._make_message({"X-Custom": "custom_value"})
        result = render_template("{{ header:X-Custom }}", msg)
        assert result == "custom_value"
