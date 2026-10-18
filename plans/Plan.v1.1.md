# hedgehogCafeCambs — V1 Implementation Plan

## Overview

Pipeline-triggered by configurable time (default 7am GMT, set via `.env` variable `pipeline_trigger_time=07:00`) — **Ring camera → AI highlight reel (video compilation) → WhatsApp delivery via OpenClaw Docker container → user feedback**. Built iteratively, one stage at a time, mock-first. Each stage is validated as a mock before wiring to the real API. The process diagram is in [docs/Process.v1.md](../plans/Plan.v1.md).

> **Note:** This plan uses the "third-party bridge" approach for Ring camera access (no official Smart Home API or OAuth flow). See Stage 1 Open Items for details.
>
> **Feedback loop detail:** After OpenClaw Docker setup completes (Stage 3 pre-condition), incoming WhatsApp messages POST to a local HTTP callback endpoint, which is registered at `response_handler.py`'s inbound route. Until that endpoint exists, feedback is mocked via stdin. The swap boundary is: *when QR scan completes and OpenClaw webhook URL becomes available.*

---

## Runtime Validation Strategy

**`pydantic` is the core validation library** for all data shape enforcement — both at mock-test time and in production after API wiring. It provides Zod-like runtime validation throughout the pipeline:

- **At config load time:** `config.py` values are read from `.env` into an `EnvConfig` Pydantic model, failing fast with clear errors if required keys are missing or malformed.
- **On every external API boundary:** After Ring API, Ollama, and OpenClaw calls, responses are validated against defined schemas via `model_validate()`. Invalid shapes cause a structured log entry + graceful skip/retry.
- **In tests at each stage:** Mock return values match the same Pydantic schemas used by real APIs, ensuring mock-to-real swaps cannot introduce shape mismatches.
- **At `ring_api_schema.py` (Stage 1):** The clip model becomes the canonical downstream contract; every stage after Stage 1 imports and validates against it.

**Test philosophy:** Every stage must have passing `pytest` tests written *before* its real-API wiring phase begins. Mock return values are constructed to match the same data shapes produced by the real API (validated via Pydantic at test time). This guarantees that mock-to-real swaps preserve contract compliance.

---

## Stage 0 — Scaffold + Schedule Trigger (No External Dependencies)

**Goal**: Establish the runnable entry point, schedule trigger, error handling shell, configuration scaffold, and test foundation. Read trigger time from `.env` (`pipeline_trigger_time`, default `07:00` GMT) via Mac launchd (`.plist`) — default approach; Python `sched` stays as a secondary fallback.

| Step | Build | Validate |
|---|---|---|
| `schedule.py` — reads `pipeline_trigger_time` from `.env` (default `07:00` GMT) and fires pipeline; writes to logs/pipeline.log | Fires at configured time, prints timestamp | Check it fires and survives reboots |
| `run_pipeline.py` — calls each stage function sequentially; wraps every call in try/except with logging to `logs/pipeline.log` | Output: "Ring clips retrieved", "Reel generated", "Sent to WhatsApp", "Awaiting feedback..." | Read the output stream end-to-end |
| `config.py` — empty scaffold with TODO comments for all keys, phone numbers, credentials. Uses Pydantic `BaseModel` for `.env` validation at import time. Includes timezone config (`lat`, `lon` for sunrise/sunset calculation; `dusk_offset_minutes`, `dawn_offset_minutes` for configurable window edges). | Every stage imports from here rather than hardcoded values | Verify no secret leaks into committed history |
| Empty `requirements.txt` (to be populated per stage) and updated `.gitignore` | Prevents accidental commits of DB files, logs, env secrets | Review `.gitignore` contents before first add |

**Pydantic dependency added to `requirements.txt`:** `pydantic>=2.0` — validation for all data shapes; `python-dotenv` — config loading.

**Error handling shell:** Each stage wrapped in try/except that writes to `logs/pipeline.log`:
- Ring API unreachable → retry queue, log failure, optionally fire local alert
- Ollama model missing/crashes → skip reel generation entirely, do not proceed with empty captions
- WhatsApp bridge failure → store compiled video locally as `.tmp` for manual resend later

