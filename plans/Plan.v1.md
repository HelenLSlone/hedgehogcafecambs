# hedgehogCafeCambs — V1 Implementation Plan

## Overview

7am-triggered pipeline: **Ring camera → AI highlight reel (video compilation) → WhatsApp delivery via OpenClaw Docker container → user feedback**. Built iteratively, one stage at a time, mock-first. Each stage is validated as a mock before wiring to the real API. The process diagram is in [docs/Process.v1.md](../plans/Plan.v1.md).

> **Note:** This plan uses the "third-party bridge" approach for Ring camera access (no official Smart Home API or OAuth flow). See Stage 1 Open Items for details.
>
> **Feedback loop detail:** After OpenClaw Docker setup completes (Stage 3 pre-condition), incoming WhatsApp messages POST to a local HTTP callback endpoint, which is registered at `response_handler.py`'s inbound route. Until that endpoint exists, feedback is mocked via stdin. The swap boundary is: *when QR scan completes and OpenClaw webhook URL becomes available.*

---

## Stage 0 — Scaffold + Schedule Trigger (No External Dependencies)

**Goal**: Establish the runnable entry point, schedule trigger, error handling shell, and configuration scaffold. Scheduled at 7am via Mac launchd (`.plist`) — default approach; Python `sched` stays as a secondary fallback.

| Step | Build | Validate |
|---|---|---|
| `schedule.py` — wrapper using Mac launchd `.plist` entry for 7am scheduling | Fires at 7am, prints timestamp | Check it fires and survives reboots |
| `run_pipeline.py` — calls each stage function sequentially; wraps every call in try/except with logging to `logs/pipeline.log` | Output: "Ring clips retrieved", "Reel generated", "Sent to WhatsApp", "Awaiting feedback..." | Read the output stream end-to-end |
| `config.py` — empty scaffold with TODO comments for all keys, phone numbers, credentials | Every stage imports from here rather than hardcoded values | Verify no secret leaks into committed history |
| Empty `requirements.txt` (to be populated per stage) and updated `.gitignore` | Prevents accidental commits of DB files, logs, env secrets | Review `.gitignore` contents before first add |

**Error handling shell:** Each stage wrapped in try/except that writes to `logs/pipeline.log`:
- Ring API unreachable → retry queue, log failure, optionally fire local alert
- Ollama model missing/crashes → skip reel generation entirely, do not proceed with empty captions
- WhatsApp bridge failure → store compiled video locally as `.tmp` for manual resend later

**Files:** `schedule.py`, `run_pipeline.py`, `config.py`, `requirements.txt`, `pipeline/__init__.py`, `data/`, `logs/`
**.gitignore updates (Stage 0):** `__pycache__/`, `*.egg-info/`, `logs/`, `.env`, `data/examples.db`. Research and add Ollama cache path (`~/.ollama/models/`) as soon as model is confirmed.

---

## Stage 1 — Ring API (Mock → Real, *third-party bridge approach*)
**Goal**: Fetch motion events and clip URLs from the Ring camera via a third-party bridge (not official Smart Home API OAuth).

| Step | Build | Mock State | Swap When |
|---|---|---|---|
| `ring_api_schema.py` — defines clip dict contract: `{clip_id, url, timestamp, duration, motion_score, thumbnail_url}` | Shared import for all downstream stages | N/A — this is the data contract only | N/A (no swap needed) |
| `pipeline/ring_client.py` — fetches clips via third-party bridge; returns list of clip dicts matching schema | **Mock:** hardcoded test data (3 sample clip dicts with all defined fields) | Bridge library/package becomes available + test access works | → Real: replace mock with real HTTP call via the bridge |
| "Zero clips today" branch — when no motion events returned, pass `empty_feed=True` downstream | Stage 2 handles gracefully ("No camera activity since our last update") | Always present in staging/mock phase | No-op once real API works |

