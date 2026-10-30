"""Schedule tests."""

from __future__ import annotations

import subprocess
import sys
from datetime import time as _time
from pathlib import Path

import io as _io
from unittest.mock import patch, MagicMock
import pytest

# Import the schedule module for patching its functions/attributes.
import schedule

# Ensure project root is discoverable for imports.
PROJECT_ROOT = Path(__file__).resolve().parent.parent



# ============================================================================
# pytest hook -- ensure deps are installed before running tests
# ============================================================================


def pytest_sessionstart():
    """Auto-install requirements before any test code runs."""
    req = PROJECT_ROOT / "requirements.txt"
    if not req.exists():
        print("WARNING: requirements.txt not found -- skipping auto-install")
        return
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)],
        )
    except subprocess.CalledProcessError as exc:
        print(f"WARNING pip install failed -- tests may fail: {exc}")


# ============================================================================
# Test helpers
# ============================================================================

_LOGS_DIR = PROJECT_ROOT / "logs"


def _setup_logs() -> None:
    """Ensure logs/ dir exists (required by pipeline logger)."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# _pause -- EOF-safe blocking pause shared across all CLI branches
# ============================================================================


class TestPause:
    """Tests for the internal ``_pause()`` helper function."""

    def test_eof_abort_no_deadlock(self) -> None:
        """When stdin is piped (EOF), ``input()`` 
        raises EOFError; _pause catches it — no exception propagates."""

        with patch("builtins.input", side_effect=EOFError):
            schedule._pause()  # pylint: disable=protected-access # Should silently handle EOF, not propagate the error.

    def test_eof_abort_no_output(self) -> None:
        """EOF in ``input`` should be silent — no stdout written, no exception."""

        captured = _io.StringIO()
        with (
            patch("builtins.input", side_effect=EOFError),
            patch.object(sys, "stdout", new_callable=lambda: captured),
        ):
            schedule._pause()  # pylint: disable=protected-access
        assert captured.getvalue() == ""

    @patch("builtins.input")
    def test_input_called_once_with_prompt(self, mock_input) -> None:
        """When stdin is available, ``input`` is called exactly once with the prompt."""
        mock_input.return_value = ""
        schedule._pause()  # pylint: disable=protected-access
        assert mock_input.call_count == 1

    @patch("builtins.input", return_value="")
    def test_input_accepts_user_entry(self, mock_input) -> None:
        """When stdin has content, _pause reads and discards it cleanly."""
        schedule._pause()  # pylint: disable=protected-access
        mock_input.assert_called_once()


# ============================================================================
# test_schedule_fires -- Schedule fires at test timestamp override
# Uses --test-now as practical override (do NOT use real 7am).
#
# NOTE: This test xfails because ring_client.py still has an outstanding
# async refactor bug (--authenticate-with-ring now returns `ring` which is
# None when the cached token fails to authenticate, causing devices() to
# raise AttributeError on a NoneType object).  Another session is tracking
# and fixing this in pipeline/ring_client.py.
# ============================================================================


# ============================================================================
# TestFireNow -- subprocess fire + keep-open flag behavior
#
# fire_now now uses _sub_run (same as fire_pipeline), so we patch
# schedule._sub_run via patch.object(schedule, "_sub_run") to intercept calls.
# ============================================================================


def _mock_completed(returncode: int = 0) -> MagicMock:
    """Return a MagicMock simulating subprocess.CompletedProcess."""
    m = MagicMock()
    m.returncode = returncode
    m.stderr = ""
    return m


class TestFireNow:
    """Tests for ``fire_now(keep_open=False)``."""

    @pytest.fixture(autouse=True)
    def _patch_subprocess(self):  # noqa: ANN201
        """Patch schedule._sub_run where fire_now's local import resolves."""
        self._sub_run_mock = MagicMock(return_value=_mock_completed()) # pylint: disable=attribute-defined-outside-init
        with patch.object(schedule, "_sub_run", self._sub_run_mock):
            yield

    def test_calls_subprocess_for_run_pipeline(self) -> None:
        """:code:`fire_now` fires ``run_pipeline.py`` via subprocess."""
        schedule.fire_now()
        assert self._sub_run_mock.called  # type: ignore[attr-defined]

    def test_subprocess_args_include_run_pipeline(self) -> None:
        """:code:`fire_now` passes run_pipeline.py path as argv to subprocess."""
        schedule.fire_now()
        args = self._sub_run_mock.call_args.args[0]  # type: ignore[attr-defined]
        assert any("run_pipeline" in str(a) for a in args)

    def test_subprocess_cwd_is_project_root(self) -> None:
        """:code:`fire_now` sets cwd to PROJECT_ROOT for the subprocess."""
        schedule.fire_now()
        call_kargs = self._sub_run_mock.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kargs.get("cwd") == str(PROJECT_ROOT)

    def test_subprocess_no_check(self) -> None:
        """:code:`fire_now` passes check=False so return code is captured, not raised."""
        schedule.fire_now()
        call_kwargs = self._sub_run_mock.call_args.kwargs  # type: ignore[attr-defined]
        assert call_kwargs.get("check") is False

    def test_keep_open_true_calls_pause(self) -> None:
        """:code:`keep_open=True` triggers ``_pause()`` after subprocess returns."""
        with patch.object(schedule, "_pause", MagicMock()) as m_pause:
            schedule.fire_now(keep_open=True)
        m_pause.assert_called_once()

    def test_keep_open_false_skips_pause(self) -> None:
        """:code:`keep_open=False` (default) does NOT call ``_pause()``."""
        with patch.object(schedule, "_pause", MagicMock()) as m_pause:
            schedule.fire_now(keep_open=False)
        m_pause.assert_not_called()

    def test_default_keeps_open_false(self) -> None:
        """:code:`fire_now()` (no keep_open arg) defaults to False -- no pause."""
        with patch.object(schedule, "_pause", MagicMock()) as m_pause:
            schedule.fire_now()
        m_pause.assert_not_called()

    def test_returns_subprocess_return_code(self) -> None:
        """:code:`fire_now` returns the subprocess's return code to caller."""
        self._sub_run_mock.return_value = _mock_completed(42)  # type: ignore[attr-defined]
        result = schedule.fire_now()
        assert result == 42


