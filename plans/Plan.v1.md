# hedgehogCafeCambs — V1 Implementation Plan

## Overview

7am-triggered pipeline: **Ring camera → AI highlight reel → WhatsApp delivery → user feedback**. Built iteratively, one stage at a time, mock-first. Each stage is validated as a mock before wiring to the real API. The process is given in [this file](../plans/Plan.v1.md).

---

## Stage 0 — Scaffold + Schedule Trigger (No External Dependencies)

**What**: A runnable entry point that prints each stage's output. Scheduled at 7am via Python `sched` or Mac `launchd`/cron.

| Step | Build | Validate |
|---|---|---|
| `schedule.py` — wrapper using `sched.Timer` or system cron | Runs at 7am, prints timestamp | Check it fires |
| `run_pipeline.py` — calls each stage function sequentially | Output: "Ring clips retrieved", "Reel generated", "Sent to WhatsApp", "Awaiting feedback..." | Read the output stream end-to-end |

**Files**: `schedule.py`, `run_pipeline.py`, `pipeline/__init__.py`, `data/`, `requirements.txt`

---

## Stage 1 — Ring API (Mock → Real, *you set up later*)
**Goal**: Fetch motion events and clip URLs from the Ring camera.

| Step | Build | Mock State | Swap When |
|---|---|---|---|
| `pipeline/ring_client.py` | GET clips endpoint; returns list of clip objects with URL, timestamp, duration | **Mock**: hardcoded test data (e.g., 3 sample clip dicts) | You provide credentials + confirm access |
| Wire real API call in ring_client.py | Replace mock with real HTTP call to Ring API | → Real | N/A |

**Validation**: Clips retrieved have all fields needed by Stage 2. Print each before moving on.

---

## Stage 2 — AI Highlight Reel (Mock → Real, *Ollama locally*)
**Goal**: Generate a highlight reel summary and caption from clip metadata.

| Step | Build | Mock State | Swap When |
|---|---|---|---|
| `pipeline/reel_generator.py` | Takes list of clips, generates text: "best moments" list + narration caption | **Mock**: hardcoded sample like "Cafe buzzed today — baristas on the terrace, a cat spotted near the compost bin..." | You confirm Ollama model responds well |
| Wire real API call in reel_generator.py | Call local Ollama (ollama API) with clip metadata as prompt | → Real | N/A |

**Validation**: Caption reads like a coherent cafe update, not boilerplate. Print before WhatsApp step.

---

## Stage 3 — WhatsApp via OpenClaw (Mock → Real, *set up later*)
**Goal**: Deliver the highlight reel summary to your phone via WhatsApp.

| Step | Build | Mock State | Swap When |
|---|---|---|---|
| `pipeline/whatsapp_sender.py` | Sends text message to recipient number | **Mock**: prints "Would send to [number]: [caption]" | You configure OpenClaw + WhatsApp QR scan |
| Install OpenClaw Docker container and connect WhatsApp | Manual setup step (QR code scan) | Not yet — skip this | After mock is verified working |
| Wire real API call in whatsapp_sender.py | Call OpenClaw HTTP API to actually send the message | → Real | N/A |

**Validation**: Caption passes through intact (no truncation, emojis OK). Test with a real message later.

---

## Stage 4 — User Feedback + Example Storage
**Goal**: Handle user response; store accepted clips as examples, delete rejected ones.

| Step | Build | Notes |
|---|---|---|
| `pipeline/response_handler.py` | Simulate incoming feedback (stdin or HTTP endpoint). Route: "Accepted" → store to DB, "Rejected" → delete downloads | Mock first; no real webhook yet |
| `data/examples_store.py` — SQLite store for clips + reel metadata | Real implementation (SQLite only, no external deps) | Persist example_id, clip_url, timestamp, reel_caption |

**Validation**: Accept + reject both produce correct side effects. Query back an example after storing it.

---

## Stage 5 — End-to-End Wiring
**Goal**: All real stages chained together in one cron-triggered command. Add logging and error handling.

| Step | What |
|---|---|
| Hook `run_pipeline.py` → all real APIs in sequence | Single-shot pipeline execution |
| Add retry logic, structured logging to file | Pipeline survives API hiccups; logs in `logs/pipeline.log` |
| **Acceptance test**: Cron fires at 7am → Ring clips fetched → Ollama generates reel → OpenClaw delivers to WhatsApp → Reply "Accepted" → clip stored ✅ | Final validation of full cycle |

---

## Target Directory

```
hedgihogCafeCambs/
├── schedule.py              # 7am trigger
├── run_pipeline.py          # Entry point (chained pipeline)
├── pipeline/
│   ├── __init__.py
│   ├── ring_client.py       # Stage 1: Ring camera API
│   ├── reel_generator.py    # Stage 2: AI highlight reel
│   ├── whatsapp_sender.py   # Stage 3: OpenClaw WhatsApp bridge
│   └── response_handler.py  # Stage 4: Feedback routing
├── data/
│   ├── examples_store.py    # SQLite persistence for accepted examples
│   └── examples.db           # Created after first successful store
├── config.py               # API keys, phone numbers, credentials (TODO)
├── requirements.txt        # Python deps
└── logs/                   # Pipeline execution logs
```

## Open Items / Decisions Pending

1. **Ollama model**: Which local model for reel generation? (e.g., `qwen2.5-coder:32b`, `llama3`, etc.)
2. **Ring credentials**: Camera access token + API endpoint URL once you get them.
3. **WhatsApp recipient phone number**: E.164 format, e.g., `+447...`.
4. **Schedule mechanism**: Python `sched` inside a foreground process vs Mac `launchd` cron job (simpler).