**Validation:** Clips retrieved have all schema fields needed by Stage 2. Print each before moving on. "Zero clips" path produces empty list → `empty_feed=True` flag passed to next stage.

**Open Items:**
- Discover which third-party Ring bridge library/package is most reliable (search PyPI, GitHub). Options may include `ring-smart-home` Python package or similar community bridges.
- Determine authentication method for the chosen bridge (token? local network sniffing?).

---

## Stage 2 — AI Highlight Reel (Mock → Real, *Qwen Ollama model with video compilation*)
**Goal**: Generate a compiled highlight reel (.mp4/.mov) from clip URLs + metadata using a Qwen-based Ollama model capable of multi-step code execution (ffmpeg orchestration).

### Model Selection Specification

The selected Ollama Qwen model must fulfil all of the following capabilities:

1. **Species identification / visual classification** — The model must be able to analyse each clip and determine whether a hedgehog is visible in the frame. Only clips where a hedgehog is detected should pass through. Clips showing other animals, people, or empty scenes are excluded.
2. **Dead footage trimming** — The model must identify and cut out any dead frames (e.g., static/blank frames, moments with no motion or activity) from each clip before it is included in the final reel.
3. **Reel compilation & hard duration limit** — All remaining clips (hedgehog-containing + trimmed of dead frames) must be stitched together into a single compiled .mp4/.mov file using `ffmpeg concat` (or equivalent). The final reel **must never exceed 3 minutes total runtime**. If eligible clips would produce a reel longer than 3 minutes, curation/trimming logic is applied to meet the cap.

**Selection process:** Run `ollama list`, review each candidate model's README/capabilities for video analysis and CLI script execution (ffmpeg orchestration). Test by pulling+running the model against sample footage before committing to use it. Determine if a pre-built `qwen-code` model suffices or if we need to build the agent ourselves using a base code model combined with prompt-based visual classification commands.

---

| Step | Build | Mock State | Swap When |
|---|---|---|---|
| **Research phase** — Identify available Ollama Qwen models (`ollama list`), check READMEs/capabilities for video stitching or CLI script execution and visual analysis capabilities (hedgehog detection, dead-frame trimming). | Research task BEFORE any implementation begins. Discover model capabilities, test pull + run against sample footage. | Still doing research (no implementation start) | After confirmed a viable model exists that can compile video output AND meet the spec above |
| `pipeline/reel_generator.py` — Takes list of clips with metadata; uses Ollama code/agent model to: (a) classify each clip for hedgehog presence, (b) trim dead frames from qualifying clips, (c) stitch eligible clips together into a ≤3 min reel. Produces compiled .mp4/.mov file + caption text as metadata. | **Mock:** hardcoded sample output (a test `.mp4` placeholder or no-op that prints "Compiled reel: highlights.mp4") and sample caption string ("Cafe buzzed today — baristas on the terrace...") | After Qwen model discovery succeeds AND passes spec validation (research is complete) | → Real: Ollama runs video analysis, produces real trimmed/stitched .mp4 video file |

**Error handling:** If Ollama model pull fails or compilation breaks → skip reel entirely, store warning in `logs/pipeline.log`, do NOT proceed with empty captions. If no clips contain a hedgehog after classification → produce "No hedgehogs spotted today" fallback message (no video compiled).

**.gitignore updates (Stage 2):** Add discovered Ollama cache path (`~/.ollama/models/`) — critical, this is massive disk space and must not be committed.

**Validation:** Caption reads like a coherent cafe update, not boilerplate. Compiled .mp4/.mov file exists and is playable. Print caption metadata before passing to WhatsApp step.

---

## Stage 3 — WhatsApp via OpenClaw (Mock → Real, *Docker container ready first*)
**Goal**: Deliver the highlight reel summary + compiled video link to your phone via WhatsApp through OpenClaw Docker container.