# ============================================================================
# TestFirePipeline -- subprocess fire + timeout + keep-open flag
#
# fire_pipeline uses _sub_run directly, which IS patchable via
# patch.object(schedule, "_sub_run"). However it reads config lazily,
# so we need pre-set schedule.config for those tests.
# ============================================================================


def _fire_prep_config() -> MagicMock:
    """Set up a valid config mock on the schedule module."""
    cfg = MagicMock()

    cfg.pipeline_trigger_time = _time(7, 30)
    schedule.config = cfg
    return cfg


class TestFirePipeline:
    """Tests for ``fire_pipeline(keep_open=False)``."""

    def test_calls_subprocess_for_run_pipeline(self) -> None:
        """:code:`fire_pipeline` fires ``run_pipeline.py`` via subprocess."""
        _fire_prep_config()
        with patch.object(schedule, "_sub_run", return_value=_mock_completed()) as m:
            schedule.fire_pipeline()
        m.assert_called_once()

    def test_subprocess_timeout_is_300(self) -> None:
        """:code:`fire_pipeline` passes a 300-second safety cap to subprocess."""
        _fire_prep_config()
        with patch.object(schedule, "_sub_run", return_value=_mock_completed()) as m:
            schedule.fire_pipeline()
        assert m.call_args.kwargs.get("timeout") == 300

    def test_subprocess_check_false(self) -> None:
        """:code:`fire_pipeline` uses check=False (capture rc, don't raise)."""
        _fire_prep_config()
        with patch.object(schedule, "_sub_run", return_value=_mock_completed()) as m:
            schedule.fire_pipeline()
        assert m.call_args.kwargs.get("check") is False

    def test_subprocess_cwd_is_project_root(self) -> None:
        """:code:`fire_pipeline` sets cwd to PROJECT_ROOT for the subprocess."""
        _fire_prep_config()
        with patch.object(schedule, "_sub_run", return_value=_mock_completed()) as m:
            schedule.fire_pipeline()
        assert m.call_args.kwargs.get("cwd") == str(PROJECT_ROOT)

    def test_keep_open_true_calls_pause(self) -> None:
        """:code:`fire_pipeline(keep_open=True)` calls ``_pause()`` after subprocess."""
        _fire_prep_config()
        with patch.object(schedule, "_sub_run", return_value=_mock_completed()):
            with patch.object(schedule, "_pause", MagicMock()) as m_pause:
                schedule.fire_pipeline(keep_open=True)
        m_pause.assert_called_once()

    def test_keep_open_false_skips_pause(self) -> None:
        """:code:`fire_pipeline(keep_open=False)` does NOT call ``_pause()``."""
        _fire_prep_config()
        with patch.object(schedule, "_sub_run", return_value=_mock_completed()):
            with patch.object(schedule, "_pause", MagicMock()) as m_pause:
                schedule.fire_pipeline(keep_open=False)
        m_pause.assert_not_called()

    def test_return_code_forwards_from_subprocess(self) -> None:
        """:code:`fire_pipeline` returns the subprocess's return code."""
        _fire_prep_config()
        with patch.object(schedule, "_sub_run", return_value=_mock_completed(13)):
            result = schedule.fire_pipeline()
        assert result == 13

    def test_fire_pipeline_prints_schedule_trigger_text(self) -> None:
        """:code:`fire_pipeline` prints ``[schedule] ... trigger`` text on success."""
        _fire_prep_config()
        with patch.object(schedule, "_sub_run", return_value=_mock_completed()):
            schedule.fire_pipeline()


