#!/usr/bin/env python3
"""ring_client.py -- Collect dusk-to-dawn motion events
from all cameras as a validated data structure."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone as _tz
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, field_validator
from ring_doorbell import Auth, Ring, RingGeneric
import config

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_TS_KEYS = ("created_at", "timestamp", "when")


# ===================================================================
# Pydantic schemas (with field-level validation)
# ===================================================================


class RingRecordingEvent(BaseModel):
    """A single motion-event record from a Ring camera."""

    camera_id: int
    camera_name: str
    created_at_utc: str
    download_url: str

    @field_validator("camera_id")
    @classmethod
    def _check_camera_id(cls, v):  # type: ignore[no-untyped-def]
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("camera_id must be an integer")
        return v


class DuskToDawnResult(BaseModel):
    """The complete output shape from ring_client.main()."""

    window_start: str
    window_end: str
    total_raw_events_scanned: int
    events_in_window: int
    cameras_used: list[str]
    events: list[RingRecordingEvent]


DuskToDawnResult.model_rebuild()


# ===================================================================
# Internal helpers
# ===================================================================

def _serialise(obj: Any) -> Any:
    """Convert datetimes → ISO strings recursively for debug dumps."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialise(i) for i in obj]
    return obj


def _find_ts(event: dict[str, Any]) -> datetime | None:
    """Pull 'created_at' out of any structure Ring hands us."""
    # Fast path: top-level dict with known key.
    if isinstance(event, dict):
        for key in _TS_KEYS:
            val = event.get(key)
            if isinstance(val, datetime):
                return val

    # Slow path: deep search into nested structures.
    ts_result: list[datetime | None] = [None]

    def _search(obj: Any) -> None:
        if ts_result[0] is not None:
            return
        if isinstance(obj, dict):
            for key in _TS_KEYS:
                val = obj.get(key)
                if isinstance(val, datetime):
                    ts_result[0] = val
                    return
            # Recurse into values to handle nested dicts.
            for val in obj.values():
                _search(val)
                if ts_result[0]:
                    break
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _search(item)
                if ts_result[0]:
                    break

    _search(event)
    return ts_result[0]



def _parse_history(history:  list[dict[str, Any]]) -> list[Any]:
    """Extract an iterable of events from various Ring history shapes.

    Handles lists, iterators, objects with a .motion attribute, and edge cases.
    This flattens the branching inside ``_fetch_raw_events`` to its own function.
    """
    if isinstance(history, list):
        return history

    # Try converting an iterator directly.
    if hasattr(history, '__iter__') and not isinstance(history, str):
        try:
            return list(history)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    # Maybe it's a container with a .motion attribute.
    attr = getattr(history, 'motion', None)
    if isinstance(attr, list):
        return attr
    if hasattr(attr, '__iter__'):
        return list(attr)
    return []


def _parse_event(ev: Any) -> dict[str, Any]:
    """Convert a raw event into a dict (Ring may return dicts or objects)."""
    if isinstance(ev, dict):
        return ev
    if hasattr(ev, "__dict__"):
        try:
            return vars(ev)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    return {}


async def _fetch_raw_events(device: RingGeneric) -> list[dict[str, Any]]:
    """Fetch motion history from one camera; return a list of event dicts."""
    try:
        history = await device.async_history(kind='motion', limit=100)
        source = _parse_history(history)
        return [_parse_event(ev) for ev in (source or [])]

    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"  [WARN] fetch error on {device}: {exc}")
        return []


async def _process_camera(
    device: RingGeneric,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    """Fetch and filter events for one camera; returns valid events only."""
    try:
        cam_id = device.id
        cam_name = device.name
        print(f"[+] Fetching events for '{cam_name}' (id={cam_id}) ...")

        raw_events = await _fetch_raw_events(device)
        valid_events: list[dict[str, Any]] = []

        for ev in raw_events:
            ts = _find_ts(ev)
            if ts is None or not window_start <= ts < window_end:
                continue

            eid = ev.get('id') if isinstance(ev, dict) else None
            download_url: str = ''
            if eid:
                try:
                    url_resp = await device.async_recording_url(eid)
                    download_url = str(url_resp) if url_resp else ''
                except Exception as e:  # pylint: disable=broad-exception-caught
                    print(f"      [!] URL fetch failed for {eid}: {e}")

            valid_events.append({
                "camera_id": int(cam_id),
                "camera_name": cam_name,
                "created_at_utc": ts.isoformat(),
                "download_url": download_url,
            })

        return valid_events

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"  [WARN] _process_camera({cam_name}) failed: {e}")
        return []