**Tests (must pass before proceeding to Stage 1):**
- `test_schedule_fires`: Schedule fires at test timestamp override (do not hardcode the trigger time in tests)
- `test_config_loads_without_errors`: `config.py` imports cleanly, `.env` reads expected keys as strings — including `pipeline_trigger_time`
- `test_run_pipeline_calls_stubs_in_order`: `run_pipeline.py` calls stubs for each stage sequentially, in expected order
- `test_config_loads_without_errors`: `config.py` imports cleanly, `.env` reads expected keys as strings
- `test_gitignore_has_required_entries`: Verify `.gitignore` contains `__pycache__/`, `*.egg-info/`, `logs/`, `.env`, `data/examples.db`, `~/.ollama/models/` (once discovered)

---

## Stage 1 — Ring API (*Discovery-First, Reverse Engineer `python-ring-doorbell`*)

> **Exception:** The standard "mock → swap" pattern does NOT apply here.
> `python-ring-doorbell` is reverse-engineered with sparse, unreliable
> documentation — you cannot meaningfully mock what you haven't yet
> discovered.

**Goal:** Probe the real Ring API to discover camera/event structure (device
types, families, methods, metadata fields). Then implement camera-name and
dusk-to-dawn filters *against discovered reality*, not plan assumptions or
external docs.

### Phase A — Discovery Script

| Step | Build | Validate |
|---|---|---|
| `scripts/discover_ring.py` — instantiate a `Ring(client_email, client_password)` from real ``.env`` credentials; call ``ring.devices()`` and dump every attribute/method on each returnee via ``dir()``, ``__dict__``, and callable method introspection. Print camera names, families, ids, any visible metadata fields. Document all findings in a local markdown file (e.g. `docs/ring-discovery-2026-10-xx.md`). | Run against live Ring credentials: confirm no crashes from invalid auth or unsupported API paths; identify which device types/families actually exist (`doorbots`? `stickup_cams`? `chimes`?). Confirm at least one camera whose name starts with `"Hedgehog Cam"`. Note whether motion events and recording URLs are accessible, or discover they aren't. Discovery *succeeds* if you find usable data; *blocked* if no Hedgehog cameras are found or auth fails entirely (fix credentials/account before wiring). |

### Phase B — Wiring Against Discovered Reality

_The steps below only begin after Phase A completes and confirms usable
devices/events._ No more fabricated contracts.

| Step | Build | When |
|---|---|---|
| `pipeline/ring_client.py` — written against what ``ring.devices()`` **actually returns** (not Plan assumptions). Filters cameras by `"Hedgehog Cam"` name prefix at runtime; attempts to fetch motion events and clip URLs using discovered method names/families; produces list of dicts from live Ring data. | Camera-name filter validated against real objects: only cameras starting with `"Hedgehog Cam"` are selected. Time-window filter applied to whatever timestamp field the API actually provides (confirmed by Phase A). | After Phase A discovers accessible device types, event methods, and timestamp fields; wiring succeeds against live Ring API data. |
| `ring_api_schema.py` — Pydantic model built from **actual return values** observed in Phase A *and* confirmed at real-API wiring time. Every field on the schema must exist in live Ring API responses; no hallucinated fields (`motion_score`, `thumbnail_url`) may be invented. This becomes the canonical downstream contract for Stages 1+ only after Phase B wire completes and validates against real data. | Schema validated: every field matches live Ring discovery output (Phase A), not Plan docs. No fabrication — if a field doesn't exist in reality, it's removed from the model. | After Phase B completes wiring; schema tested against live API returns, not mocked input. |
| `"Zero clips today"` branch — when no motion events returned by discovered methods: return `[]` and pass `empty_feed=True` downstream. Stage 2 handles gracefully (`"No camera activity since our last update"`). | Tested against real Ring API (not mock data): zero motion events for a given day produces `[]`. Empty-feed flag reaches downstream error handling confirmed at Phase B wire time. | After Phase B confirms live Zero-Clips path works end-to-end against Ring. |

### Stage 1 Tests — Run Against Real Ring API (Not Mocks)

All tests execute against live `python-ring-doorbell` credentials and real
Ring camera data. No mock stand-ins. Testing happens *as part of wiring* —
discover first, validate second (Phase B).