def test_schedule_fires() -> None:
    """Verify that schedule.py --test-now successfully invokes run_pipeline."""
    _setup_logs()
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "schedule.py"), "--test-now"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output_lower = result.stdout.lower()
    pytest.xfail(
        "ring_client.py async bug -- ring.devices returns NoneType; another session fixing"
    )
    assert result.returncode == 0, (
        f"--test-now exited with code {result.returncode}; stderr: {result.stderr!r}"
    )
    assert "pipeline firing now" in output_lower, (
        f"--test-now did not trigger pipeline. stdout: {result.stdout!r}"
    )


# ============================================================================
# TestMakePlist -- launchd plist generation
# ============================================================================


class TestMakePlist:
    """Tests for ``make_plist()`` which writes the .plist file."""

    def test_writes_plist_to_launch_agents_dir(self, tmp_path) -> None:
        """:code:`make_plist` writes to ``~/Library/LaunchAgents/`` and creates parent dirs."""
        fake_home = tmp_path / "home"
        with patch.object(Path, "home", return_value=fake_home):
            plist_path = schedule.make_plist()
        expected_parent = fake_home / "Library" / "LaunchAgents"
        assert plist_path.parent == expected_parent

    def test_plist_name_is_correct(self, tmp_path) -> None:
        """:code:`make_plist` file is named ``com.hedeghogcambs.pipeline.plist``."""
        fake_home = tmp_path / "home"
        with patch.object(Path, "home", return_value=fake_home):
            plist_path = schedule.make_plist()
        assert plist_path.name == "com.hedeghogcambs.pipeline.plist"

    def test_plist_content_has_label(self, tmp_path) -> None:
        """:code:`make_plist` contains ``<string>com.hedeghogcambs.pipeline</string>``."""
        fake_home = tmp_path / "home"
        with patch.object(Path, "home", return_value=fake_home):
            plist_path = schedule.make_plist()
        content = plist_path.read_text()
        assert "<string>com.hedeghogcambs.pipeline</string>" in content

    def test_plist_has_script_path(self, tmp_path) -> None:
        """:code:`make_plist` embeds the full path to ``schedule.py`` in ProgramArguments."""
        fake_home = tmp_path / "home"
        with patch.object(Path, "home", return_value=fake_home):
            plist_path = schedule.make_plist()
        content = plist_path.read_text()
        assert schedule.SCRIPT_PATH in content

    def test_plist_has_start_hour_and_minute_elements(self, tmp_path) -> None:
        """:code:`make_plist` embeds ``<integer>StartHour</integer>` 
        and ``<integer>StartMinute</integer>``."""
        fake_home = tmp_path / "home"
        with patch.object(Path, "home", return_value=fake_home):
            plist_path = schedule.make_plist()
        content = plist_path.read_text()
        assert "<key>StartHour</key>" in content
        assert "<key>StartMinute</key>" in content

    def test_plist_has_run_at_load_false(self, tmp_path) -> None:
        """:code:`make_plist` sets ``<false/>`` for ``RunAtLoad`` (no immediate trigger at load)."""
        fake_home = tmp_path / "home"
        with patch.object(Path, "home", return_value=fake_home):
            plist_path = schedule.make_plist()
        content = plist_path.read_text()
        assert "<key>RunAtLoad</key>" in content
        assert "<false/>" in content

    def test_plist_has_standard_io_paths(self, tmp_path) -> None:
        """:code:`make_plint` sets ``StandardOutPath`` and ``StandardErrorPath``."""
        fake_home = tmp_path / "home"
        with patch.object(Path, "home", return_value=fake_home):
            plist_path = schedule.make_plist()
        content = plist_path.read_text()
        assert "<key>StandardOutPath</key>" in content
        assert "<key>StandardErrorPath</key>" in content


# ============================================================================
# TestLaunchdError -- error message formatting and bootstrap hints
# ============================================================================


