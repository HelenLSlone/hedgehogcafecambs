# hedeghogCafeCambs

Automated daily highlight reel pipeline — fetches motion clips from Ring camera(s) via `python-ring-doorbell`, filters by the dusk-to-dawn solar window, compiles a short video with AI narration using a local Ollama/Qwen model, and delivers it via WhatsApp (through OpenClaw). Scheduled every morning at 7 am via `launchd` on macOS.

---

## Prerequisites

| Requirement | Minimum version | Why |
|---|---|---|
| **macOS** | 12+ (Monterey) | `launchd` + modern Python |
| **Python** | 3.10 (64-bit) | Apple Silicon requires 64-bit mode; the project uses f-strings, type hints with `typing`, and modern `pathlib` |
| **Ollama** | latest | Runs the Qwen vision model locally for reel compilation |
| **OpenClaw** | latest (Docker) | WhatsApp bridge that delivers the final clip |
| **Ring account** | active | Credentials + 2FA support via `python-ring-doorbell` bridge |

---

## Quick Start

### 1. Install Python & dependencies

```bash
# Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install project dependencies
pip install -r requirements.txt
```

Verify the install:

```bash
python3 -m pytest tests/    # all Stage 0 tests should pass
```

### 2. Configure environment variables

```bash
cp .env.example .env
edit .env        # fill in your real values
```

At minimum, set these keys (full list in `.env.example`):

| Key | What to put | Example |
|---|---|---|
| `latitude` | Camera latitude | `52.2` |
| `longitude` | Camera longitude | `0.1167` |
| `ring_username` | Ring account email | `you@example.com` |
| `ring_password` | Ring account password | (your password) |
| `ring_camera_filter` | Prefix to match cameras | `"Your Camera Prefix"` |
| `ollama_model_name` | A model you have pulled locally | `qwen3-v1:30b-a3b` |

### 3. Authenticate with Ring API

Before running the pipeline, obtain a valid cached token:

```bash
python scripts/auth_ring.py
```

This script handles the two-factor auth flow interactively (prompts for OTP when required) and persists the token to `ring.token.cache`. Every subsequent pipeline run reads from this cache, calling `Auth.async_close()` on exit to prevent orphaned connections.

### 4. Ensure local services are running

**Ollama** (for Qwen vision inference):

```bash
ollama serve   # defaults to http://localhost:11434

# Confirm your chosen model is pulled
ollama list    # should show qwen3-v1:30b-a3b (or whatever you set in .env)
```

**OpenClaw** (WhatsApp bridge — Docker container):

```bash
docker ps      # confirm it's running
```

### 5. Run the pipeline manually

A single run fires every stage sequentially:

```bash
python run_pipeline.py [--date YYYY-MM-DD]
```

You should see structured log output:

```
>> Ring clips retrieved via python-ring-doorbell
>> Reel generated
>> Sent to WhatsApp
>> Awaiting feedback...
>> Pipeline complete at 2026-10-29 07:00 (UTC)
```

Logs are written to `logs/pipeline.log`.

### 6. Schedule automatic runs with launchd

Set up the daily trigger once:

```bash
python schedule.py --setup-plist
```

This generates and loads `~/Library/LaunchAgents/com.hedeghogcambs.pipeline.plist`, which tells `launchd` to fire the pipeline every morning at the configured time (default 7 am, configurable via `pipeline_trigger_time` in `.env`).

Other useful flags:

| Command | What it does |
|---|---|
| `python schedule.py --test-now` | Fire the pipeline immediately (bypasses the scheduled wait) |
| `python schedule.py --unload-plist` | Disable the daily trigger |

Verify it's scheduled:

```bash
launchctl list | grep hedeghog   # should show the com.hedeghogcambs.pipeline label
```

---

## Pipeline Overview

```
Scheduled trigger (launchd)
    │
    ▼
Solar module — compute dawn/dusk window (today + offsets)
    │
    ▼
Ring API ──► motion clips collected (via python-ring-doorbell)
    │              ▲ filters by ring_camera_filter prefix only
    ▼
Ollama / Qwen ──► highlight reel generated + caption written
    │
    ▼
OpenClaw / WhatsApp ──► clip sent to your phone
    │
    ▼
User feedback ──► accepted / rejected / comments sent back
```

---

## Features

### Dusk-to-dawn window with solar calculation

The pipeline computes civil twilight times (dawn/dusk) from the camera's lat/lon using only stdlib `math` — no third-party dependencies like `astral`. The core module (`pipeline/solar.py`) implements NOAA solar position formulas: solar declination, equation of time, and hour angle at -6° elevation (the civil twilight threshold).

The window is then widened/narrowed by configurable offsets (`dusk_offset_minutes`, `dawn_offset_minutes`). Only motion events falling within this window are collected — saving GPU cycles and avoiding irrelevant daytime clips.

### Camera name prefix filter

Only cameras whose name starts with the configured `ring_camera_filter` prefix are queried. No static list of device IDs needed — the pipeline discovers matching cameras dynamically from the Ring API on every run.

### Structured output format with Pydantic validation

Motion events are collected into a `DuskToDawnResult` Pydantic model with guaranteed shape validation at the pipeline boundary:
- Camera metadata (ID, name)
- UTC timestamps for each event
- Deep-serialised debug payloads (no live `datetime` objects)
- Download URLs for offline clip retrieval

