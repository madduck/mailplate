"""Tests for the CLI module."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from click.testing import CliRunner

from mailplate import cli
from mailplate.cli import (
    _find_profile_by_name,
    _pick_best_profile,
    _resolve_log_level,
    main,
)
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

    def test_by_relative_path(self) -> None:
        """A subdirectory profile can be found by its relative path."""
        profiles = [
            Profile(
                name="Foo",
                path=Path("/profiles/work/foo.mplt"),
                relative_path=Path("work/foo.mplt"),
            ),
        ]
        result = _find_profile_by_name(profiles, "work/foo")
        assert result is not None
        assert result.stem == "work/foo"

    def test_not_found(self) -> None:
        """Missing profile returns None."""
        profiles = [Profile(name="Work", path=Path("work.mplt"))]
        result = _find_profile_by_name(profiles, "Missing")
        assert result is None

    def test_empty_list(self) -> None:
        """An empty profile list returns None."""
        result = _find_profile_by_name([], "anything")
        assert result is None


class TestResolveLogLevel:
    """Tests for _resolve_log_level."""

    def test_default_is_none(self) -> None:
        """No flags leaves logging unconfigured."""
        assert _resolve_log_level(0, False, False) is None

    def test_verbose_is_info(self) -> None:
        """A single -v selects INFO."""
        assert _resolve_log_level(1, False, False) == logging.INFO

    def test_double_verbose_is_debug(self) -> None:
        """-vv selects DEBUG."""
        assert _resolve_log_level(2, False, False) == logging.DEBUG

    def test_debug_flag_is_debug(self) -> None:
        """--debug selects DEBUG."""
        assert _resolve_log_level(0, True, False) == logging.DEBUG

    def test_quiet_is_error(self) -> None:
        """--quiet selects ERROR."""
        assert _resolve_log_level(0, False, True) == logging.ERROR

    def test_quiet_beats_debug(self) -> None:
        """--quiet takes precedence over --debug."""
        assert _resolve_log_level(2, True, True) == logging.ERROR


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

    def test_info_logs_selected_profile(self, caplog: pytest.LogCaptureFixture) -> None:
        """INFO reports the evaluation count and the selected profile."""
        profiles = [
            Profile(
                name="Match",
                path=Path("match.mplt"),
                rules=[Rule(kind="header", value="X-Custom: yes")],
            )
        ]
        with caplog.at_level(logging.INFO, logger="mailplate.cli"):
            _pick_best_profile(profiles, self._MESSAGE)
        assert "evaluating 1 profiles for auto-detection" in caplog.text
        assert "selected profile 'match' (Match) with score 1" in caplog.text

    def test_info_logs_catch_all_fallback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """INFO reports the fallback to a catch-all profile."""
        profiles = [
            Profile(
                name="Nomatch",
                path=Path("nomatch.mplt"),
                rules=[Rule(kind="header", value="X-Custom: no-way")],
            ),
            Profile(name="Catch-all", path=Path("catchall.mplt")),
        ]
        with caplog.at_level(logging.INFO, logger="mailplate.cli"):
            _pick_best_profile(profiles, self._MESSAGE)
        assert "falling back to catch-all 'catchall' (Catch-all)" in caplog.text

    def test_info_logs_no_match(self, caplog: pytest.LogCaptureFixture) -> None:
        """INFO reports that no profile matched."""
        profiles = [
            Profile(
                name="Nomatch",
                path=Path("nomatch.mplt"),
                rules=[Rule(kind="header", value="X-Custom: no-way")],
            )
        ]
        with caplog.at_level(logging.INFO, logger="mailplate.cli"):
            _pick_best_profile(profiles, self._MESSAGE)
        assert "no matching profile found" in caplog.text

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

    def test_zero_weight_adds_no_score(self) -> None:
        """A zero-weight rule does not make a profile a match."""
        profiles = [
            Profile(
                name="Zero",
                path=Path("zero.mplt"),
                rules=[Rule(kind="header", value="X-Custom: yes", weight=0)],
            ),
            Profile(name="Catch-all", path=Path("catchall.mplt")),
        ]
        profile, _captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is not None
        assert profile.stem == "catchall"

    def test_zero_weight_captures_are_collected(self) -> None:
        """A zero-weight rule still contributes its named captures."""
        profiles = [
            Profile(
                name="Match",
                path=Path("match.mplt"),
                rules=[
                    Rule(kind="header", value="X-Custom: yes"),
                    Rule(
                        kind="header",
                        value="Subject: (?P<subj>Test)",
                        weight=0,
                    ),
                ],
            )
        ]
        profile, captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is not None
        assert profile.stem == "match"
        assert captures == {"subj": "Test"}

    def test_negative_weight_prevents_selection(self) -> None:
        """A negative-weight rule keeps its profile from being selected."""
        profiles = [
            Profile(
                name="Penalised",
                path=Path("penalised.mplt"),
                rules=[Rule(kind="header", value="X-Custom: yes", weight=-100)],
            ),
            Profile(name="Catch-all", path=Path("catchall.mplt")),
        ]
        profile, _captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is not None
        assert profile.stem == "catchall"

    def test_negative_weight_outweighs_positive_score(self) -> None:
        """A negative rule can drag a profile below a competitor."""
        profiles = [
            Profile(
                name="Penalised",
                path=Path("penalised.mplt"),
                rules=[
                    Rule(kind="header", value="X-Custom: yes", weight=5),
                    Rule(kind="body", value="Urgent", weight=-100),
                ],
            ),
            Profile(
                name="Modest",
                path=Path("modest.mplt"),
                rules=[Rule(kind="header", value="X-Custom: yes", weight=3)],
            ),
        ]
        profile, _captures = _pick_best_profile(profiles, self._MESSAGE)
        assert profile is not None
        assert profile.stem == "modest"


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Click test runner."""
    return CliRunner()


