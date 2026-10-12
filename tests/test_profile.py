"""Tests for the profile module."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from mailplate.profile import (
    ProfileError,
    Rule,
    _include_paths,
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

    def test_zero_weight_allowed(self) -> None:
        """A rule weight of zero is allowed."""
        rule = Rule(kind="body", value="urgent", weight=0)
        assert rule.weight == 0

    def test_negative_weight_allowed(self) -> None:
        """A negative rule weight is allowed."""
        rule = Rule(kind="body", value="urgent", weight=-100)
        assert rule.weight == -100


class TestParseRuleLine:
    """Tests for _parse_rule_line."""

    def test_header_rule(self) -> None:
        """A header rule line is parsed correctly."""
        result = _parse_rule_line("From = .*@example\\.com")
        assert result is not None
        assert result.kind == "header"
        assert result.value == "from: .*@example\\.com"
        assert result.weight == 1

    def test_body_rule(self) -> None:
        """A body rule line is parsed correctly."""
        result = _parse_rule_line("body = \\[internal\\]")
        assert result is not None
        assert result.kind == "body"
        assert result.value == "\\[internal\\]"
        assert result.weight == 1

    def test_header_rule_with_weight(self) -> None:
        """A header rule with an explicit weight is parsed."""
        result = _parse_rule_line("From:5 = .*@example\\.com")
        assert result is not None
        assert result.kind == "header"
        assert result.value == "from: .*@example\\.com"
        assert result.weight == 5

    def test_header_name_is_case_insensitive(self) -> None:
        """The same field name in different cases yields the same rule."""
        upper = _parse_rule_line("FROM = .*@example\\.com")
        lower = _parse_rule_line("from = .*@example\\.com")
        assert upper is not None
        assert lower is not None
        assert upper == lower

    def test_body_keyword_is_case_insensitive(self) -> None:
        """The reserved ``body`` keyword is recognised in any case."""
        result = _parse_rule_line("BODY:3 = urgent")
        assert result is not None
        assert result.kind == "body"
        assert result.value == "urgent"
        assert result.weight == 3

    def test_rcpt_rule(self) -> None:
        """A rcpt rule line is parsed into a ``rcpt`` rule."""
        result = _parse_rule_line("rcpt = .*@example\\.com")
        assert result is not None
        assert result.kind == "rcpt"
        assert result.value == ".*@example\\.com"
        assert result.weight == 1

    def test_rcpt_keyword_is_case_insensitive(self) -> None:
        """The reserved ``rcpt`` keyword is recognised in any case."""
        result = _parse_rule_line("RCPT:2 = urgent")
        assert result is not None
        assert result.kind == "rcpt"
        assert result.value == "urgent"
        assert result.weight == 2

    def test_body_rule_with_weight(self) -> None:
        """A body rule with an explicit weight is parsed."""
        result = _parse_rule_line("body:3 = urgent")
        assert result is not None
        assert result.kind == "body"
        assert result.value == "urgent"
        assert result.weight == 3

    def test_zero_weight_parsed(self) -> None:
        """A parsed rule weight of zero is accepted."""
        result = _parse_rule_line("From:0 = .*@example\\.com")
        assert result is not None
        assert result.weight == 0

    def test_negative_weight_parsed(self) -> None:
        """A parsed negative rule weight is accepted."""
        result = _parse_rule_line("body:-100 = urgent")
        assert result is not None
        assert result.kind == "body"
        assert result.value == "urgent"
        assert result.weight == -100

    def test_no_match(self) -> None:
        """A line without a rule pattern returns None."""
        assert _parse_rule_line("not a rule") is None

    def test_legacy_header_syntax_rejected(self) -> None:
        """The removed ``header = ...`` syntax raises ProfileError."""
        with pytest.raises(ProfileError, match="no longer supported"):
            _parse_rule_line("header = From:.*@example\\.com")

    def test_empty_value(self) -> None:
        """A rule with empty value after = is parsed."""
        result = _parse_rule_line("Subject = ")
        assert result is not None
        assert result.kind == "header"
        assert result.value == "subject:"
        assert result.weight == 1


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

    def test_non_matching_lines_in_sections(self, tmp_path: Path) -> None:
        """Lines that don't match any pattern in a section are ignored."""
        content = """[profile]
name = Test
extra_line_ignored

[rules]
From = .*@example\\.com
bogus_line

[headers]
X-Custom = value
another_bogus
"""
        path = tmp_path / "test.mplt"
        path.write_text(content, encoding="utf-8")
        profile = load_profile(path)
        assert profile.name == "Test"
        assert len(profile.rules) == 1
        assert profile.headers == {"X-Custom": "value"}

    def test_full_profile(self, tmp_path: Path) -> None:
        """A profile with all sections can be loaded."""
        content = """[profile]
name = Work

[rules]
From = .*@company\\.com
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

    def test_remove_headers(self, tmp_path: Path) -> None:
        """The ``[remove_headers]`` section is parsed."""
        content = """[profile]
name = Test

