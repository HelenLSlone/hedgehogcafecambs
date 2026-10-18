"""Stage 0 tests — Entry point, schedule trigger, config scaffold, and foundation."""

import importlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is discoverable for imports.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# pytest hook — ensure deps are installed before running tests
# ============================================================================

def pytest_sessionstart(session):  # noqa: ANN201
    """Auto-install requirements before any test code runs."""
    req = PROJECT_ROOT / "requirements.txt"
    if not req.exists():
        print("WARNING: requirements.txt not found — skipping auto-install")
        return None
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)],
        )
    except subprocess.CalledProcessError as exc:  # noqa: ANN201
        print(f"WARNING pip install failed — tests may fail: {exc}")


# ============================================================================
# Test helpers
# ============================================================================

_LOGS_DIR = PROJECT_ROOT / "logs"


def _setup_logs() -> None:
    """Ensure logs/ dir exists (required by pipeline logger)."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def _clear_run_pipeline_module():  # noqa: ANN201
    """Re-import run_pipeline fresh before every test to avoid stale state."""
    if "run_pipeline" in sys.modules:
        del sys.modules["run_pipeline"]
    yield
    if "run_pipeline" in sys.modules:
        del sys.modules["run_pipeline"]


# ============================================================================
# test_schedule_fires — Schedule fires at test timestamp override
# Uses --test-now as practical override (do NOT use real 7am).
# ============================================================================

def test_schedule_fires() -> None:
    """Verify that schedule.py --test-now successfully invokes run_pipeline."""
    _setup_logs()
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "schedule.py"), "--test-now"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    output_lower = result.stdout.lower()
    assert (
        result.returncode == 0
    ), f"--test-now exited with code {result.returncode}; stderr: {result.stderr!r}"
    assert (
        "pipeline firing now" in output_lower
    ), f"--test-now did not trigger pipeline. stdout: {result.stdout!r}"


# ============================================================================
# test_run_pipeline_calls_stubs_in_order — stub order verification
# run_pipeline calls stubs for each stage sequentially, in expected order.
# ============================================================================

def test_run_pipeline_calls_stubs_in_order() -> None:  # noqa: D401, D205
    """run_pipeline calls stubs for each stage sequentially, in expected order."""
    _setup_logs()

    # Import module-level mutable list that patched functions can mutate.
    import run_pipeline as rp  # noqa: F401

    # Shared store avoiding patch.object signature-wrapping pitfalls.
    calls_order: list[str] = []

    def make_capture(name):  # type: ignore[no-untyped-def]
        """Return a callable that records itself being called."""
        captured_name = name  # closure var, not a param

        def _inner(*args, **kwargs):  # noqa: ARG001
            calls_order.append(captured_name)
            if name == "stage_ring_clips":
                return [{"clip_id": "test"}]  # non-empty so reel generation fires
            if name == "stage_reel_generate":
                return {"video_path": None, "caption": ""}
            return None

        return _inner

    with patch.object(
        rp, "stage_ring_clips", side_effect=make_capture("stage_ring_clips")
    ), patch.object(
        rp, "stage_reel_generate", side_effect=make_capture("stage_reel_generate")
    ), patch.object(
        rp, "stage_whatsapp_send", side_effect=make_capture("stage_whatsapp_send")
    ), patch.object(
        rp, "stage_await_feedback", side_effect=make_capture("stage_await_feedback")
    ):
        rp.run_pipeline()

    expected_order = [
        "stage_ring_clips",
        "stage_reel_generate",
        "stage_whatsapp_send",
        "stage_await_feedback",
    ]
    assert calls_order == expected_order, (
        f"Stage calls out of order or missing. "
        f"Expected {expected_order}, got {calls_order}"
    )


# ============================================================================
# test_config_loads_without_errors — config imports cleanly
# .env reads expected keys as strings (validated by Pydantic at import time).
# ============================================================================

def test_config_loads_without_errors() -> None:
    """Verify that config.py imports without raising errors."""
    import config  # noqa: F401, ANN201

    # Check expected keys / attributes exist on the loaded config object.
    assert hasattr(config.config, "latitude"), "config missing latitude"
    assert hasattr(config.config, "longitude"), "config missing longitude"
    assert hasattr(
        config.config, "dusk_offset_minutes"
    ), "config missing dusk_offset_minutes"
    assert hasattr(
        config.config, "dawn_offset_minutes"
    ), "config missing dawn_offset_minutes"
    assert hasattr(config.config, "ring_api_token"), "config missing ring_api_token"
    assert hasattr(config.config, "ollama_base_url"), "config missing ollama_base_url"


# ============================================================================
# test_gitignore_has_required_entries — verify .gitignore contents
# Checks that all Stage 0 required entries are present in .gitignore.
# ============================================================================

def test_gitignore_has_required_entries() -> None:  # noqa: D401, D205
    """Verify .gitignore contains all Stage 0 required entries."""
    gitignore_path = PROJECT_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore not found at project root"

    content = gitignore_path.read_text()

    required_entries = [
        "__pycache__",
        "*.egg-info",
        "logs/",
        ".env",
        "data/examples.db",
        "~/.ollama/models",
    ]

    for entry in required_entries:
        assert (
            entry in content
        ), f".gitignore missing required entry: {entry!r}"
