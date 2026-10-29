"""
config.py

All pipeline values loaded from .env via dotenv + validated at import time
with Pydantic BaseModel(). Fails fast with clear errors if required keys
are missing or malformed.

"""

from datetime import time as _time

from dotenv import dotenv_values
from pydantic import BaseModel, field_validator


class EnvConfig(BaseModel):
    """All .env keys for the hedgehogCafeCambs pipeline."""

    model_config = {"extra": "forbid"}  # reject unknown .env keys at load time

    # ------------------------------------------------------------------
    # Core pipeline metadata (used by schedule + dusk/dawn calc)
    # ------------------------------------------------------------------
    timezone_name: str                     # IANA timezone name, e.g. Europe/London
    latitude: float                        # camera latitude
    longitude: float                       # camera longitude
    dusk_offset_minutes: int               # offset after sunset for window start
    dawn_offset_minutes: int               # offset before sunrise for window end
    pipeline_trigger_time: _time           # scheduled trigger time, e.g. 07:00

    # ------------------------------------------------------------------
    # Ring API
    # ------------------------------------------------------------------
    ring_username: str                       # Ring account username (email)
    ring_password: str                       # Ring account password
    ring_camera_filter: str                  # e.g. "Hedgehog Cam" — prefix on _all_devices
    ring_token_cache_file: str               # e.g. "ring.token.cache"

    # ------------------------------------------------------------------
    # Stage 2 — Ollama / Qwen model (placeholder)
    # ------------------------------------------------------------------
    ollama_base_url: str                   # local Ollama server address
    ollama_model_name: str                 # e.g. qwen3-v1:30b-a3b

    # ------------------------------------------------------------------
    # Stage 3 — OpenClaw / WhatsApp (placeholder)
    # ------------------------------------------------------------------
    openclaw_webhook_url: str              # HTTP endpoint for OpenClaw send API
    recipient_phone_number: str            # E.164 format, e.g. +447...

    # ------------------------------------------------------------------
    # Stage 4 — Example store (placeholder)
    # ------------------------------------------------------------------
    sqlite_path: str                       # local SQLite path for example data

    # -- Validators that consume string fields ------------------------------
    @field_validator("timezone_name")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "timezone_name must be a valid IANA name (e.g. Europe/London)."
            )
        return v

    # -- Validators — fail early with actionable messages -------------------

    @field_validator("latitude", "longitude")
    @classmethod
    def _validate_coords(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError(f"Latitude/longitude must be between -90 and 90 — got {v}.")
        return v

    @field_validator(
        "dusk_offset_minutes",
        "dawn_offset_minutes",
    )
    @classmethod
    def _validate_offsets(cls, v: int) -> int:
        if not -60 <= v <= 120:
            raise ValueError("Offset must be between -60 and +120 minutes.")
        return v

    @field_validator("pipeline_trigger_time")
    @classmethod
    def _validate_trigger_time(cls, v) -> _time:
        if not v or not str(v).strip():
            raise ValueError(
                "pipeline_trigger_time must be a valid time string (e.g. '07:00')."
            )
        return v

    @field_validator("ring_token_cache_file")
    @classmethod
    def _validate_token_cache_path(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "ring_token_cache_file must not be empty — provide a .token/cache path."
            )
        return v


# --------------------------------------------------------------------------
# Load-time validation — read .env and validate on import
# --------------------------------------------------------------------------

_env_values = dotenv_values(".env")  # all values come back as str | None

# Fail immediately if .env is absent (dotenv_values returns empty dict)
if not _env_values:
    raise RuntimeError(
        ".env file not found. Copy .env.example to .env and fill in real values."
    )

# Build _cleaned dict: float-parse lat/lon, leave everything else as-is
_cleaned = {
    k: float(v) if k in ("latitude", "longitude") else v
    for k, v in _env_values.items()
}

# Build config instance — catches field_validator errors, type mismatches, etc.
try:
    config = EnvConfig(**_cleaned)
except Exception as _exc:
    raise RuntimeError(
        f"Config failed to load from .env — ensure it mirrors .env.example.\n{_exc}"
    ) from _exc

# Every field on EnvConfig must be present and non-blank in .env.
# Dotenv returns "" or None for missing/empty keys; we fail loudly.
_optional_fields: set[str] = {"ring_otp"}
_required_fields = [k for k in EnvConfig.model_fields.keys() if k not in _optional_fields]
for field_name in _required_fields:
    value = getattr(config, field_name)
    display_value = str(value).strip()
    if not display_value:
        raise RuntimeError(
            f"Required .env key is empty/missing: '{field_name}'. "
        )
