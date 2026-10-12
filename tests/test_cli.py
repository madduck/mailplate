"""Tests for the CLI module."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from mailplate.cli import _find_profile_by_name, _pick_best_profile, main
from mailplate.merge import parse_email
from mailplate.profile import Profile, Rule


class TestFindProfileByName:
    """Tests for _find_profile_by_name."""

    def test_by_stem(self) -> None:
        """A profile can be found by its stem."""
        profiles = [
            Profile(name="Work", path=Path("work.mplt")),
            Profile(name="Personal", path=Path("personal.mplt")),
        ]
        result = _find_profile_by_name(profiles, "work")
        assert result is not None
        assert result.stem == "work"

    def test_by_name(self) -> None:
        """A profile can be found by its display name."""
        profiles = [
            Profile(name="Work Profile", path=Path("work.mplt")),
        ]
        result = _find_profile_by_name(profiles, "Work Profile")
        assert result is not None
        assert result.stem == "work"

    def test_not_found(self) -> None:
        """Missing profile returns None."""
        profiles = [Profile(name="Work", path=Path("work.mplt"))]
        result = _find_profile_by_name(profiles, "Missing")
        assert result is None

    def test_empty_list(self) -> None:
        """An empty profile list returns None."""
        result = _find_profile_by_name([], "anything")
        assert result is None


EMAIL_HEADERS = b"Subject: Test\r\nFrom: Alice <alice@example.com>\r\nTo: Bob <bob@example.com>\r\n\r\nHello, this is the body.\r\n"

SAMPLE_PROFILE = """[profile]
name = Test Profile

[headers]
X-Mailer = mailplate-test/1.0

[greeting]
Hi {{ to_name }},

[closing]
Best,
{{ from_name }}

[signature]
--
{{ from_email }}
"""


class TestPickBestProfile:
    """Tests for _pick_best_profile."""

    _MESSAGE = parse_email(b"Subject: Test\r\nX-Custom: yes\r\n\r\nUrgent body\r\n")

    def test_zero_score_is_not_a_match(self) -> None:
        """A profile whose rules all fail scores zero and is not selected."""
        profiles = [
            Profile(
                name="First",
                path=Path("first.mplt"),
                rules=[Rule(kind="header", value="X-Custom: no-way")],
            )
        ]
        profile, captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is None
        assert captures == {}

    def test_positive_score_wins(self) -> None:
        """A profile with a matching rule is selected."""
        profiles = [
            Profile(
                name="Nomatch",
                path=Path("nomatch.mplt"),
                rules=[Rule(kind="header", value="X-Custom: no-way")],
            ),
            Profile(
                name="Match",
                path=Path("match.mplt"),
                rules=[Rule(kind="header", value="X-Custom: yes")],
            ),
        ]
        profile, _captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is not None
        assert profile.stem == "match"

    def test_catch_all_used_when_no_match(self) -> None:
        """A rule-less profile is the fallback when nothing scores."""
        profiles = [
            Profile(
                name="Nomatch",
                path=Path("nomatch.mplt"),
                rules=[Rule(kind="header", value="X-Custom: no-way")],
            ),
            Profile(name="Catch-all", path=Path("catchall.mplt")),
        ]
        profile, _captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is not None
        assert profile.stem == "catchall"

    def test_first_catch_all_wins(self) -> None:
        """The earliest catch-all is used when several exist."""
        profiles = [
            Profile(name="First", path=Path("first.mplt")),
            Profile(name="Second", path=Path("second.mplt")),
        ]
        profile, _captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is not None
        assert profile.stem == "first"

    def test_match_beats_catch_all(self) -> None:
        """A positive-scoring profile beats a catch-all."""
        profiles = [
            Profile(name="Catch-all", path=Path("catchall.mplt")),
            Profile(
                name="Match",
                path=Path("match.mplt"),
                rules=[Rule(kind="header", value="X-Custom: yes")],
            ),
        ]
        profile, _captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is not None
        assert profile.stem == "match"

    def test_captures_only_from_winner(self) -> None:
        """Named captures are returned for the winning profile."""
        profiles = [
            Profile(
                name="Match",
                path=Path("match.mplt"),
                rules=[
                    Rule(kind="header", value="X-Custom: (?P<flag>yes)"),
                ],
            )
        ]
        _profile, captures = _pick_best_profile(profiles, self._MESSAGE)
        assert captures == {"flag": "yes"}


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Click test runner."""
    return CliRunner()