> **Pre-condition:** OpenClaw Docker MUST install + QR-scan WhatsApp BEFORE wiring begins. Currently: Docker installed, but OpenClaw / WhatsApp not yet configured. This is a hard blocker for Stage 3 real wiring and Stage 4 feedback loop.

| Step | Build | Mock State | Swap When |
|---|---|---|---|
| `pipeline/whatsapp_sender.py` — sends compiled reel + caption to recipient number via OpenClaw HTTP API | **Mock:** prints "Would send to [number]: [caption]" + notes video file path for delivery | You confirm OpenClaw Docker is running and QR scan completed successfully | → Real: replace mock with real HTTP POST to OpenClaw container |
| Install OpenClaw Docker container, connect WhatsApp via QR code scan (Manual setup step) | **Pre-condition** — DO THIS BEFORE wiring. Blocklisted until complete | Not wired yet | After mock is verified working and Docker is available |
| Wire real API call in whatsapp_sender.py | POST compiled reel link + caption to OpenClaw's messaging endpoint | → Real | N/A |

**Error handling:** If OpenClaw container crashes or misses WhatsApp delivery → store compiled video locally as `.tmp` for manual resend. Log failure and retry later.

**Validation:** Caption passes through intact. Compiled .mp4/.mov is delivered or link works. Test with a real message after Docker + QR setup completes.

---

## Stage 4 — User Feedback + Example Storage
**Goal**: Handle user response; store accepted clips as metadata-only examples (see note below), delete rejected ones.

| Step | Build | Notes |
|---|---|---|
| `pipeline/response_handler.py` — Simulate incoming feedback (stdin or HTTP endpoint). Route: "Accepted" → store to SQLite, "Rejected" → mark as deleted in DB | Mock first; no real webhook until OpenClaw is wired | Feedback channel: when OpenClaw inbound webhook is live, route incoming WhatsApp messages to `response_handler.py`'s listener. Until then, stdin-only for testing |
| `data/examples_store.py` — SQLite store for **metadata only** (NOT full video files). Schema: `id INTEGER PRIMARY KEY, clip_id TEXT, clip_url TEXT, timestamp DATETIME, reel_caption TEXT, status TEXT CHECK(status IN ('accepted','rejected'))`. No download archival — Ring API stays source of truth for replay. | Real implementation (SQLite only, no external deps) | Use WAL mode for better concurrency. Track feed state (`pending/accepted/rejected`) to prevent re-deleting or double-storing across daily runs |

**Validation:** Accept + reject both produce correct side effects. Query back an example after storing it. Verify `status` field prevents duplicate inserts across scheduled runs.

> **Note: "Store original clips" means metadata only (Option B from plan review), NOT downloading full MP4 video files. This saves significant disk space; Ring API remains the source of truth for replaying video.**

---

## Stage 5 — End-to-End Wiring
**Goal**: All real stages chained together in one cron-triggered command. Add structured logging, pipeline retry/idempotency logic, and a staged acceptance test that accounts for feedback channel availability.

| Step | What |
|---|---|
| Hook `run_pipeline.py` → all real APIs in sequence (with `--retry` flag support for idempotent restart from any failed stage) | Single-shot pipeline execution; restart cleanly without side effects on prior stages |
| Add retry logic, structured logging to file (`logs/pipeline.log`) | Pipeline survives API hiccups; logs every failure type with context |
| **Staged acceptance tests:** (1) Mock-first end-to-end validation with test stubs + mocked feedback via stdin. (2) Real-API end-to-end per-stage swaps validated before full chain: Ring mock → Ollama mock → WhatsApp mock → stdin feedback = GREEN ✅ Then swap each, one at a time. | Full pipeline verified in two passes: mock first, then real-only |
| **WHATSAPP CANNOT WORK:** Do NOT initially run "Reply 'Accepted' through live WhatsApp" unless OpenClaw inbound webhook is live and wired. This test path was removed from initial acceptance because it requires feedback channel to exist | Feedback testing stays mock until QR scan + callback setup complete |

---

## Target Directory