[remove_headers]
X-NoProxy
Old-Header
"""
        path = tmp_path / "test.mplt"
        path.write_text(content, encoding="utf-8")
        profile = load_profile(path)
        assert profile.remove_headers == ["X-NoProxy", "Old-Header"]

    def test_helpers_section(self, tmp_path: Path) -> None:
        """The ``[helpers]`` section is parsed."""
        content = """[profile]
name = Test

[helpers]
get_quote = fortune -n2
get_long_date = date '+%%d %%B %%Y'
"""
        path = tmp_path / "test.mplt"
        path.write_text(content, encoding="utf-8")
        profile = load_profile(path)
        assert profile.helpers == {
            "get_quote": "fortune -n2",
            "get_long_date": "date '+%%d %%B %%Y'",
        }

    def test_comments_and_blanks(self, tmp_path: Path) -> None:
        """Comments and blank lines are ignored."""
        content = """# This is a comment
[profile]
name = Test
# Another comment

[rules]
# Rule comment
From = .*@test\\.com
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

    def test_finds_profiles_in_subdirectories(self, tmp_path: Path) -> None:
        """Profiles in nested subdirectories are discovered too."""
        nested = tmp_path / "team" / "project"
        nested.mkdir(parents=True)
        (tmp_path / "top.mplt").write_text("[profile]\nname = Top\n", encoding="utf-8")
        (nested / "deep.mplt").write_text("[profile]\nname = Deep\n", encoding="utf-8")
        (nested / "ignored.txt").write_text("not a profile", encoding="utf-8")
        profiles = discover_profiles([tmp_path])
        assert {p.stem for p in profiles} == {"top", "team/project/deep"}

    def test_subdirectory_profiles_keep_distinct_stems(self, tmp_path: Path) -> None:
        """Same-named profiles in different subdirectories stay distinct."""
        (tmp_path / "work").mkdir()
        (tmp_path / "personal").mkdir()
        (tmp_path / "work" / "foo.mplt").write_text(
            "[profile]\nname = Work Foo\n", encoding="utf-8"
        )
        (tmp_path / "personal" / "foo.mplt").write_text(
            "[profile]\nname = Personal Foo\n", encoding="utf-8"
        )
        profiles = discover_profiles([tmp_path])
        assert {p.stem for p in profiles} == {"work/foo", "personal/foo"}

    def test_nested_scan_roots_deduplicated(self, tmp_path: Path) -> None:
        """A profile is not duplicated when both a parent and a nested
        directory are scanned."""
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "p.mplt").write_text("[profile]\nname = P\n", encoding="utf-8")
        profiles = discover_profiles([tmp_path, nested])
        assert len(profiles) == 1
        # The parent scan root is searched first, so that is the path the
        # profile is identified by.
        assert profiles[0].stem == "sub/p"

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


class TestIncludePaths:
    """Tests for _include_paths."""

    def test_root_and_nested_ancestors(self, tmp_path: Path) -> None:
        """All INCLUDE files from the root down are listed."""
        path = tmp_path / "foo" / "bar" / "prof.mplt"
        assert _include_paths(path, tmp_path) == [
            tmp_path / "INCLUDE",
            tmp_path / "foo" / "INCLUDE",
            tmp_path / "foo" / "bar" / "INCLUDE",
        ]

    def test_profile_directly_in_root(self, tmp_path: Path) -> None:
        """A top-level profile only sees the root INCLUDE."""
        assert _include_paths(tmp_path / "prof.mplt", tmp_path) == [
            tmp_path / "INCLUDE"
        ]

    def test_profile_outside_root(self, tmp_path: Path) -> None:
        """A profile outside the scan root has no applicable includes."""
        other = tmp_path / "other"
        other.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        assert _include_paths(other / "prof.mplt", root) == []


