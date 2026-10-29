#!/usr/bin/env python3
"""
run_pipeline.py

Chains every pipeline stage in order (Ring -- Ollama -- WhatsApp -- Feedback),
wrapping each call in try/except with structured logging to logs/pipeline.log.

At this stage every downstream stage is a stub that prints a status line.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path

from pipeline.ring_client import main
from pipeline.solar import get_window_with_offsets

# Ensure the project root is on sys.path so imports like `from config import config`
# work whether invoked from the repo root or another directory.
_SCRIPT_DIR = Path(__file__).resolve().parent
if _SCRIPT_DIR != Path("."):
    sys.path.insert(0, str(_SCRIPT_DIR))


# ---------------------------------------------------------------------------
# Logging setup (file + console)
# ---------------------------------------------------------------------------

_LOG_PATH = "logs/pipeline.log"


def _setup_logger() -> logging.Logger:
    """Return a configured logger that writes to both file and stdout."""
    log = logging.getLogger("hedeghog")
    log.setLevel(logging.DEBUG)

    # File handler -- always write structured lines
    try:
        fh = logging.FileHandler(_LOG_PATH)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        ))
        log.addHandler(fh)
    except OSError:
        # logs dir may not exist yet or .gitignore prevented mkdir access
        pass

    # Console handler -- readable for CI / manual runs
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(">> %(message)s"))
    log.addHandler(ch)

    return log


logger = _setup_logger()

# ---------------------------------------------------------------------------
# Stage stubs (Stage 0 -- no external dependencies)
# ---------------------------------------------------------------------------


def stage_reel_generate(clips: list) -> dict:  # pylint: disable=unused-argument
    """Stage 2 stub -- build highlight reel via Ollama / Qwen model."""
    logger.info("Reel generated")
    return {
        "video_path": None,
        "caption": "No camera activity since our last update",
    }


def stage_whatsapp_send(reel: dict) -> None:  # pylint: disable=unused-argument
    """Stage 3 stub -- send reel + caption via OpenClaw WhatsApp bridge."""
    logger.info("Sent to WhatsApp")


def stage_await_feedback() -> None:
    """Stage 4 stub -- wait for user feedback (stdin until webhook live)."""
    logger.info("Awaiting feedback...")


# ---------------------------------------------------------------------------
# Pipeline orchestration helpers
# ---------------------------------------------------------------------------


def _fetch_solar_window(date_str: str | None) -> tuple[datetime, datetime] | None:
    """Compute dawn--dusk window; returns None on failure.

    Separated to keep ``run_pipeline`` under pylint's return-statement threshold.
    """
    try:
        target_date: _date | None = None
        if date_str:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        window_start, window_end = get_window_with_offsets(target_date)
        logger.info("Computed solar window: %s --> %s",
                     window_start.isoformat(), window_end.isoformat())
        return (window_start, window_end)
    except ValueError as exc:
        logger.error("Solar computation failed -- %s", exc)
        return None


async def _run_ring_stage(window_start: datetime, window_end: datetime
                         ) -> list[dict]:
    """Call ring_client.main() and return clips.

    Separated to keep ``run_pipeline`` under pylint's return-statement threshold.
    """
    try:
        result = await main(window_start, window_end)
        clips = result.events if result else []
        logger.info("Fetched %d clips from Ring API", len(clips))
        return clips
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        logger.error("Ring API call failed -- %s", exc)
        raise


def _run_stages_after_fetch(clips: list) -> int:
    """Run stages 2-4 after fetching clips; returns exit code.

    Separated to keep ``run_pipeline`` under pylint's return-statement threshold.
    """
    if not clips:
        logger.info("No clips today")
        return 0

    # Stage 2: Compile reel via Ollama
    try:
        reel = stage_reel_generate(clips)
    except Exception as exc:  # pylint: disable=broad-exception-caught # is a stub stage
        logger.error("Ollama model missing/crash -- skipping reel: %s", exc)
        return 1

    # Stage 3: Send via WhatsApp
    try:
        stage_whatsapp_send(reel)
    except Exception as exc:  # pylint: disable=broad-exception-caught # is a stub stage
        logger.error("WhatsApp bridge failure -- stored locally for manual resend: %s",
                     exc)
        return 1

    # Stage 4: Await feedback
    try:
        stage_await_feedback()
    except Exception as exc:  # pylint: disable=broad-exception-caught # is a stub stage
        logger.error("Feedback channel error -- %s", exc)
        return 1

    logger.info("Pipeline complete at %s (UTC)",
                datetime.now(UTC).strftime("%Y-%m-%d %H:%M"))
    return 0


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def run_pipeline(retry: bool = False, date_str: str | None = None) -> int:
    """Run every stage sequentially, returning exit code 0 or 1."""

    if retry:
        logger.info("[RETRY] Pipeline restart from --retry flag")

    # Compute the solar dawn --> dusk window (today's lat/lon + offsets)
    solar_window = _fetch_solar_window(date_str)
    if solar_window is None:
        return 1

    # Fetch clips via Ring API
    try:
        clips = asyncio.run(_run_ring_stage(*solar_window))
    except Exception:  # pylint: disable=broad-exception-caught # is a stub stage
        return 1

    # Run stages 2-4
    return _run_stages_after_fetch(clips)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="hedeghogCafeCambs pipeline -- Stage 0 stub")
    p.add_argument("--retry", action="store_true",
                   help="Restart pipeline from last failed stage")
    p.add_argument("--date", type=str,
                   help="Specify the date for the pipeline in YYYY-MM-DD format")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run_pipeline(retry=args.retry, date_str=args.date))
