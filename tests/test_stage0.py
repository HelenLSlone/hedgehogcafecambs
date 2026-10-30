"""Stage 0 tests -- Entry point, schedule trigger, config scaffold, and foundation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import pytest

import run_pipeline as rp

# Ensure project root is discoverable for imports.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================================
# Test helpers
# ============================================================================

_LOGS_DIR = PROJECT_ROOT / "logs"


def _setup_logs() -> None:
    """Ensure logs/ dir exists (required by pipeline logger)."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def _clear_run_pipeline_module():
    """Re-import run_pipeline fresh before every test to avoid stale state."""
    if "run_pipeline" in sys.modules:
        del sys.modules["run_pipeline"]
    yield
    for key in ("pipeline.ring_client",):
        if key in sys.modules:
            del sys.modules[key]

# ============================================================================
# test_run_pipeline_calls_stubs_in_order -- orchestration flow verification
# run_pipeline now calls ring_client.main() (async), then passes .events to
# stage_reel_generate(clips), then to downstream stubs in order.
# We mock asyncio.run to short-circuit the Ring API call and return fake clips,
# then verify every downstream stub fires in the correct order.
# ============================================================================


def test_run_pipeline_calls_stubs_in_order(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """run_pipeline invokes stages in correct order via async ring_client.main."""
    _setup_logs()



    call_order: list[str] = []

    def _make_stage(name):  # type: ignore[no-untyped-def]
        """Build a mock stage that records its name and returns appropriate data."""

        def _stage(arg=None):  # type: ignore[no-untyped-def]
            call_order.append(name)
            if name == "stage_reel_generate" and arg is not None:
                return {"video_path": None, "caption": ""}
            return None

        return _stage

    class _FakeResult:  # pylint: disable=too-few-public-methods # is a test stub
        __slots__ = ()
        events: ClassVar[list[dict]] = [
            {
                "camera_id": 635097130,
                "camera_name": "Hedgehog Cam 1",
                "created_at_utc": "2026-10-28T06:00:00+00:00",
                "download_url": "http://example.com/clip.mp4",
            },
        ]

    def _fake_asyncio_run(coro):  # pylint: disable=unused-argument
        """Return fake clips without making real async Ring API calls."""
        return _FakeResult()

    # Replace real stage functions and asyncio.run with mocks.
    monkeypatch.setattr(rp, "stage_reel_generate", _make_stage("stage_reel_generate"))
    monkeypatch.setattr(rp, "stage_whatsapp_send", _make_stage("stage_whatsapp_send"))
    monkeypatch.setattr(rp, "stage_await_feedback", _make_stage("stage_await_feedback"))
    monkeypatch.setattr(rp.asyncio, "run", _fake_asyncio_run)

    rp.run_pipeline(date_str="2026-10-28")

    expected_order = [
        "stage_reel_generate",
        "stage_whatsapp_send",
        "stage_await_feedback",
    ]
    assert call_order == expected_order, (
        f"Stage calls out of order. Expected {expected_order}, got {call_order}"
    )


# ============================================================================
# test_gitignore_has_required_entries -- verify .gitignore contents
# Checks that all Stage 0 required entries are present in .gitignore.
# ============================================================================


def test_gitignore_has_required_entries() -> None:
    """Verify .gitignore contains all Stage 0 required entries."""
    gitignore_path = PROJECT_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore not found at project root"

    content = gitignore_path.read_text()

    required_entries = [
        ".qwen*",
        ".DS_Store",
        ".vscode/",
        "memory/",
        "__pycache__/",
        ".ruff_cache/",
        ".pytest_cache/",
        "logs/",
        ".env",
        "*.token.cache",
    ]

    for entry in required_entries:
        assert entry in content, f".gitignore missing required entry: {entry!r}"