class TestMainCommand:
    """Tests for the main CLI command."""

    def test_no_input(self, cli_runner: CliRunner) -> None:
        """Running without any input returns an error."""
        result = cli_runner.invoke(main, input="")
        assert result.exit_code != 0
        assert "no input" in result.output.lower()

    def test_auto_detect_no_profiles(self, cli_runner: CliRunner) -> None:
        """Auto-detect passes input through when no profile matches."""
        import tempfile
        from pathlib import Path

        # Create an isolated profiles directory with a non-matching profile.
        with tempfile.TemporaryDirectory() as tmp:
            profiles_dir = Path(tmp) / "profiles"
            profiles_dir.mkdir()
            (profiles_dir / "nomatch.mplt").write_text(
                "[profile]\nname = Nomatch\n\n[rules]\nheader = X-Custom: no-way\n",
                encoding="utf-8",
            )
            result = cli_runner.invoke(
                main,
                args=["--profile-dir", str(profiles_dir)],
                input=EMAIL_HEADERS,
            )
            # No profile matched, so input should pass through verbatim
            # (minus \r\n → \n normalization from Click's test runner).
            assert result.exit_code == 0
            parsed = __import__("email").message_from_bytes(result.stdout_bytes)
            assert parsed["Subject"] == "Test"
            assert "Hi" not in result.stdout_bytes.decode()

    def test_explicit_profile_not_found(self, cli_runner: CliRunner) -> None:
        """Specifying a non-existent profile returns an error."""
        result = cli_runner.invoke(
            main,
            args=["--profile", "nonexistent", "--profile-dir", "/nonexistent"],
            input=EMAIL_HEADERS,
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_explicit_profile_success(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """An explicit profile is applied successfully."""
        from email import policy
        from email.parser import BytesParser

        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(SAMPLE_PROFILE, encoding="utf-8")
        result = cli_runner.invoke(
            main,
            args=["--profile", "test", "--profile-dir", str(profile_dir)],
            input=EMAIL_HEADERS,
        )
        assert result.exit_code == 0
        # Parse the result and verify content.
        parser = BytesParser(policy=policy.default)
        parsed = parser.parsebytes(result.stdout_bytes)
        assert parsed["X-Mailer"] == "mailplate-test/1.0"
        body_payload = parsed.get_payload(decode=True)
        assert isinstance(body_payload, bytes)
        body = body_payload.decode("utf-8")
        assert "Hi Bob," in body
        assert "Best,\nAlice" in body
        assert "--\nalice@example.com" in body

    def test_output_to_file(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """The --output option writes to a file."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(SAMPLE_PROFILE, encoding="utf-8")
        output_path = tmp_path / "result.eml"
        result = cli_runner.invoke(
            main,
            args=[
                "--profile",
                "test",
                "--profile-dir",
                str(profile_dir),
                "--output",
                str(output_path),
            ],
            input=EMAIL_HEADERS,
        )
        assert result.exit_code == 0
        assert output_path.exists()
        content = output_path.read_bytes()
        assert b"X-Mailer: mailplate-test/1.0" in content

    def test_list_profiles(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """The --list-profiles flag lists available profiles."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "work.mplt").write_text(
            "[profile]\nname = Work Profile\n", encoding="utf-8"
        )
        (profile_dir / "personal.mplt").write_text(
            "[profile]\nname = Personal Profile\n", encoding="utf-8"
        )
        result = cli_runner.invoke(
            main,
            args=["--list-profiles", "--profile-dir", str(profile_dir)],
        )
        assert result.exit_code == 0
        assert "work" in result.output
        assert "Work Profile" in result.output
        assert "personal" in result.output
        assert "Personal Profile" in result.output

    def test_list_profiles_no_profiles(self, cli_runner: CliRunner) -> None:
        """--list-profiles with no custom profiles still shows the default."""
        # The default profile from ~/.config/mailplate/profiles/ exists,
        # so --list-profiles always finds at least that one.
        result = cli_runner.invoke(
            main,
            args=["--list-profiles"],
        )
        assert result.exit_code == 0
        assert "default" in result.output

    def test_multiple_profile_dirs(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Multiple --profile-dir options are accepted."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "a.mplt").write_text("[profile]\nname = A\n", encoding="utf-8")
        (dir2 / "b.mplt").write_text("[profile]\nname = B\n", encoding="utf-8")
        result = cli_runner.invoke(
            main,
            args=[
                "--list-profiles",
                "--profile-dir",
                str(dir1),
                "--profile-dir",
                str(dir2),
            ],
        )
        assert result.exit_code == 0
        assert "a" in result.output
        assert "b" in result.output

    def test_auto_detect_with_match(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Auto-detection picks a matching profile based on rules."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        # Profile that matches by From header.
        work_profile = """[profile]
name = Work

[rules]
header = From:.*@company\\.com

[headers]
X-Profile = work
"""
        (profile_dir / "work.mplt").write_text(work_profile, encoding="utf-8")
        # Profile that does not match.
        personal_profile = """[profile]
name = Personal

[rules]
header = From:.*@personal\\.com

[headers]
X-Profile = personal
"""
        (profile_dir / "personal.mplt").write_text(personal_profile, encoding="utf-8")
        # Input email from company domain.
        email = b"From: alice@company.com\r\n\r\nHello\r\n"
        result = cli_runner.invoke(
            main,
            args=["--profile-dir", str(profile_dir)],
            input=email,
        )
        assert result.exit_code == 0
        assert b"X-Profile: work" in result.stdout_bytes
        assert b"X-Profile: personal" not in result.stdout_bytes

    def test_verbose_no_profile_match(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Verbose mode does not prevent normal operation when no rule matches."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        non_matching = """[profile]
name = Nomatch

[rules]
header = X-Custom: will-never-match
"""
        (profile_dir / "nomatch.mplt").write_text(non_matching, encoding="utf-8")
        email = b"From: alice@other.com\r\n\r\nHello\r\n"
        result = cli_runner.invoke(
            main,
            args=["--verbose", "--profile-dir", str(profile_dir)],
            input=email,
        )
        # The email passes through (the default catch-all profile matches).
        assert result.exit_code == 0
        assert b"From: alice@other.com" in result.stdout_bytes

    def test_explicit_profile_verbose(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Verbose output with an explicit profile (no stderr assertions)."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(
            "[profile]\nname = Test\n\n[headers]\nX-Foo = bar\n",
            encoding="utf-8",
        )
        email = b"Subject: Hi\r\n\r\nBody\r\n"
        result = cli_runner.invoke(
            main,
            args=["--verbose", "--profile", "test", "--profile-dir", str(profile_dir)],
            input=email,
        )
        assert result.exit_code == 0
        assert b"X-Foo: bar" in result.stdout_bytes
