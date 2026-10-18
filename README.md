# hedeghogCafeCambs

Automated daily highlight reel pipeline — captures motion clips from Ring cameras via a third-party bridge, compiles them into a short video with AI narration using a local Qwen model on Ollama, and sends the result to your phone via WhatsApp (through OpenClaw). Runs automatically at 7 am via `launchd` on macOS.

---

## Prerequisites

| Requirement | Minimum version | Why |
|---|---|---|
| **macOS** | 12+ (Monterey) | `launchd` + modern Python |
| **Python** | 3.10 (64-bit) | 64-bit mode required on Apple Silicon; the project uses f-strings, type hints with `typing`, and modern `pathlib` |
| **Ollama** | latest | Runs the Qwen vision model locally for reel compilation |
| **OpenClaw** | latest (Docker) | WhatsApp bridge that delivers the final clip |
| **Ring account** | active | API access token from your chosen third-party bridge |

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
pytest tests/    # all Stage 0 stub tests should pass
```

### 2. Configure environment variables

```bash
cp .env.example .env
edit .env        # fill in your real values
```

At minimum, set:

| Key | What to put | Example |
|---|---|---|
| `latitude` | Camera latitude | `52.2` |
| `longitude` | Camera longitude | `0.1167` |
| `ring_api_token` | Token from your Ring bridge | (provided by bridge) |
| `ollama_model_name` | A model you have pulled locally | `qwen3-v1:30b-a3b` |

### 3. Ensure local services are running

**Ollama** (for Qwen vision inference):

```bash
# Run the Ollama server in the foreground, or load the launchd plist from ollama's installer
ollama serve   # defaults to http://localhost:11434

# Confirm your chosen model is pulled
ollama list    # should show qwen3-v1:30b-a3b (or whatever you set in .env)
```

**OpenClaw** (WhatsApp bridge — Docker container):

```bash
# Follow your bridge's setup docs; the default webhook URL in .env is
# http://localhost:8787/api/send
docker ps      # confirm it's running
```

### 4. Run the pipeline manually

A single dry-run fires every stage (currently stubbed — real API wiring happens in Stage 1+):

```bash
python run_pipeline.py
```

You should see structured log output:

```
>> Ring clips retrieved
>> Reel generated
>> Sent to WhatsApp
>> Awaiting feedback...
>> Pipeline complete at 2026-10-18 07:00 (UTC)
```

Logs are written to `logs/pipeline.log`.

### 5. Schedule automatic 7 am runs with launchd

Set up the daily trigger once:

```bash
python schedule.py --setup-plist
```

This generates and loads `~/Library/LaunchAgents/com.hedeghogcambs.pipeline.plist`, which tells `launchd` to fire the pipeline every morning at 7 am.

Other useful flags:

| Command | What it does |
|---|---|
| `python schedule.py --test-now` | Fire the pipeline immediately (bypasses the 7 am wait) |
| `python schedule.py --unload-plist` | Disable the daily 7 am trigger |

Verify it's scheduled:

```bash
launchctl list | grep hedeghog   # should show the com.hedeghogcambs.pipeline label
```

---

## Pipeline Overview

```
7 am (launchd)
    │
    ▼
Ring API ──► motion clips collected
    │
    ▼
Ollama / Qwen ──► highlight reel generated + caption written
    │
    ▼
OpenClaw / WhatsApp ──► clip sent to your phone
    │
    ▼
User feedback ──► accepted / rejected / comments sent back
```

| Stage | Purpose | Dependencies |
|---|---|---|
| **1 — Ring** | Fetch motion clips from cameras filtered by "Hedgehog Cam" name prefix | `ring_api_token`, bridge library (Stage 1 TBD) |
| **2 — Ollama** | Compile clips into a highlight reel with AI narration (`qwen3-v1:30b-a3b`) | local Ollama server, pulled Qwen model |
| **3 — OpenClaw** | Deliver the clip via WhatsApp | Docker container running OpenClaw WhatsApp bridge |
| **4 — Feedback** | Await user decision (reject → delete; accept/comment → store as example) | webhook or chat endpoint wired up |

Runtime filters applied automatically:

- **Camera name prefix**: only cameras whose name starts with `"Hedgehog Cam"` are queried. No config list of device IDs needed.
- **Dusk-to-dawn window**: clips outside the computed sunset/sunrise window (configurable lat/lon + offsets in `.env`) are dropped before reaching Ollama, saving GPU cycles.

---

## Project Structure

```
hedeghogCafeCambs/
├── config.py          # All pipeline config — loaded & validated from .env at import time
├── run_pipeline.py    # Stage 0 entry point — chains every stage sequentially
├── schedule.py        # launchd wrapper — generates/loads the 7 am .plist on Mac
├── requirements.txt   # Python dependencies (pydantic, python-dotenv, pytest)
├── .env.example       # Reference .env template (gitignore'd in production)
├── pipeline/          # Per-stage logic directories — grow as each stage is wired
├── tests/             # Pytest suite — stubs first, real-API tests after wiring
├── docs/              # ArchitectureDecisionRecords & process diagrams
└── logs/pipeline.log  # Structured log output (created on first run)
```

---

## Testing

```bash
# Run all tests with verbose output
pytest tests/ -v

# Watch mode — re-run on file changes
ptw          # if you have pytest-watch installed
```

The test suite follows a **mock-first** approach: every stage has passing stub tests against Pydantic schemas before any real-API wiring begins. This ensures downstream breaks surface at test time, not in production.

## Configuration Reference

Key settings in `.env` (full list in `.env.example`):

| Key | Default | Description |
|---|---|---|
| `latitude` | `52.2` | Camera latitude for dusk/dawn computation |
| `longitude` | `0.1167` | Camera longitude for dusk/dawn computation |
| `dusk_offset_minutes` | `30` | Minutes after sunset → window start |
| `dawn_offset_minutes` | `-30` | Minutes before sunrise → window end |
| `ring_api_token` | _(empty)_ | Authentication token for Ring bridge |
| `ollama_base_url` | `http://localhost:11434` | Local Ollama server endpoint |
| `ollama_model_name` | `qwen3-v1:30b-a3b` | Model used for reel compilation |
| `openclaw_webhook_url` | `http://localhost:8787/api/send` | WhatsApp delivery webhook |

Config is validated at import time via Pydantic — missing or malformed values cause a clear error before any pipeline code runs.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Config failed to load from .env` | Ensure `.env` exists and mirrors `.env.example`; check coordinates are valid floats |
| `Ollama model missing or crash` | Run `ollama list` — if your model isn't listed, run `ollama pull <name>` from `.env` |
| Logs dir not found | Create `mkdir -p logs` before the first run |
| `launchd` won't load plist | Check permissions: `chmod 644 ~/Library/LaunchAgents/com.hedeghogcambs.pipeline.plist`; restart `launchd` with `sudo launchctl bootstrap global /System/Library/LaunchDaemons/` |

---

## Development Roadmap (Stage 0 → ∞)

| Stage | Status | What happens |
|---|---|---|
| **Stage 0** | ✅ scaffold | Pydantic config validation, stub pipeline chain, launchd trigger |
| **Stage 1** | 🚧 TBD | Wire real Ring API through third-party bridge (e.g. `python-ring-doorbell`) |
| **Stage 2** | 📋 Planned | Replace Ollama stub with actual frame fetch + Qwen vision pipeline |
| **Stage 3** | 📋 Planned | Connect OpenClaw/WhatsApp webhook for live delivery |
| **Stage 4** | 📋 Planned | Feedback loop — reject clips, store accepted examples in SQLite |

---

Licensed under the terms specified in the `LICENSE` file.