class TestXdgConfigHome:
    """Tests for _xdg_config_home."""

    def test_env_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An absolute $XDG_CONFIG_HOME is used as-is."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        assert cli._xdg_config_home() == tmp_path / "cfg"

    def test_env_relative_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A relative $XDG_CONFIG_HOME is ignored."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
        assert cli._xdg_config_home() == Path.home() / ".config"

    def test_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unset $XDG_CONFIG_HOME falls back to ~/.config."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert cli._xdg_config_home() == Path.home() / ".config"

    def test_env_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty $XDG_CONFIG_HOME falls back to ~/.config."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        assert cli._xdg_config_home() == Path.home() / ".config"


def test_default_profile_dirs_exclude_host_config(
    default_profile_dirs: list[Path],
) -> None:
    """Tests never search the host's real profile directories."""
    assert cli.DEFAULT_PROFILE_DIRS == default_profile_dirs
    real_user_dir = cli._xdg_config_home() / "mailplate" / "profiles"
    assert real_user_dir not in cli.DEFAULT_PROFILE_DIRS
    assert Path("/etc/mailplate/profiles") not in cli.DEFAULT_PROFILE_DIRS


class TestMainCommand:
    """Tests for the main CLI command."""

    def test_no_input_explicit_profile(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Empty stdin applies the profile to a minimal draft."""
        from email import policy
        from email.parser import BytesParser

        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(SAMPLE_PROFILE, encoding="utf-8")
        result = cli_runner.invoke(
            main,
            args=["--profile", "test", "--profile-dir", str(profile_dir)],
            input="",
        )
        assert result.exit_code == 0
        assert result.stderr == ""
        parsed = BytesParser(policy=policy.default).parsebytes(result.stdout_bytes)
        assert parsed["X-Mailer"] == "mailplate-test/1.0"
        # The minimal draft carries no address headers, so the templates
        # render with empty values.
        body_payload = parsed.get_payload(decode=True)
        assert isinstance(body_payload, bytes)
        body = body_payload.decode("utf-8")
        assert "Hi ," in body
        assert "Best," in body

    def test_no_input_output_to_file(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """An empty stdin is written to --output as a minimal message."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(SAMPLE_PROFILE, encoding="utf-8")
        output = tmp_path / "out.eml"
        result = cli_runner.invoke(
            main,
            args=[
                "--profile",
                "test",
                "--profile-dir",
                str(profile_dir),
                "--output",
                str(output),
            ],
            input="",
        )
        assert result.exit_code == 0
        assert b"X-Mailer: mailplate-test/1.0" in output.read_bytes()

    def test_no_input_no_profile_match(self, cli_runner: CliRunner) -> None:
        """Empty stdin without a matching profile yields a minimal message."""
        from email import policy
        from email.parser import BytesParser

        result = cli_runner.invoke(
            main, args=["--profile-dir", "/nonexistent"], input=""
        )
        assert result.exit_code == 0
        assert result.stderr == ""
        assert result.stdout_bytes == b"Content-Type: text/plain\n\n"
        parsed = BytesParser(policy=policy.default).parsebytes(result.stdout_bytes)
        assert parsed.get_content_type() == "text/plain"
        assert not parsed.is_multipart()

    def test_no_input_passthrough_to_file(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Empty stdin without a matching profile writes the minimal message."""
        output = tmp_path / "out.eml"
        result = cli_runner.invoke(
            main,
            args=["--profile-dir", "/nonexistent", "--output", str(output)],
            input="",
        )
        assert result.exit_code == 0
        assert result.stdout == ""
        assert output.read_bytes() == b"Content-Type: text/plain\n\n"

    def test_no_input_catch_all(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Empty stdin auto-selects a catch-all profile."""
        from email import policy
        from email.parser import BytesParser

        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "catchall.mplt").write_text(
            "[profile]\nname = Catch All\n\n[headers]\nX-Catch = yes\n",
            encoding="utf-8",
        )
        result = cli_runner.invoke(
            main, args=["--profile-dir", str(profile_dir)], input=""
        )
        assert result.exit_code == 0
        parsed = BytesParser(policy=policy.default).parsebytes(result.stdout_bytes)
        assert parsed["X-Catch"] == "yes"
        assert parsed.get_content_type() == "text/plain"

    def test_auto_detect_no_profiles(self, cli_runner: CliRunner) -> None:
        """Auto-detect passes input through when no profile matches."""
        import tempfile
        from pathlib import Path

        # Create an isolated profiles directory with a non-matching profile.
        with tempfile.TemporaryDirectory() as tmp:
            profiles_dir = Path(tmp) / "profiles"
            profiles_dir.mkdir()
            (profiles_dir / "nomatch.mplt").write_text(
                "[profile]\nname = Nomatch\n\n[rules]\nX-Custom = no-way\n",
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

    def test_signature_preserves_blank_lines(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Blank lines inside a profile signature survive to the output."""
        from email import policy
        from email.parser import BytesParser

        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(
            "[profile]\nname = Test\n[signature]\nAlice\n\nMy Company Inc.\n",
            encoding="utf-8",
        )
        result = cli_runner.invoke(
            main,
            args=["--profile", "test", "--profile-dir", str(profile_dir)],
            input=EMAIL_HEADERS,
        )
        assert result.exit_code == 0
        parser = BytesParser(policy=policy.default)
        parsed = parser.parsebytes(result.stdout_bytes)
        body_payload = parsed.get_payload(decode=True)
        assert isinstance(body_payload, bytes)
        body = body_payload.decode("utf-8")
        assert "Hello, this is the body.\n\n-- \nAlice\n\nMy Company Inc." in body

    @pytest.mark.parametrize(
        ("body", "signature", "expected"),
        [
            pytest.param(
                "",
                "[signature]\nAlice\n",
                b"Subject: T\nFrom: a@b\n\n\n\n-- \nAlice\n",
                id="no-body-with-signature",
            ),
            pytest.param(
                "",
                "",
                b"Subject: T\nFrom: a@b\n\n\n",
                id="no-body-without-signature",
            ),
            pytest.param(
                "Hello\n",
                "[signature]\nAlice\n",
                b"Subject: T\nFrom: a@b\n\nHello\n\n-- \nAlice\n",
                id="body-with-signature",
            ),
            pytest.param(
                "Hello\n",
                "",
                b"Subject: T\nFrom: a@b\n\nHello\n",
                id="body-without-signature",
            ),
        ],
    )
    def test_body_layout(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        body: str,
        signature: str,
        expected: bytes,
    ) -> None:
        """The body is framed by blank lines and ends with a newline."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(
            f"[profile]\nname = Test\n{signature}",
            encoding="utf-8",
        )
        result = cli_runner.invoke(
            main,
            args=["--profile", "test", "--profile-dir", str(profile_dir)],
            input=("Subject: T\nFrom: a@b\n\n" + body).encode(),
        )
        assert result.exit_code == 0
        assert result.stdout_bytes == expected

    def test_explicit_profile_collects_captures(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """An explicit profile still evaluates its rules to collect captures."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(
            "[profile]\nname = Test\n\n"
            "[rules]\nFrom = .*@(?P<domain>[a-z0-9.]+)\n\n"
            "[headers]\nX-Domain = {{ rule:domain }}\n",
            encoding="utf-8",
        )
        email = b"From: alice@company.com\r\n\r\nBody\r\n"
        result = cli_runner.invoke(
            main,
            args=["--profile", "test", "--profile-dir", str(profile_dir)],
            input=email,
        )
        assert result.exit_code == 0
        assert b"X-Domain: company.com" in result.stdout_bytes

    def test_explicit_profile_merges_captures(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Captures from every matching rule are merged for an explicit profile."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(
            "[profile]\nname = Test\n\n"
            "[rules]\nFrom = .*@(?P<domain>[a-z0-9.]+)\n"
            "Subject = (?P<subject>.+)\n\n"
            "[headers]\nX-Summary = {{ rule:domain }} {{ rule:subject }}\n",
            encoding="utf-8",
        )
        email = b"From: alice@company.com\r\nSubject: Hello\r\n\r\nBody\r\n"
        result = cli_runner.invoke(
            main,
            args=["--profile", "test", "--profile-dir", str(profile_dir)],
            input=email,
        )
        assert result.exit_code == 0
        assert b"X-Summary: company.com Hello" in result.stdout_bytes

    def test_explicit_profile_ignores_non_matching_rule_captures(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """A rule that does not match contributes no captures."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(
            "[profile]\nname = Test\n\n"
            "[rules]\nFrom = .*@(?P<domain>[a-z0-9.]+)\n"
            "Subject = (?P<subject>.+)\n\n"
            "[headers]\nX-Summary = [{{ rule:subject }}]\n",
            encoding="utf-8",
        )
        email = b"From: alice@company.com\r\n\r\nBody\r\n"
        result = cli_runner.invoke(
            main,
            args=["--profile", "test", "--profile-dir", str(profile_dir)],
            input=email,
        )
        assert result.exit_code == 0
        assert b"X-Summary: []" in result.stdout_bytes

    def test_non_ascii_header_written_as_utf8(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Non-ASCII header bodies are written verbatim as UTF-8."""
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test.mplt").write_text(
            "[profile]\nname = Test\n\n[headers]\nX-Mailer = mailplate\n",
            encoding="utf-8",
        )
        raw = "Subject: Umläut\n\nBody\n".encode()
        result = cli_runner.invoke(
            main,
            args=["--profile", "test", "--profile-dir", str(profile_dir)],
            input=raw,
        )
        assert result.exit_code == 0
        assert "Subject: Umläut".encode() in result.stdout_bytes
        assert b"=?" not in result.stdout_bytes

    def test_explicit_nested_profile_success(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """A profile in a subdirectory is selected by its relative path."""
        profile_dir = tmp_path / "profiles"
        nested = profile_dir / "team"
        nested.mkdir(parents=True)
        (nested / "test.mplt").write_text(SAMPLE_PROFILE, encoding="utf-8")
        result = cli_runner.invoke(
            main,
            args=["--profile", "team/test", "--profile-dir", str(profile_dir)],
            input=EMAIL_HEADERS,
        )
        assert result.exit_code == 0
        assert b"X-Mailer: mailplate-test/1.0" in result.stdout_bytes

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

    def test_list_profiles_no_profiles(
        self,
        cli_runner: CliRunner,
        default_profile_dirs: list[Path],
    ) -> None:
        """--list-profiles lists profiles from the default directory."""
        default_dir = default_profile_dirs[0]
        default_dir.mkdir(parents=True)
        (default_dir / "default.mplt").write_text(
            "[profile]\nname = Default\n", encoding="utf-8"
        )
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
From = .*@company\\.com

[headers]
X-Profile = work
"""
        (profile_dir / "work.mplt").write_text(work_profile, encoding="utf-8")
        # Profile that does not match.
        personal_profile = """[profile]
name = Personal

[rules]
From = .*@personal\\.com

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
X-Custom = will-never-match
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