All config values are validated via a Pydantic `EnvConfig` model at import time — missing or blank required fields cause an explicit error before any pipeline code runs.

### Launchd scheduler

The `launchd` plist is generated automatically based on `.env` settings (timezone, trigger time). No manual XML editing required.

---

## Project Structure

```
hedeghogCafeCambs/
├── config.py              # Pydantic EnvConfig — loads & validates .env at import time
├── run_pipeline.py        # Pipeline orchestrator — stages sequential chain + logging
├── schedule.py            # launchd wrapper — generates/loads the scheduled .plist on Mac
├── requirements.txt       # Python dependencies (pydantic, python-dotenv, pytest)
├── pyproject.toml         # Pylint 4.x configuration (similarity, messages, basic rules)
├── .env.example           # Reference .env template (gitignore'd in production)
├── pipeline/              # Per-stage logic — solar calc, Ring API client
│   ├── ring_client.py     # dusk-to-dawn motion event collector via python-ring-doorbell
│   └── solar.py           # Civil twilight calculation (NOAA formulas, stdlib math only)
├── scripts/               # One-shot auth and discovery tools
│   └── auth_ring.py       # Interactive 2FA auth → writes ring.token.cache
├── tests/                 # Pytest suite — stubs first, real-API tests after wiring
├── docs/                  # Architecture Decision Records & process diagrams
└── logs/pipeline.log      # Structured log output (created on first run)
```

---

## Configuration Reference

All keys in `.env` are validated at import time via Pydantic `EnvConfig`. Missing or blank required fields cause an explicit error before any pipeline code runs.

| Key | Default | Description |
|---|---|---|
| `timezone_name` | `Europe/London` | IANA timezone name |
| `latitude` | `52.2` | Camera latitude for dusk/dawn computation |
| `longitude` | `0.1167` | Camera longitude for dusk/dawn computation |
| `dusk_offset_minutes` | `30` | Minutes after sunset → window start |
| `dawn_offset_minutes` | `-30` | Minutes before sunrise → window end |
| `pipeline_trigger_time` | `07:00` | Daily launchd trigger time (HH:MM) |
| `ring_username` | _(required)_ | Ring account username/email |
| `ring_password` | _(required)_ | Ring account password |
| `ring_camera_filter` | `""` | Prefix to filter cameras dynamically |
| `ollama_base_url` | `http://localhost:11434` | Local Ollama server endpoint |
| `ollama_model_name` | `qwen3-v1:30b-a3b` | Model used for reel compilation |
| `openclaw_webhook_url` | `http://localhost:8787/api/send` | WhatsApp delivery webhook |
| `recipient_phone_number` | _(required)_ | E.164 format, e.g. `+447...` |

### Ring API auth flow

The pipeline **does not** read a raw `ring_api_token` from `.env`. Instead:

1. Run `scripts/auth_ring.py` interactively — it handles 2FA/OTP prompting.
2. On successful auth, a token cache file (`ring.token.cache`) is written.
3. `pipeline/ring_client.py` reads this cache on every run via `Auth(...)` from `python-ring-doorbell`, and calls `async_close()` on exit to prevent orphaned connections.

---

## Testing

```bash
# Run all tests with verbose output
python3 -m pytest tests/ -v

# Watch mode — re-run on file changes (requires pytest-watch)
ptw          # if you have pytest-watch installed
```

The test suite follows a **mock-first** approach: every stage has passing stub tests against Pydantic schemas before any real-API wiring begins. This ensures downstream breaks surface at test time, not in production.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Config failed to load from .env` | Ensure `.env` exists and mirrors `.env.example`; check coordinates are valid floats |
| No cameras match prefix | Verify `ring_camera_filter` matches your Ring device names exactly (case-sensitive) |
| Ollama model missing or crash | Run `ollama list` — if your model isn't listed, run `ollama pull <name>` from `.env` |
| Logs dir not found | Create `mkdir -p logs` before the first run |
| Ring API auth fails / 2FA needed | Run `python scripts/auth_ring.py` — follow interactive OTP prompt to refresh `ring.token.cache` |
| `launchd` won't load plist | Check permissions: `chmod 644 ~/Library/LaunchAgents/com.hedeghogcambs.pipeline.plist`; restart `launchd` with `sudo launchctl bootstrap global /System/Library/LaunchDaemons/` |

---

## Development Roadmap (Stage 0 → ∞)

| Stage | Status | What happens |
|---|---|---|
| **Stage 0** | ✅ Complete | Pydantic config validation, launchd trigger, solar window calc (`pipeline/solar.py`), Ring API client with `ring.token.cache` auth via `python-ring-doorbell`, structured output via Pydantic models |
| **Stage 1** | ✅ Functional | Real Ring API through `python-ring-doorbell` bridge — dusk-to-dawn filtering by camera name prefix + motion events collection |
| **Stage 2** | 📋 Planned | Replace Ollama stub with actual frame fetch + Qwen vision pipeline for highlight reel compilation |
| **Stage 3** | 📋 Planned | Connect OpenClaw/WhatsApp webhook for live clip delivery |
| **Stage 4** | 📋 Planned | Feedback loop — reject clips, store accepted examples in SQLite |

---

Licensed under the terms specified in the `LICENSE` file.