```
hedgehogCafeCambs/                   # ← corrected spelling (was "hedgihog")
├── schedule.py              # Mac launchd trigger for 7am schedule
├── run_pipeline.py          # Entry point (chained pipeline, --retry support)
├── config.py                # API keys, phone numbers, credentials scaffold (TODO: add per stage)
├── requirements.txt         # Python deps (populated as stages are built)
├── logs/                    # Pipeline execution logs (.gitignore'd)
│   └── pipeline.log         # Structured log output
├── pipeline/
│   ├── __init__.py
│   ├── ring_api_schema.py   # Stage 1: Clip dict contract definition
│   ├── ring_client.py       # Stage 1: Ring camera API via third-party bridge
│   ├── reel_generator.py    # Stage 2: Ollama video compilation + caption
│   ├── whatsapp_sender.py   # Stage 3: OpenClaw WhatsApp bridge (HTTP POST)
│   └── response_handler.py  # Stage 4: Inbound feedback from stdin or OpenClaw webhook
├── data/
│   ├── examples_store.py    # SQLite persistence for metadata-only accepted examples
│   └── examples.db          # Created after first successful store; .gitignore'd
└── .gitignore               # Updated Stage 0: __pycache__*, *.egg-info, logs/, .env, data/examples.db, ~/.ollama/models/
```

---

## Open Items / Decisions Pending

1. **Qwen Ollama model research (STAGE 0–1 PRIORITY):** Which available Qwen Ollama model can execute code + orchestrate ffmpeg AND perform visual classification for hedgehog species identification? Discover via `ollama list`, check READMEs/capabilities for video stitching or CLI script execution and visual analysis capabilities. Determine if pre-built `qwen-code` model suffices or we need to build the agent ourselves using a base code model. **This must be resolved before any Stage 2 implementation coding begins.**
2. **Ring API bridge discovery:** Discover which third-party Ring bridge library/package is most reliable (search PyPI, GitHub). Determine authentication method for chosen bridge. Official Smart Home API OAuth approach was explicitly rejected.
3. **OpenClaw Docker + WhatsApp QR scan setup:** Still pending. Hard blocker for both Stage 3 real wiring and Stage 4's inbound feedback channel. Install OpenClaw container via Docker Desktop, complete QR flow to link WhatsApp.
4. **Ollama model cache path:** Need to confirm the exact filesystem location for `~/.ollama/models/` on this machine (may vary by platform). Add to `.gitignore`.
5. `.gitignore` population: Missing entries beyond basics — add all items listed in Target Directory section above. This is a Stage 0 deliverable.

---

## Error Handling Summary Table

| Failure Type | Action |
|---|---|
| Ring API unreachable | Retry queue, log to `logs/pipeline.log`, optionally fire local alert; skip reel + delivery if retries exhausted |
| Ollama model missing or crashes | Skip reel generation entirely; log error; do NOT proceed with empty captions or no-op video output |
| WhatsApp bridge failure | Store compiled video (.mp4) locally as `.tmp` for manual resend; log warning; retry next 7am cycle |
| No motion events at 7am | Empty feed → Stage 2 produces "No camera activity since our last update" text fallback (no video compile) |
| No hedgehogs detected after classification | Produce "No hedgehogs spotted today" fallback message; no video compiled |
| Feedback channel not yet live | Use stdin-only simulation in `response_handler.py`; wire OpenClaw webhook when Docker/QR is fully set up |

---

## Pipeline Idempotency & Retry Strategy

- `run_pipeline.py --retry` flag: restart the pipeline from any failed stage without re-executing earlier stages (e.g., if Stage 3 crashes, retry only Stage 3 onwards).
- Ring API calls are read-only and safe to re-query.
- `examples_store.py` `status` field (`pending/accepted/rejected`) tracks feed state across daily runs — prevents re-deleting or double-storing clips.
- All failures produce structured log entries in `logs/pipeline.log`.
