"""
Stage 0 — Test Helpers & Fixtures

Common utilities for all Stage 0 tests.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ensure logs/ exists so pipeline stages that write logs/pipeline.log
# don't crash with FileNotFoundError during test runs.
(PROJECT_ROOT / "logs").mkdir(exist_ok=True)