- `test_discovery_runs_against_real_credentials`: `Ring(client_email, client_password)` instantiates; ``ring.devices()`` returns non-empty list of live camera objects without crashing from invalid auth or unsupported API paths.
- `test_hedgehog_cameras_filter_applies_to_discovered_devices`: Given *actual* device names/families as returned by live Ring, only cameras whose name starts with `"Hedgehog Cam"` are selected (no fabricated device types used).
- `test_dusk_to_dawn_time_window_filters_real_clips_against_ring_data`: Validate filtering works against *discovered* timestamp fields on live Ring API objects; off-window clips correctly excluded based on Phase A findings.
- `test_zero_clips_today_returns_empty_feed_and_flag_from_ring`: When no motion events for today (verified via *live* Ring API call, not a mock), pipeline returns ``[]`` and passes `empty_feed=True` downstream; confirmed end-to-end against real account data at Phase B wire time.
- `test_pydantic_schema_matches_discovered_api_shape_post_wire`: After Phase A reverse-engineers actual return values and Phase B wires them through, validate that every field on the Pydantic model exists in live Ring API responses — zero hallucinated fields allowed (`motion_score`, `thumbnail_url` etc. are rejected).

### Open Items — Stage 1

- **Discovery pending.** Until ``python-ring-doorbell`` reverse-engineering completes against real credentials, camera device types, event methods, timestamp structures, and access paths remain unknown. Phase A output (discovery notes) is the single source of truth for this stage: all wiring in Phase B derives from its output, never from Plan assumptions or external documentation.


## Stage 2 — AI Highlight Reel (Mock → Real, *Qwen Ollama model with video compilation*)
**Goal**: Generate a compiled highlight reel (.mp4/.mov) from clip URLs + metadata using a Qwen-based Ollama model capable of multi-step code execution (ffmpeg orchestration).

### Model Selection Specification

The selected Ollama Qwen model must fulfil all of the following capabilities:

1. **Species identification / visual classification** — The model must be able to analyse each clip and determine whether a hedgehog is visible in the frame. Only clips where a hedgehog is detected should pass through. Clips showing other animals, people, or empty scenes are excluded.
2. **Dead footage trimming** — The model must identify and cut out any dead frames (e.g., static/blank frames, moments with no motion or activity) from each clip before it is included in the final reel.
3. **Reel compilation & hard duration limit** — All remaining clips (hedgehog-containing + trimmed of dead frames) must be stitched together into a single compiled .mp4/.mov file using `ffmpeg concat` (or equivalent). The final reel **must never exceed 3 minutes total runtime**. If eligible clips would produce a reel longer than 3 minutes, curation/trimming logic is applied to meet the cap.
4. **Caption in the style of a British wildlife documentary narrator** — The model must generate a narrating caption for the finished reel that reads like David Attenborough (or equivalent) presenting a hedgehog segment: dry wit, understated observation, gentle awe at nature. Examples: *"Here we see our hedgehog making its daily pilgrimage to the cafe terrace — perhaps hoping for spilled coffee grounds more than acorns."* The caption should sound natural and slightly whimsical, never technical or robotic. It is delivered alongside the compiled video via WhatsApp (Stage 3).

**Selection process:** Run `ollama list`, review each candidate model's README/capabilities for video analysis and CLI script execution (ffmpeg orchestration). Test by pulling+running the model against sample footage before committing to use it. Determine if a pre-built `qwen-code` model suffices or if we need to build the agent ourselves using a base code model combined with prompt-based visual classification commands.

---

| Step | Build | Mock State | Swap When |
|---|---|---|---|
| **Research phase** — Identify available Ollama Qwen models (`ollama list`), check READMEs/capabilities for video stitching or CLI script execution and visual analysis capabilities (hedgehog detection, dead-frame trimming). | Research task BEFORE any implementation begins. Discover model capabilities, test pull + run against sample footage. | Still doing research (no implementation start) | After confirmed a viable model exists that can compile video output AND meet the spec above |
| `pipeline/reel_generator.py` — Takes list of clips with metadata; uses Ollama code/agent model to: (a) classify each clip for hedgehog presence, (b) trim dead frames from qualifying clips, (c) stitch eligible clips together into a ≤3 min reel. Produces compiled .mp4/.mov file + caption text as metadata. Validate output with Pydantic against a `CompiledReel(model_validate={'video_path': str, 'clip_urls': list[str], 'total_duration': float, 'caption': str})`. | **Mock:** hardcoded sample output (a test `.mp4` placeholder or no-op that prints "Compiled reel: highlights.mp4") and sample caption string ("Cafe buzzed today — baristas on the terrace...") | After Qwen model discovery succeeds AND passes spec validation (research is complete) | → Real: Ollama runs video analysis, produces real trimmed/stitched .mp4 video file |

