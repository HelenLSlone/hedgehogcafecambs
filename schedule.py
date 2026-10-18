#!/usr/bin/env python3
"""
schedule.py — Stage 0 Schedule Trigger (Mac launchd .plist wrapper)

When launched by launchd at the time configured via pipeline_trigger_time in
.env, this script fires run_pipeline().
It can also be invoked directly from the CLI for testing:
    python schedule.py --test-now

The accompanying .plist is expected to live at:
    Library/LaunchAgents/com.hedeghogcambs.pipeline.plist
"""

import argparse
import logging
import sys
from pathlib import Path
from subprocess import run as _sub_run


def make_plist() -> Path:
    """Write (or overwrite) the launchd plist to the standard location."""
    from config import config  # delay import so argparse-first path still works

    home = Path.home()
    plist_dir = home / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)

    trigger_time = config.pipeline_trigger_time
    start_hour = str(trigger_time.hour)
    start_minute = str(trigger_time.minute).zfill(2)

    plist_path = plist_dir / "com.hedeghogcambs.pipeline.plist"
    plist_content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hedeghogcambs.pipeline</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/env</string>
        <string>python3</string>
        <string>{SCRIPT_PATH}</string>
    </array>
    <key>StartHour</key>
    <integer>{start_hour}</integer>
    <key>StartMinute</key>
    <integer>{start_minute}</integer>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
""".replace("{SCRIPT_PATH}", str(Path(__file__).resolve()))

    plist_path.write_text(plist_content)
    return plist_path


def load_plist(plist_path: Path, domain: str = "com.hedeghogcambs.pipeline") -> int:
    """Load the .plist into launchd so it fires at pipeline_trigger_time."""
    from config import config

    _sub_run(["launchctl", "load", str(plist_path)], check=True)
    trigger_str = config.pipeline_trigger_time.strftime("%H:%M")
    print(f"Loaded {plist_path} — pipeline will now trigger daily at {trigger_str}.")

    # Register domain name so `launchctl list` recognises it
    try:
        _sub_run(
            ["launchctl", "assign-name", domain, "process"],
            check=False,
        )
    except Exception:
        pass  # Domain registration is optional for basic operation

    return 0


def unload_plist(plist_path: Path, domain: str = "com.hedeghogcambs.pipeline") -> int:
    """Unload the .plist (disable daily trigger)."""
    from config import config

    _sub_run(["launchctl", "unload", str(plist_path)], check=True)
    trigger_str = config.pipeline_trigger_time.strftime("%H:%M")
    print(f"Unloaded {plist_path} — daily {trigger_str} trigger disabled.")

    try:
        _sub_run(
            ["launchctl", "unassign-name", domain, "process"],
            check=False,
        )
    except Exception:
        pass

    return 0


def fire_now() -> int:
    """Run the pipeline immediately (for testing)."""
    print("[TEST-MODE] Pipeline firing now.")
    # Import here to avoid circular imports when run_pipeline isn't on sys.path
    import os, subprocess as sp
    result = sp.run(
        [sys.executable, str(Path(__file__).parent / "run_pipeline.py")],
        cwd=str(Path(__file__).parent),
    )
    return result.returncode


def fire_pipeline() -> int:
    """Run the pipeline via subprocess (same path as --test-now)."""
    from config import config

    trigger_str = config.pipeline_trigger_time.strftime("%H:%M")
    print(f"[schedule] {trigger_str} trigger — running pipeline now.")
    import sys as _sys
    return _sub_run(
        [_sys.executable, str(Path(__file__).parent / "run_pipeline.py")],
        cwd=str(Path(__file__).parent),
        timeout=300,  # 5-minute safety cap for the full mock pipeline
    ).returncode


def main() -> int:
    """Default action — run the pipeline. This is what launchd calls at pipeline_trigger_time.

    For direct CLI use (not via launchd):
        python schedule.py --setup-plist   # generate & load .plist for today's trigger time
        python schedule.py --test-now      # fire pipeline now instead of waiting
        python schedule.py --unload-plist  # disable the daily trigger
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="schedule.py — Stage 0 launchd wrapper",
        epilog="Without args: runs the pipeline (this is what launchd invokes at pipeline_trigger_time).",
    )
    parser.add_argument("--setup-plist", action="store_true", help="Generate and load the .plist for today's trigger time triggers")
    parser.add_argument("--unload-plist", action="store_true", help="Unload the .plist (disable daily trigger)")
    parser.add_argument("--test-now", action="store_true", help="Fire pipeline now instead of waiting for scheduled trigger")

    args = parser.parse_args()

    if args.test_now:
        return fire_now()

    if args.setup_plist:
        plist_path = make_plist()
        return load_plist(plist_path)

    if args.unload_plist:
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist_path = plist_dir / "com.hedeghogcambs.pipeline.plist"
        if plist_path.exists():
            return unload_plist(plist_path)
        print("No .plist found — nothing to unload.")
        return 0

    # No CLI flags passed → launchd at pipeline_trigger_time (or user ran `python schedule.py` directly).
    # Fire the pipeline.
    return fire_pipeline()


if __name__ == "__main__":
    sys.exit(main())