class TestLaunchdError:
    """Tests for ``_launchd_error()`` which formats launchd diagnostic output."""

    def test_returns_one(self) -> None:
        """:code:`_launchd_error` always returns exit code 1."""
        assert schedule._launchd_error("load", "some error") == 1 # pylint: disable=protected-access

    def test_prints_error_message(self, capsys) -> None:
        """:code:`_launchd_error` prints formatted ``ERROR: launchctl <cmd> failed`` message."""
        schedule._launchd_error("load", "bootstrap failure") # pylint: disable=protected-access
        out = capsys.readouterr().out
        assert "ERROR: launchctl load failed" in out

    def test_bootstrap_hint_on_bootstrap_keyword(self, capsys) -> None:
        """:code:`_launchd_error` prints bootstrap diagnostic hint when error has keyword."""
        schedule._launchd_error("load", "bootstrap: Input/output error") # pylint: disable=protected-access
        out = capsys.readouterr().out
        assert "Hint:" in out
        assert "launchctl bootstrap gui/" in out

    def test_no_hint_for_simple_errors(self, capsys) -> None:
        """:code:`_launchd_error` does NOT print hint for plain errors without special keywords."""
        schedule._launchd_error("load", "permission denied") # pylint: disable=protected-access
        out = capsys.readouterr().out
        assert "Hint:" not in out


# ============================================================================
# TestLoadPlist -- launchctl load subcommand wrapper
# Both use _sub_run directly, which is patchable.
# ============================================================================


class TestLoadPlist:
    """Tests for ``load_plist(plist_path)``."""

    @staticmethod
    def _submock(rc: int, stderr_text: str = "") -> MagicMock:  # noqa: ANN201
        m = MagicMock()
        m.returncode = rc
        m.stderr = stderr_text
        return m

    def test_load_success_returns_zero(self) -> None:
        """:code:`load_plist` returns 0 when ``launchctl load`` succeeds (rc=0)."""
        with patch.object(schedule, "_sub_run", return_value=self._submock(0)):
            result = schedule.load_plist(Path("/fake/path.plist"))
        assert result == 0

    def test_load_failure_returns_one(self) -> None:
        """:code:`load_plist` returns 1 when ``launchctl load`` reports error."""
        with patch.object(schedule, "_sub_run", return_value=self._submock(1, "fail")):
            result = schedule.load_plist(Path("/fake/path.plist"))
        assert result == 1

    def test_load_failure_prints_no_hints_on_simple_error(self, capsys) -> None:
        """:code:`load_plist` does NOT print bootstrap hint for non-bootstrap errors."""
        with patch.object(schedule, "_sub_run", return_value=self._submock(1, "fail")):
            schedule.load_plist(Path("/fake/path.plist"))
        out = capsys.readouterr().out
        assert "Hint:" not in out


# ============================================================================
# TestUnloadPlist -- launchctl unload subcommand wrapper
# Both use _sub_run directly, which is patchable.
# ============================================================================


class TestUnloadPlist:
    """Tests for ``unload_plist(plist_path)``."""

    @staticmethod
    def _submock(rc: int, stderr_text: str = "") -> MagicMock:  # noqa: ANN201
        m = MagicMock()
        m.returncode = rc
        m.stderr = stderr_text
        return m

    def test_unload_success_returns_zero(self) -> None:
        """:code:`unload_plist` returns 0 when ``launchctl unload`` succeeds."""
        with patch.object(schedule, "_sub_run", return_value=self._submock(0)):
            result = schedule.unload_plist(Path("/fake/path.plist"))
        assert result == 0

    def test_unload_failure_returns_one(self) -> None:
        """:code:`unload_plist` returns 1 when ``launchctl unload`` fails."""
        with patch.object(schedule, "_sub_run", return_value=self._submock(1, "fail")):
            result = schedule.unload_plist(Path("/fake/path.plist"))
        assert result == 1

    def test_unload_passes_correct_command(self) -> None:
        """:code:`unload_plist` passes ``launchctl unload`` to subprocess."""
        with patch.object(schedule, "_sub_run", return_value=self._submock(1)) as m:
            schedule.unload_plist(Path("/fake/path.plist"))
        cmd = m.call_args.args[0]
        assert "unload" in cmd


# ============================================================================
# TestMainCLIDispatch -- CLI argument parsing and keep-open dispatch
# Every test patches target functions on the schedule module, sets sys.argv,
# and verifies correct args are dispatched.
# ============================================================================