**Error handling:** If Ollama model pull fails or compilation breaks → skip reel entirely, store warning in `logs/pipeline.log`, do NOT proceed with empty captions. If no clips contain a hedgehog after classification → produce "No hedgehogs spotted today" fallback message (no video compiled).

**.gitignore updates (Stage 2):** Add discovered Ollama cache path (`~/.ollama/models/`) — critical, this is massive disk space and must not be committed.

**Validation:** Caption reads like a coherent cafe update, not boilerplate. Compiled .mp4/.mov file exists and is playable. Print caption metadata before passing to WhatsApp step.

**Tests (must pass before real-API wiring at this stage):**
- `test_reel_output_passes_pydantic_schema`: Mock-generated reel output validates against `CompiledReel` Pydantic model (`video_path`, `clip_urls`, `total_duration`, `caption`)
- `test_hedgehog_classification_filters_clips`: Given a list of clips with mixed hedgehog/non-hedgehog content, only hedgehog-containing clips pass through the mock classifier
- `test_dead_frame_trimming_removes_empty_frames`: Input clip with blank/static frames is trimmed correctly in mock; resulting duration is within expected bounds
- `test_max_3min_cap_enforced_on_mock_reel`: When input clips would exceed 3 minutes, mock compilation enforces a hard cap by selecting/trimming clips to produce `total_duration <= 180.0` seconds
- `test_no_hedgehogs_detected_produces_text_fallback`: If all clips fail hedgehog classification, output is "No hedgehogs spotted today" text with no .mp4 file compiled
- `test_compiled_reel_validation_after_wiring`: After real Ollama swap, mock-to-real transition validates that any reel output from Ollama matches the Pydantic schema

---

## Stage 3 — WhatsApp via OpenClaw (Mock → Real, *Docker container ready first*)
**Goal**: Deliver the highlight reel summary + compiled video link to your phone via WhatsApp through OpenClaw Docker container.

> **Pre-condition:** OpenClaw Docker MUST install + QR-scan WhatsApp BEFORE wiring begins. Currently: Docker installed, but OpenClaw / WhatsApp not yet configured. This is a hard blocker for Stage 3 real wiring and Stage 4 feedback loop.

| Step | Build | Mock State | Swap When |
|---|---|---|---|
| `pipeline/whatsapp_sender.py` — sends compiled reel + caption to recipient number via OpenClaw HTTP API payload shape `{to: str, message: str, media_url?: str}` as Pydantic model. | **Mock:** prints "Would send to [number]: [caption]" + notes video file path for delivery | You confirm OpenClaw Docker is running and QR scan completed successfully | → Real: replace mock with real HTTP POST to OpenClaw container |
| Install OpenClaw Docker container, connect WhatsApp via QR code scan (Manual setup step) | **Pre-condition** — DO THIS BEFORE wiring. Blocklisted until complete | Not wired yet | After mock is verified working and Docker is available |
| Wire real API call in whatsapp_sender.py | POST compiled reel link + caption to OpenClaw's messaging endpoint; validate all outbound payloads against `WhatsAppMessage.model_validate()` | → Real | N/A |

**Error handling:** If OpenClaw container crashes or misses WhatsApp delivery → store compiled video locally as `.tmp` for manual resend. Log failure and retry later.

**Validation:** Caption passes through intact. Compiled .mp4/.mov is delivered or link works. Test with a real message after Docker + QR setup completes.

**Tests (must pass before real-API wiring at this stage):**
- `test_mock_sender_prints_correct_caption_and_recipient`: Given sample caption and recipient phone number, mock sender prints expected output string
- `test_compiled_video_metadata_reaches_whatsapp_body`: Compiled reel metadata (video path, duration, caption) passes intact through the full pipeline into Stage 3's mock body; all values are non-empty and valid
- `test_webhook_payload_schema_matches_openshaw_expectations`: Constructed Pydantic model for OpenClaw HTTP POST payload matches expected shape; any mismatch causes test failure before wiring

---

## Stage 4 — User Feedback + Example Storage
**Goal**: Handle user response; store accepted clips as metadata-only examples (see note below), delete rejected ones.

