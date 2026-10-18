"""
Stage 0 — Test Helpers & Fixtures

Common utilities for all Stage 0 tests.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ensure_logs_dir() -> None:
    """Stage 0 pipeline creates logs/pipeline.log; ensure parent exists."""
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
