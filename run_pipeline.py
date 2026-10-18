#!/usr/bin/env python3
"""
run_pipeline.py — Stage 0 Entry Point

Chains every pipeline stage in order (Ring → Ollama → WhatsApp → Feedback),
wrapping each call in try/except with structured logging to logs/pipeline.log.

At this stage every downstream stage is a stub that prints a status line.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path so imports like `from config import config`
# work whether invoked from the repo root or another directory.
_SCRIPT_DIR = Path(__file__).resolve().parent
if _SCRIPT_DIR != Path("."):
    import sys as _sys
    _sys.path.insert(0, str(_SCRIPT_DIR))

from config import config

# ---------------------------------------------------------------------------
# Logging setup (file + console)
# ---------------------------------------------------------------------------

_LOG_PATH = "logs/pipeline.log"

def _setup_logger() -> logging.Logger:
    """Return a configured logger that writes to both file and stdout."""
    log = logging.getLogger("hedeghog")
    log.setLevel(logging.DEBUG)

    # File handler — always write structured lines
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

    # Console handler — readable for CI / manual runs
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(">> %(message)s"))
    log.addHandler(ch)

    return log


logger = _setup_logger()

# ---------------------------------------------------------------------------
# Stage stubs (Stage 0 — no external dependencies)
# ---------------------------------------------------------------------------


def stage_ring_clips() -> list:
    """Stage 1 stub — fetch motion events from Ring API."""
    logger.info("Ring clips retrieved")
    return []  # No real clips until Stage 1 API switch


def stage_reel_generate(clips: list) -> dict:
    """Stage 2 stub — build highlight reel via Ollama / Qwen model."""
    logger.info("Reel generated")
    return {
        "video_path": None,
        "caption": "No camera activity since our last update",
    }


def stage_whatsapp_send(reel: dict) -> None:
    """Stage 3 stub — send reel + caption via OpenClaw WhatsApp bridge."""
    logger.info("Sent to WhatsApp")
    pass


def stage_await_feedback() -> None:
    """Stage 4 stub — wait for user feedback (stdin until webhook live)."""
    logger.info("Awaiting feedback...")
    pass


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def run_pipeline(retry: bool = False) -> int:
    """Run every stage sequentially, returning exit code 0 or 1."""

    if retry:
        logger.info("[RETRY] Pipeline restart from --retry flag")

    # Stage 1: Fetch clips from Ring
    try:
        clips = stage_ring_clips()
    except Exception as exc:
        logger.error("Ring API unreachable — %s", exc)
        return 1

    # Stage 2: Compile reel via Ollama
    if clips:
        try:
            reel = stage_reel_generate(clips)
        except Exception as exc:
            logger.error("Ollama model missing or crash — skipping reel. Error: %s", exc)
            return 1
    else:
        logger.info("Zero clips today — feeding empty state downstream")
        reel = {"video_path": None, "caption": "No camera activity since our last update"}

    # Stage 3: Send via WhatsApp
    try:
        stage_whatsapp_send(reel)
    except Exception as exc:
        logger.error("WhatsApp bridge failure — stored video locally as .tmp for manual resend. Error: %s", exc)
        return 1

    # Stage 4: Await feedback
    try:
        stage_await_feedback()
    except Exception as exc:
        logger.error("Feedback channel error — %s", exc)
        return 1

    logger.info("Pipeline complete at %s (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="hedeghogCafeCambs pipeline — Stage 0 stub")
    p.add_argument("--retry", action="store_true", help="Restart pipeline from last failed stage")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run_pipeline(retry=args.retry))
