# ADR-002: Python-Deterministic Frame Fetching, Model-Consumed Frames for Classification and Caption

**Status:** Accepted  
**Date:** 2026-10-18  
**Context:** Stage 2 of the hedgehogCafeCambs pipeline selects `qwen3-v1:30b-a3b` as the Ollama model. The remaining question is *how* that model receives visual data — should it call Ring APIs directly and extract frames, or should a Python layer handle frame prefetching and pass processed frames to the model for analysis?

---

## Decision

**Python fetches clip URLs, extracts frames, and validates them deterministically. The Qwen model receives pre-processed frames (file paths or byte arrays) and performs classification + caption generation.**

### Architecture: Two-Layer Pipeline in Stage 2

```
Ring API ──fetch──▶ Python layer: download clips, extract frames, validate shapes via Pydantic
                                    │
                                    ▼
                          Qwen model receives pre-processed frame batches
                                    │
                              ├── Species classification (hedgehog detected?)
                              ├── Dead-frame detection (remove static frames)
                              └── Caption generation (Attenborough-style narration)
                                    │
                                    ▼
                          Compiled reel metadata passed downstream via Pydantic CompiledReel model
```

**Why this separation of concerns:**

| Concern | Layer | Why Here? |
|---|---|---|
| **Clip URL fetching** | Python + Ring API / third-party bridge | Deterministic, retryable, rate-limit-aware. Pydantic validates each clip dict against `ring_api_schema.py` before downstream consumption. Model does not need credentials or HTTP client knowledge. |
| **Frame extraction from video** | FFmpeg (invoked by Python) | Frame sampling intervals, keyframe selection, and decoding — deterministic operations that must produce consistent output regardless of model state. Not a language-model concern. |
| **Species identification / dead-frame trimming** | Qwen model (visual analysis) | Requires visual understanding. Model receives frames directly — not raw URLs — because visual quality matters more than source fidelity. Frames are standard image formats (JPG/PNG). |
| **Caption generation** | Qwen model (text generation) | Prompt-driven output. Needs no data-fetching capability; requires only the processed clip metadata + species classification results. |

**Why NOT let the model call Ring APIs directly:**

1. **Credential exposure**: Model code execution runs in unpredictable contexts — credentials live closer to user-controlled code paths, creating risk vectors.
2. **Non-deterministic output**: Ollama models are stochastic — repeated frames-of-the-same-call might vary or error silently. Python retries and fails loudly with stack traces + structured logs; model failures may only say "no hedgehog found" when the API actually failed.
3. **Rate limiting / authentication**: Ring third-party bridge has unknown rate limits and auth quirks. Python layer can queue retries, back off gracefully, handle 401/429 errors. Model calling HTTP directly has no such logic — it gets an error and either stops or guesses.
4. **Frame quality control**: Pre-processing ensures frames are consistent (resolution, format, timestamps). If the model fetches URLs itself, frame extraction might produce different results on every invocation due to network timing or partial downloads.
5. **Failure isolation**: Ring API failure → logs + retry, skip reel entirely. Model classification failure → model error logged, but at least the video files are safe for retry next cycle.

**Test implications:**

- Stage 2 tests mock the *output* of the Python frame-fetch layer (pre-processed frames or file paths) and pass them to a mocked Qwen model call
- Separate test: `test_python_frame_fetch_validates_ring_responses_against_schema` validates the Ring API fetching layer independently from model calls
- End-to-end test (`e2e_full_stage_2_test`) chains real Python frame fetch + mock model, ensuring the handoff between layers is Pydantic-validated

---

## Consequences

### Positive:
- **Deterministic data pipeline** at every step: Ring API → Python validation → FFmpeg extraction → model classification → caption generation. Each layer has a single responsibility and clean failure semantics.
- **Easier testing**: Frame-fetching logic (FFmpeg, network calls) is testable independently of model behaviour; model calls are testable with stubbed frame inputs regardless of Ring API state.
- **Retry safety**: If the model throws an error during classification, frames already downloaded are safe for retry — no re-downloading from Ring API.
- **Credential isolation**: OAuth tokens, third-party bridge URLs, and OpenClaw config live in `config.py` (Pydantic validated at import time) — never exposed to model-execution contexts.

### Negative:
- **Added code complexity**: Python frame-fetching logic means writing FFmpeg orchestration, error handling, and retry logic that a simpler design could have left to the model.
- **Memory / disk throughput for frames**: Pre-downloading all frames before model classification means temporary storage for video chunks on disk/RAM. Must manage cleanup after processing to avoid filling local SSD.
- **Slightly longer startup latency**: Pipeline pauses at "Ring clips retrieved" while Python downloads + extracts frames before the model is invoked. In production (~10–30 sec depending on clip count), this is acceptable; in rapid iteration/testing, each stage's mock is faster than real frame processing.

### Risks:
- **FFmpeg availability**: Must ensure `ffmpeg` binary is installed locally (via `brew install ffmpeg`). Pipeline cannot run without it for Stage 2 frame extraction.
- **Frame memory management for large clip counts**: Hedgehog cameras on busy days may produce hundreds of motion events across 24h. Memory-mapping hundreds of video files simultaneously could crash the process before model classification starts. Mitigation: stream frames in batches (e.g., 50 clips at a time), write to temp dir, delete after processing.
- **Model input size limits**: If per-frame data exceeds the Qwen model's context window, large frame batches must be batched or subsampled, adding complexity to the handoff validation layer.

---

## Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|---|---|---|---|
| Model calls Ring APIs directly (single-layer pipeline) | Fewer code paths; less orchestration overhead | Non-deterministic frame fetch, credential exposure, broken retry semantics | Too fragile for a production system delivering daily highlight reels. A failed classification due to missed CLI frames would be indistinguishable from "no hedgehog detected." |
| Cloud-based vision API + local FFmpeg runner | Reliable species id; no VRAM constraints on-device | External dependency, costs per call, requires persistent network connectivity | Breaks the "fully-local-first" principle. Adds an external dependency that can fail silently or charge unexpectedly. Python-layer fetching is simpler to audit than a third-party cloud AI service. |

---

## References

- **docs/adr/adr-001-qwen-model-selection.md** — Qwen Ollama model selection rationale.
- **plans/Plan.v1.md** — Stage 2: AI Highlight Reel. Model Selection Specification section (Python layer handles frame fetch, Qwen model receives frames for classification + caption).
- **Memory:** `ollama-qwen-model-spec.md` — Full hedgehog classification + narration caption requirements (model receives pre-processed frames, not raw URLs).