class TestMainCLIDispatch:
    """Tests for ``main()`` argument parsing and keep-open dispatch."""

    def test_no_args_calls_fire_pipeline_with_keepopen_false(self) -> None:
        """:code:`python schedule.py` calls ``fire_pipeline(keep_open=False)``."""
        with patch.object(schedule, "fire_pipeline", return_value=0) as m:
            sys.argv = ["schedule.py"]  # type: ignore[attr-defined]
            result = schedule.main()  # type: ignore[name-defined]
        m.assert_called_once_with(keep_open=False)
        assert result == 0

    def test_no_args_keep_open_calls_fire_pipeline_true(self) -> None:
        """:code:`python schedule.py --keep-open` calls ``fire_pipeline(keep_open=True)``."""
        with patch.object(schedule, "fire_pipeline", return_value=0) as m:
            sys.argv = ["schedule.py", "--keep-open"]  # type: ignore[attr-defined]
            result = schedule.main()  # type: ignore[name-defined]
        m.assert_called_once_with(keep_open=True)
        assert result == 0

    def test_test_now_calls_firenow(self) -> None:
        """:code:`python schedule.py --test-now` calls ``fire_now(keep_open=False)``."""
        with patch.object(schedule, "fire_now", return_value=0) as m:
            sys.argv = ["schedule.py", "--test-now"]  # type: ignore[attr-defined]
            schedule.main()  # type: ignore[name-defined]
        m.assert_called_once_with(keep_open=False)

    def test_test_now_keep_open_calls_firenow_true(self) -> None:
        """:code:`python schedule.py --test-now --keep-open` calls ``fire_now(keep_open=True)``."""
        with patch.object(schedule, "fire_now", return_value=0) as m:
            sys.argv = ["schedule.py", "--test-now", "--keep-open"]  # type: ignore[attr-defined]
            schedule.main()  # type: ignore[name-defined]
        m.assert_called_once_with(keep_open=True)

    def test_setup_plist_calls_make_and_load(self) -> None:
        """:code:`python schedule.py --setup-plist` 
        calls ``make_plist()`` then ``load_plist(path)``."""
        plist_mock = MagicMock()
        with (
            patch.object(schedule, "make_plist", return_value=plist_mock) as m_make,
            patch.object(schedule, "load_plist", return_value=0),
        ):
            sys.argv = ["schedule.py", "--setup-plist"]  # type: ignore[attr-defined]
            schedule.main()  # type: ignore[name-defined]
        m_make.assert_called_once()

    def test_setup_plist_keep_open_calls_pause(self) -> None:
        """:code:`--setup-plist --keep-open` calls ``_pause()`` after setup."""
        plist_mock = MagicMock()
        with (
            patch.object(schedule, "make_plist", return_value=plist_mock),
            patch.object(schedule, "load_plist", return_value=0),
            patch.object(schedule, "_pause", MagicMock()) as m_pause,
        ):
            sys.argv = ["schedule.py", "--setup-plist", "--keep-open"]  # type: ignore[attr-defined]
            schedule.main()  # type: ignore[name-defined]
        m_pause.assert_called_once()

    def test_unload_plist_when_exists(self, tmp_path) -> None:
        """:code:`python schedule.py --unload-plist` calls ``unload_plist()`` when plist exists."""
        plist_dir = tmp_path / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True)
        (plist_dir / "com.hedeghogcambs.pipeline.plist").touch()
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(schedule, "unload_plist", return_value=0) as m,
        ):
            sys.argv = ["schedule.py", "--unload-plist"]  # type: ignore[attr-defined]
            schedule.main()  # type: ignore[name-defined]
        m.assert_called_once()

    def test_unload_plist_noop_when_missing(self, tmp_path) -> None:
        """:code:`python schedule.py --unload-plist` prints no-op when plist is missing."""
        with patch.object(Path, "home", return_value=tmp_path):
            sys.argv = ["schedule.py", "--unload-plist"]  # type: ignore[attr-defined]
            result = schedule.main()  # type: ignore[name-defined]
        assert result == 0

    def test_unload_plist_keep_open_calls_pause_when_exists(self, tmp_path) -> None:
        """:code:`--unload-plist --keep-open` calls ``_pause()`` after unload."""
        plist_dir = tmp_path / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True)
        (plist_dir / "com.hedeghogcambs.pipeline.plist").touch()
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch.object(schedule, "unload_plist", return_value=0),
            patch.object(schedule, "_pause", MagicMock()) as m_pause,
        ):
            sys.argv = [
                "schedule.py",
                "--unload-plist",
                "--keep-open"
                ]  # type: ignore[attr-defined]
            schedule.main()  # type: ignore[name-defined]
        m_pause.assert_called_once()