| Step | Build | Notes |
|---|---|---|
| `pipeline/response_handler.py` — Simulate incoming feedback (stdin or HTTP endpoint). Route: "Accepted" → store to SQLite, "Rejected" → mark as deleted in DB | Mock first; no real webhook until OpenClaw is wired | Feedback channel: when OpenClaw inbound webhook is live, route incoming WhatsApp messages to `response_handler.py`'s listener. Until then, stdin-only for testing |
| `data/examples_store.py` — SQLite store for **metadata only** (NOT full video files). Schema: `id INTEGER PRIMARY KEY, clip_id TEXT, clip_url TEXT, timestamp DATETIME, reel_caption TEXT, status TEXT CHECK(status IN ('accepted','rejected'))`. No download archival — Ring API stays source of truth for replay. | Real implementation (SQLite only, no external deps) | Use WAL mode for better concurrency. Track feed state (`pending/accepted/rejected`) to prevent re-deleting or double-storing across daily runs |

**Validation:** Accept + reject both produce correct side effects. Query back an example after storing it. Verify `status` field prevents duplicate inserts across scheduled runs.

> **Note: "Store original clips" means metadata only (Option B from plan review), NOT downloading full MP4 video files. This saves significant disk space; Ring API remains the source of truth for replaying video.**

**Tests (must pass before real-API wiring at this stage):**
- `test_accepted_routes_to_sqlite_with_correct_schema`: "Accepted" feedback writes a row into SQLite with correct Pydantic schema (`clip_id`, `clip_url`, `timestamp`, `reel_caption`) and `status='accepted'`
- `test_rejected_deletes_properly`: "Rejected" feedback deletes the correct entry in SQLite; verify row count decreases after query-back
- `test_feedback_via_stdin_and_webhook_same_side_effects`: Both stdin simulation and HTTP webhook produce identical store/delete results — no divergence in side effects between input methods
- `test_feed_state_prevents_duplicates_across_retries`: After retry logic, duplicate `clip_id` inserts are prevented via unique constraint + UPSERT pattern; query-back confirms no duplicate rows

---

## Stage 5 — End-to-End Wiring
**Goal**: All real stages chained together in one cron-triggered command. Add structured logging, pipeline retry/idempotency logic, and a staged acceptance test that accounts for feedback channel availability.

| Step | What |
|---|---|
| Hook `run_pipeline.py` → all real APIs in sequence (with `--retry` flag support for idempotent restart from any failed stage) | Single-shot pipeline execution; restart cleanly without side effects on prior stages |
| Add retry logic, structured logging to file (`logs/pipeline.log`) | Pipeline survives API hiccups; logs every failure type with context |
| **Staged acceptance tests:** (1) Mock-first end-to-end validation with test stubs + mocked feedback via stdin. (2) Real-API end-to-end per-stage swaps validated before full chain: Ring mock → Ollama mock → WhatsApp mock → stdin feedback = GREEN ✅ Then swap each, one at a time. | Full pipeline verified in two passes: mock first, then real-only |
| **WHATSAPP CANNOT WORK:** Do NOT initially run "Reply 'Accepted' through live WhatsApp" unless OpenClaw inbound webhook is live and wired. This test path was removed from initial acceptance because it requires feedback channel to exist | Feedback testing stays mock until QR scan + callback setup complete |

**Tests (must pass before shipping Stage 5 / full pipeline deployment):**
- `test_full_mock_chain_all_stages_pass`: Full mock-first end-to-end test with all stubs → Ring, Ollama, WhatsApp, stdin feedback. All stages produce expected output. GREEN ✅ before any real swap.
- `test_single_real_api_swap_ring_first`: Swap only Stage 1 (Ring) to real; all others remain mock. Verify full chain works despite live Ring call. Test fails if schema mismatch.
- `test_single_real_api_swap_ollama_next`: Swap only Stage 2 (Ollama) to real. Validate Ollama output against Pydantic schemas in both `ring_api_schema.py` and `CompiledReel`.
- `test_single_real_api_swap_whatsapp_finally`: Swap only Stage 3 (WhatsApp / OpenClaw) to real. Verify compiled reel + caption reaches OpenClaw via live HTTP POST.
- `test_full_real_chain_with_mock_feedback_until_webhook_live`: All APIs real, mock stdin feedback only — because the OpenClaw callback webhook may not be live yet. Confirm all stages flow end-to-end with data Pydantic-validated at every boundary.
- `test_full_real_chain_with_live_webhook_feedback`: The final pass — when OpenClaw inbound webhook is wired up, test real WhatsApp reply → SQLite storage. Accept + reject both produce correct side effects.

---

## Target Directory

