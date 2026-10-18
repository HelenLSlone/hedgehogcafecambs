# ADR-001: Qwen Ollama Model Selection for Hedgehog Reel Generation

**Status:** Proposed — pending research validation  
**Date:** 2026-10-18  
**Context:** Stage 2 of the hedgehogCafeCambs pipeline requires a single model capable of four distinct capabilities. No pre-packaged Ollama model is yet confirmed to meet all requirements.

---

## Context

Stage 2 generates an AI highlight reel from Ring camera clips. The selected Ollama model must simultaneously perform:
1. Visual classification (hedgehog species identification in video frames)
2. Dead-frame trimming (removing static/blank frames)
3. Video compilation via `ffmpeg concat` (producing a ≤3 min reel)
4. Caption generation in the style of a British wildlife documentary narrator (dry wit, understated observation, gentle awe — e.g., Attenborough-style)

The model must run locally on an M5 Pro with 64 GB unified memory and be accessible via the `ollama` CLI or local HTTP API. A Qwen-based model is preferred as the primary candidate family.

---

## Decision

Adopt the **`qwen3-v1:30b-a3b`** Ollama model as the single Qwen-family model capable of fulfilling all four capabilities above. This model was selected because it is the only currently available candidate with sufficient capacity for simultaneous visual classification (hedgehog species ID) and code execution (ffmpeg orchestration + caption generation), running locally on an M5 Pro with 64 GB unified memory.

- **Primary path:** One Qwen model (`qwen3-v1:30b-a3b`) handles classification + ffmpeg orchestration + caption generation via code execution and prompt chaining.
- **Fallback path (if no single model works):** Use one model for visual analysis/species identification (e.g., `qwen2.5-vl`) and a second model for code orchestration/caption writing (e.g., `qwen2.5-coder`), chained together via an intermediate data structure validated by Pydantic between stages.

### Selection criteria (all must pass during research phase):

1. **Species identification / visual classification** — Model analyses each clip and correctly identifies whether a hedgehog is present in the frame; non-hedgehog clips excluded.
2. **Dead footage trimming** — Model detects and cuts out dead frames (static/blank, no motion) from qualifying clips before inclusion in the reel.
3. **Reel compilation & hard duration limit** — Model orchestrates `ffmpeg concat` to stitch remaining clips into a single .mp4/.mov; final runtime never exceeds 3 minutes (180 seconds). If eligible clips would exceed this cap, curation/trimming logic is applied to meet it.
4. **British wildlife documentary narrator caption style** — Model generates a narrating caption that reads naturally in the style of David Attenborough or equivalent: dry wit, understated observation, gentle awe at nature. Captions must not sound technical or robotic.

### Research verification procedure:

1. Run `ollama list` to enumerate all available Qwen-family models.
2. Review each model's README/capabilities for visual analysis and code execution support.
3. Pull candidate model(s) via `ollama pull` and test against sample footage.
4. Validate results against the four criteria above — **all four must pass** before adoption.
5. If single-model path fails, evaluate the two-model fallback pipeline and assess added complexity vs. delivery capability.

---

## Consequences

### Positive:
- Clear, testable selection criteria prevent ad-hoc model choices that may fail in production.
- A two-model fallback preserves deliverability even if no single Qwen family model meets all four requirements simultaneously.
- Pydantic validation between stages prevents data shape mismatches when chaining models.

### Negative:
- If a two-model path is chosen, added complexity (additional Ollama API calls, intermediate data structures, more failure modes) increases pipeline fragility and runtime latency.
- Heavy visual models consume significant unified memory; must verify available VRAM before committing to a large model.
- Video processing via code execution is uncommon for Qwen-family models — success is not guaranteed without custom script authoring.

### Risks:
- No pre-built "video analysis + ffmpeg" model exists as of 2026-10-18; we may need to author the classification/trimming scripts ourselves and prompt the code model to execute them.
- Ollama models are non-deterministic — repeated runs may produce different captions or classifications, complicating feedback matching in Stage 4.

---

## Alternatives Considered

| Alternative | Pros | Cons |
|---|---|---|
| Non-Qwen Ollama models (e.g., LLaVA for vision, LLama3 for caption) | May offer better out-of-box video analysis | Less cohesive code execution than Qwen-coder; mixed model pipeline increases complexity |
| Cloud-based vision API + local ffmpeg runner | Reliable species identification; no VRAM limits on device | Adds external dependency; breaks "fully local" design principle; incurs API costs |
| Skip species classification; compile all clips with metadata filtering only | Simplest possible Stage 2; no visual model needed | Delivers irrelevant footage (empty scenes, other animals); defeats purpose of highlight reel |

---

## References

- **plan/Plan.v1.md** — Stage 2: AI Highlight Reel. Model Selection Specification section.
- **Memory:** `ollama-qwen-model-spec.md` — Full hedgehog classification + narration caption requirements.
