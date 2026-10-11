"""Tests for the profile module."""

from __future__ import annotations

from pathlib import Path

import pytest

from mailplate.profile import (
    ProfileError,
    Rule,
    _parse_header_line,
    _parse_rule_line,
    discover_profiles,
    load_profile,
)


class TestRule:
    """Tests for the Rule dataclass."""

    def test_valid_header_rule(self) -> None:
        """A header rule can be created."""
        rule = Rule(kind="header", value="From:.*@example\\.com")
        assert rule.kind == "header"
        assert rule.value == "From:.*@example\\.com"

    def test_valid_body_rule(self) -> None:
        """A body rule can be created."""
        rule = Rule(kind="body", value="urgent")
        assert rule.kind == "body"

    def test_invalid_kind_raises(self) -> None:
        """An unknown rule kind raises ProfileError."""
        with pytest.raises(ProfileError, match="Unknown rule kind"):
            Rule(kind="invalid", value="x")  # type: ignore[arg-type]


class TestParseRuleLine:
    """Tests for _parse_rule_line."""

    def test_header_rule(self) -> None:
        """A header rule line is parsed correctly."""
        result = _parse_rule_line("header = From:.*@example\\.com")
        assert result is not None
        assert result.kind == "header"
        assert result.value == "From:.*@example\\.com"

    def test_body_rule(self) -> None:
        """A body rule line is parsed correctly."""
        result = _parse_rule_line("body = \\[internal\\]")
        assert result is not None
        assert result.kind == "body"
        assert result.value == "\\[internal\\]"

    def test_no_match(self) -> None:
        """A line without a rule pattern returns None."""
        assert _parse_rule_line("not a rule") is None

    def test_empty_value(self) -> None:
        """A rule with empty value after = is parsed."""
        result = _parse_rule_line("header = ")
        assert result is not None
        assert result.kind == "header"
        assert result.value == ""


class TestParseHeaderLine:
    """Tests for _parse_header_line."""

    def test_simple_header(self) -> None:
        """A simple header line is parsed."""
        result = _parse_header_line("X-Mailer = mailplate/1.0")
        assert result is not None
        assert result == ("X-Mailer", "mailplate/1.0")

    def test_header_with_colon(self) -> None:
        """A header value containing a colon is handled (the first
        ``=`` is the delimiter)."""
        result = _parse_header_line("X-Custom = value:with:colons")
        assert result is not None
        assert result == ("X-Custom", "value:with:colons")

    def test_no_match(self) -> None:
        """A line without ``=`` returns None."""
        assert _parse_header_line("no equals") is None


class TestLoadProfile:
    """Tests for loading profile files."""

    def test_minimal_profile(self, tmp_path: Path) -> None:
        """A profile with just a name can be loaded."""
        path = tmp_path / "test.mplt"
        path.write_text("[profile]\nname = Test Profile\n", encoding="utf-8")
        profile = load_profile(path)
        assert profile.name == "Test Profile"
        assert profile.stem == "test"
        assert profile.rules == []
        assert profile.headers == {}

    def test_full_profile(self, tmp_path: Path) -> None:
        """A profile with all sections can be loaded."""
        content = """[profile]
name = Work

[rules]
header = From:.*@company\\.com
body = \\[internal\\]

[headers]
X-Mailer = mailplate/1.0
Organization = My Company Inc.

[greeting]
Hi {{ to_name | default("there") }},

[closing]
Best,
{{ from_name }}

[signature]
{{ from_name }}
{{ from_email }}
My Company Inc.
"""
        path = tmp_path / "work.mplt"
        path.write_text(content, encoding="utf-8")
        profile = load_profile(path)
        assert profile.name == "Work"
        assert profile.stem == "work"
        assert len(profile.rules) == 2
        assert profile.rules[0].kind == "header"
        assert profile.rules[1].kind == "body"
        assert profile.headers == {
            "X-Mailer": "mailplate/1.0",
            "Organization": "My Company Inc.",
        }
        assert profile.greeting == ['Hi {{ to_name | default("there") }},']
        assert profile.closing == ["Best,", "{{ from_name }}"]
        assert profile.signature == [
            "{{ from_name }}",
            "{{ from_email }}",
            "My Company Inc.",
        ]

    def test_comments_and_blanks(self, tmp_path: Path) -> None:
        """Comments and blank lines are ignored."""
        content = """# This is a comment
[profile]
name = Test
# Another comment

[rules]
# Rule comment
header = From:.*@test\\.com
"""
        path = tmp_path / "test.mplt"
        path.write_text(content, encoding="utf-8")
        profile = load_profile(path)
        assert profile.name == "Test"
        assert len(profile.rules) == 1

    def test_no_section_header(self, tmp_path: Path) -> None:
        """Content before any section header raises an error."""
        path = tmp_path / "bad.mplt"
        path.write_text("name = Test\n", encoding="utf-8")
        with pytest.raises(ProfileError, match="Content before any section"):
            load_profile(path)

    def test_unknown_section(self, tmp_path: Path) -> None:
        """An unknown section header raises an error."""
        path = tmp_path / "bad.mplt"
        path.write_text(
            "[profile]\nname = Test\n[unknown]\nkey = value\n", encoding="utf-8"
        )
        with pytest.raises(ProfileError, match="Unknown section"):
            load_profile(path)

    def test_file_not_found(self) -> None:
        """A missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_profile(Path("/nonexistent/profile.mplt"))


class TestDiscoverProfiles:
    """Tests for profile discovery."""

    def test_no_directory(self) -> None:
        """Discovery on a non-existent directory returns empty list."""
        profiles = discover_profiles([Path("/nonexistent")])
        assert profiles == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Discovery on an empty directory returns empty list."""
        profiles = discover_profiles([tmp_path])
        assert profiles == []

    def test_finds_mplt_files(self, tmp_path: Path) -> None:
        """Only .mplt files are discovered."""
        (tmp_path / "work.mplt").write_text(
            "[profile]\nname = Work\n", encoding="utf-8"
        )
        (tmp_path / "personal.mplt").write_text(
            "[profile]\nname = Personal\n", encoding="utf-8"
        )
        (tmp_path / "notes.txt").write_text("not a profile", encoding="utf-8")
        profiles = discover_profiles([tmp_path])
        assert len(profiles) == 2
        assert {p.stem for p in profiles} == {"work", "personal"}

    def test_skips_malformed(self, tmp_path: Path) -> None:
        """Malformed profile files are silently skipped."""
        (tmp_path / "good.mplt").write_text(
            "[profile]\nname = Good\n", encoding="utf-8"
        )
        (tmp_path / "bad.mplt").write_text("no section header\n", encoding="utf-8")
        profiles = discover_profiles([tmp_path])
        assert len(profiles) == 1
        assert profiles[0].stem == "good"

    def test_multiple_directories(self, tmp_path: Path) -> None:
        """Profiles from multiple directories are collected."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "a.mplt").write_text("[profile]\nname = A\n", encoding="utf-8")
        (dir2 / "b.mplt").write_text("[profile]\nname = B\n", encoding="utf-8")
        profiles = discover_profiles([dir1, dir2])
        assert len(profiles) == 2

    def test_deduplicates(self, tmp_path: Path) -> None:
        """The same profile file in multiple directories is not duplicated."""
        (tmp_path / "p.mplt").write_text("[profile]\nname = P\n", encoding="utf-8")
        profiles = discover_profiles([tmp_path, tmp_path])
        assert len(profiles) == 1