async def _collect_all_events(
    allowed_devices: Sequence[RingGeneric],
    window_start: datetime,
    window_end: datetime,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch & filter dusk-to-dawn events from all matched cameras."""
    all_events: list[dict[str, Any]] = []
    total_raw = 0

    for device in allowed_devices:

        events = await _process_camera(
            device,
            window_start, window_end,
        )
        total_raw += len(events)
        all_events.extend(events)

    all_events.sort(key=lambda e: e["created_at_utc"])
    return all_events, total_raw

async def _authenticate_with_ring() -> tuple[Auth, Ring]:
        # -- Load cached token ---------------------------------------------------
    cache_file = "ring.token.cache"
    cache_path = _PROJECT_ROOT / cache_file
    if not cache_path.exists():
        print(f"[!] No cached token found at {cache_file}")
        print("    Run `python scripts/auth_ring.py` first to obtain a valid token.")
        raise FileNotFoundError(cache_file)

    try:
        token: dict[str, Any] = json.loads(cache_path.read_text())
    except Exception as exc:
        print(f"[!] Failed to parse cached token: {exc}")
        raise RuntimeError("Invalid cache") from exc

    # -- Connect to Ring API -------------------------------------------------
    try:
        auth_obj =  Auth("hedeghogCambs-list/1.0", token=token)
        ring_obj = Ring(auth_obj)
        ring = await ring_obj.async_update_devices()
        return auth_obj, ring

    except ImportError:
        print("[!] python-ring-doorbell not installed.")
        sys.exit(1)
    except Exception as exc:
        print(f"[!] Ring API error: {exc}")
        print("    Run `python scripts/auth_ring.py` to refresh your token.")
        raise

def _get_allowed_devices(all_devices: Sequence[RingGeneric]) -> dict[int, str]:
    config_obj = config.config
    filter_prefix = config_obj.ring_camera_filter
    # Filter cameras by configured prefix.
    allowed_devices: dict[int, str] = {}
    for k, v in all_devices.items():
        if isinstance(v, RingGeneric) and str(v).startswith(filter_prefix):
            allowed_devices[int(k)] = str(v)
    if not allowed_devices:
        print(f"[!] No cameras match prefix '{filter_prefix}'. Nothing to fetch.")
        raise ValueError("No matching cameras")
    return allowed_devices

# -- Main -------------------------------------------------------------------

async def main(
    window_start: datetime,
    window_end: datetime,
) -> DuskToDawnResult:
    """Fetch dusk-to-dawn motion events and return a validated result object.

    The dawn→dusk window is pre-computed by the orchestrator
    (``run_pipeline.py`` via solar module). This function owns only
    data-transform logic.

    Returns
    -------
    DuskToDawnResult — all shape validation happens at the boundary,
    ignoring any _raw fields from the Ring API.
    """
    # -- Load cached token ---------------------------------------------------
    auth_obj, ring = await _authenticate_with_ring()

    # -- Body (all logic inside try/finally so we tear down the auth session) -
    try:
        dev_obj = ring.devices()
        all_devices = dev_obj.all_devices
        allowed_devices = _get_allowed_devices(all_devices)




        # -- Fetch & filter events across all cameras --------------------
        all_events, total_raw = await _collect_all_events(
            allowed_devices, window_start, window_end,
        )

    finally:
        if auth_obj is not None and hasattr(auth_obj, 'async_close'):
            await auth_obj.async_close()

    # -- Build and validate the result shape ---------------------------------
    dusk_to_dawn_result = DuskToDawnResult(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        total_raw_events_scanned=total_raw,
        events_in_window=len(all_events),
        cameras_used=list(allowed_devices.values()),
        events=all_events,
    )

    print(f"[+] Validated {dusk_to_dawn_result.events_in_window} dusk-to-dawn events")
    print(f"    Scanned {total_raw} total raw events across {len(allowed_devices)} cameras")

    return dusk_to_dawn_result


if __name__ == "__main__":
    # Safe defaults: today midnight UTC → tomorrow midnight UTC.
    # Real usage goes through run_pipeline which computes via solar.
    _now = datetime.now(_tz.utc).date()
    _start = datetime.combine(_now, datetime.min.time(), tzinfo=_tz.utc)
    _tomorrow = _now.replace(day=_now.day + 1)
    _end = datetime.combine(_tomorrow, datetime.min.time(), tzinfo=_tz.utc)

    try:
        result = asyncio.run(main(_start, _end))
        print(json.dumps(result.model_dump(), indent=2))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"[ERROR] {exc}")
        sys.exit(1)