class TestIncludes:
    """Tests for merging INCLUDE files into a profile."""

    def test_ancestors_merge_least_specific_first(self, tmp_path: Path) -> None:
        """Includes are applied root-most first, with the profile last."""
        (tmp_path / "INCLUDE").write_text(
            "[rules]\n"
            "From = root@example\n"
            "[headers]\n"
            "X-Root = root\n"
            "X-Shared = root\n"
            "[helpers]\n"
            "quote = root-quote\n"
            "[remove_headers]\n"
            "X-Root-Only\n"
            "[greeting]\n"
            "Root greeting\n"
            "[signature]\n"
            "Root signature\n",
            encoding="utf-8",
        )
        foo = tmp_path / "foo"
        foo.mkdir()
        (foo / "INCLUDE").write_text(
            "[rules]\n"
            "body = foo-body\n"
            "[headers]\n"
            "X-Foo = foo\n"
            "X-Shared = foo\n"
            "[helpers]\n"
            "quote = foo-quote\n"
            "[remove_headers]\n"
            "X-Foo-Only\n"
            "[greeting]\n"
            "Foo greeting\n",
            encoding="utf-8",
        )
        bar = foo / "bar"
        bar.mkdir()
        (bar / "INCLUDE").write_text(
            "[headers]\nX-Bar = bar\n[signature]\n",
            encoding="utf-8",
        )
        profile_path = bar / "prof.mplt"
        profile_path.write_text(
            "[profile]\n"
            "name = Leaf\n"
            "[rules]\n"
            "Subject = leaf\n"
            "[headers]\n"
            "X-Shared = leaf\n"
            "[remove_headers]\n"
            "X-Leaf-Only\n",
            encoding="utf-8",
        )

        profile = load_profile(profile_path, include_root=tmp_path)

        assert profile.name == "Leaf"
        assert profile.path == profile_path
        assert [(rule.kind, rule.value) for rule in profile.rules] == [
            ("header", "from: root@example"),
            ("body", "foo-body"),
            ("header", "subject: leaf"),
        ]
        assert profile.headers == {
            "X-Root": "root",
            "X-Shared": "leaf",
            "X-Foo": "foo",
            "X-Bar": "bar",
        }
        assert profile.helpers == {"quote": "foo-quote"}
        assert profile.remove_headers == [
            "X-Root-Only",
            "X-Foo-Only",
            "X-Leaf-Only",
        ]
        # The more specific greeting wins; the empty [signature] section
        # in bar/INCLUDE clears the inherited root signature.
        assert profile.greeting == ["Foo greeting"]
        assert profile.signature == []

    def test_root_include_applies_to_top_level_profile(self, tmp_path: Path) -> None:
        """A profile directly in the root inherits the root INCLUDE."""
        (tmp_path / "INCLUDE").write_text("[greeting]\nHello\n", encoding="utf-8")
        path = tmp_path / "prof.mplt"
        path.write_text("[profile]\nname = P\n", encoding="utf-8")
        profile = load_profile(path, include_root=tmp_path)
        assert profile.greeting == ["Hello"]

    def test_missing_include_files_are_skipped(self, tmp_path: Path) -> None:
        """Only existing INCLUDE files are merged."""
        (tmp_path / "INCLUDE").write_text("[greeting]\nHello\n", encoding="utf-8")
        nested = tmp_path / "foo" / "bar"
        nested.mkdir(parents=True)
        path = nested / "prof.mplt"
        path.write_text("[profile]\nname = P\n", encoding="utf-8")
        profile = load_profile(path, include_root=tmp_path)
        assert profile.greeting == ["Hello"]

    def test_duplicates_dropped_keeping_first(self, tmp_path: Path) -> None:
        """Verbatim duplicate rules and remove_headers are dropped."""
        (tmp_path / "INCLUDE").write_text(
            "[rules]\nFrom = dup@example\n[remove_headers]\nX-Dup\n",
            encoding="utf-8",
        )
        path = tmp_path / "prof.mplt"
        path.write_text(
            "[profile]\n"
            "name = P\n"
            "[rules]\n"
            "From = dup@example\n"
            "Subject = leaf\n"
            "[remove_headers]\n"
            "X-Dup\n"
            "X-Leaf\n",
            encoding="utf-8",
        )
        profile = load_profile(path, include_root=tmp_path)
        assert [(rule.kind, rule.value) for rule in profile.rules] == [
            ("header", "from: dup@example"),
            ("header", "subject: leaf"),
        ]
        assert profile.remove_headers == ["X-Dup", "X-Leaf"]

    def test_profile_section_in_include_rejected(self, tmp_path: Path) -> None:
        """A [profile] section in an INCLUDE file raises an error."""
        (tmp_path / "INCLUDE").write_text("[profile]\nname = Nope\n", encoding="utf-8")
        path = tmp_path / "prof.mplt"
        path.write_text("[profile]\nname = P\n", encoding="utf-8")
        with pytest.raises(ProfileError, match="not allowed in an INCLUDE"):
            load_profile(path, include_root=tmp_path)

    def test_without_include_root_ignores_include(self, tmp_path: Path) -> None:
        """Without an include root no INCLUDE file is consulted."""
        (tmp_path / "INCLUDE").write_text("[greeting]\nHello\n", encoding="utf-8")
        path = tmp_path / "prof.mplt"
        path.write_text("[profile]\nname = P\n", encoding="utf-8")
        profile = load_profile(path)
        assert profile.greeting == []


class TestDiscoveryWithIncludes:
    """Tests for INCLUDE handling during discovery."""

    def test_discovery_applies_includes(self, tmp_path: Path) -> None:
        """Discovered profiles inherit their ancestor INCLUDE files."""
        (tmp_path / "INCLUDE").write_text("[greeting]\nHello\n", encoding="utf-8")
        nested = tmp_path / "foo"
        nested.mkdir()
        (nested / "prof.mplt").write_text("[profile]\nname = P\n", encoding="utf-8")
        # An INCLUDE file must never be discovered as a profile itself.
        profiles = discover_profiles([tmp_path])
        assert [p.stem for p in profiles] == ["foo/prof"]
        assert profiles[0].greeting == ["Hello"]

    def test_malformed_include_warns_and_skips(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A malformed INCLUDE yields a warning and skips the profile."""
        (tmp_path / "INCLUDE").write_text("no section header\n", encoding="utf-8")
        (tmp_path / "prof.mplt").write_text("[profile]\nname = P\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="mailplate.profile"):
            profiles = discover_profiles([tmp_path])
        assert profiles == []
        assert "skipping" in caplog.text