```
hedgehogCafeCambs/
├── schedule.py              # Mac launchd trigger; reads pipeline_trigger_time from .env (default 07:00 GMT)
├── run_pipeline.py          # Entry point (chained pipeline, --retry support)
├── config.py                # API keys, phone numbers, credentials scaffold (TODO: add per stage)
├── requirements.txt         # Python deps (populated as stages are built; includes pydantic, python-dotenv, pytest)
├── logs/                    # Pipeline execution logs (.gitignore'd)
│   └── pipeline.log         # Structured log output
├── pipeline/
│   ├── __init__.py
│   ├── ring_api_schema.py   # Stage 1: Clip dict contract as Pydantic model validation schema
│   ├── ring_client.py       # Stage 1: Ring camera API via third-party bridge
│   ├── reel_generator.py    # Stage 2: Ollama video compilation + caption (Pydantic output validated)
│   ├── whatsapp_sender.py   # Stage 3: OpenClaw WhatsApp bridge (HTTP POST, Pydantic payload validation)
│   └── response_handler.py  # Stage 4: Inbound feedback from stdin or OpenClaw webhook
├── data/
│   ├── examples_store.py    # SQLite persistence for metadata-only accepted examples
│   └── examples.db          # Created after first successful store; .gitignore'd
└── .gitignore               # Updated Stage 0: __pycache__*, *.egg-info, logs/, .env, data/examples.db, ~/.ollama/models/
```

---

## Open Items / Decisions Pending

1. **Qwen Ollama model research (STAGE 0–1 PRIORITY):** Which available Qwen Ollama model can execute code + orchestrate ffmpeg AND perform visual classification for hedgehog species identification? Discover via `ollama list`, check READMEs/capabilities for video stitching or CLI script execution and visual analysis capabilities. Determine if pre-built `qwen-code` model suffices or we need to build the agent ourselves using a base code model. **This must be resolved before any Stage 2 implementation coding begins.**
2. **Ring API bridge discovery:** Resolved — [python-ring-doorbell](https://python-ring-doorbell.readthedocs.io/stable/) (`ring_doorbell` package) chosen as third-party bridge (ADR-001). Auth: username + password with optional 2FA; tokens cached to `.token/cache`. Remove this line from Open Items pending list.
3. **OpenClaw Docker + WhatsApp QR scan setup:** Still pending. Hard blocker for both Stage 3 real wiring and Stage 4's inbound feedback channel. Install OpenClaw container via Docker Desktop, complete QR flow to link WhatsApp.
4. **Ollama model cache path:** Need to confirm the exact filesystem location for `~/.ollama/models/` on this machine (may vary by platform). Add to `.gitignore`.
5. `.gitignore` population: Missing entries beyond basics — add all items listed in Target Directory section above. This is a Stage 0 deliverable.

---

## Error Handling Summary Table

| Failure Type | Action |
|---|---|
| Ring API unreachable | Retry queue, log to `logs/pipeline.log`, optionally fire local alert; skip reel + delivery if retries exhausted |
| Ollama model missing or crashes | Skip reel generation entirely; log error; do NOT proceed with empty captions or no-op video output |
| WhatsApp bridge failure | Store compiled video (.mp4) locally as `.tmp` for manual resend; log warning; retry next pipeline_trigger_time cycle |
| No motion events at pipeline_trigger_time | Empty feed → Stage 2 produces "No camera activity since our last update" text fallback (no video compile) |
| No hedgehogs detected after classification | Produce "No hedgehogs spotted today" fallback message; no video compiled |
| Feedback channel not yet live | Use stdin-only simulation in `response_handler.py`; wire OpenClaw webhook when Docker/QR is fully set up |
| Pydantic schema mismatch at any boundary | Structured log entry + graceful skip/retry for that stage's data; prevent downstream corruption |

---

## Pipeline Idempotency & Retry Strategy

- `run_pipeline.py --retry` flag: restart the pipeline from any failed stage without re-executing earlier stages (e.g., if Stage 3 crashes, retry only Stage 3 onwards).
- Ring API calls are read-only and safe to re-query.
- `examples_store.py` `status` field (`pending/accepted/rejected`) tracks feed state across daily runs — prevents re-deleting or double-storing clips.
- All failures produce structured log entries in `logs/pipeline.log`.

---

## References

- [ADR-001](../docs/adr/adr-001-qwen-model-selection.md) — Qwen Ollama model selection (`qwen3-v1:30b-a3b`).
- [ADR-002](../docs/adr/adr-002-python-frame-fetch-strategy.md) — Python-deterministic frame fetching; model consumes pre-processed frames for classification + caption.

