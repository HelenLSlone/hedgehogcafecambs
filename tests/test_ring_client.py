"""Tests for pipeline/ring_client.py's DuskToDawnResult Pydantic schema.

Validates the dusk-to-dawn motion event shape used by the Ring stage.
No external fixtures — all ValidationError refs loaded from pydantic.

Also tests internal helpers: _find_ts, _get_allowed_devices, _process_camera,
_collect_all_events via targeted mocks (no .env or live API required).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone as _tz
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError as VE

from ring_doorbell import RingGeneric

from pipeline.ring_client import (
    DuskToDawnResult,
    _find_ts,
    _get_allowed_devices,
    _process_camera,
    _collect_all_events,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Pydantic schema tests — 14 self-contained tests for DuskToDawnResult
# ===========================================================================


def _make_valid_event() -> dict:
    """Return a minimal valid event dict."""
    return {
        "camera_id": 635097130,
        "camera_name": "Hedgehog Cam 1 (cocoa_camera)",
        "created_at_utc": "2026-10-18T02:00:00+00:00",
        "download_url": "https://example.com/clip.mp4",
    }


def _build_result(extra_events: list | None = None) -> DuskToDawnResult:
    """Helper: build a valid DuskToDawnResult with optional extra events."""
    base_events = [
        {
            "camera_id": 635097130,
            "camera_name": "Hedgehog Cam 1",
            "created_at_utc": "2026-10-18T01:00:00+00:00",
            "download_url": "",
        },
    ]
    if extra_events:
        base_events.extend(extra_events)

    return DuskToDawnResult(
        window_start="2026-10-17T19:00:00+00:00",
        window_end="2026-10-18T07:00:00+00:00",
        total_raw_events_scanned=5,
        events_in_window=len(base_events),
        cameras_used=["Hedgehog Cam 1"],
        events=base_events,
    )


# ---------------------------------------------------------------
# Acceptance tests — valid shapes pass
# ---------------------------------------------------------------

def test_schema_accepts_valid_event():  # type: ignore[no-untyped-def]
    """DuskToDawnResult accepts a dict with all 4 required fields."""
    result = _build_result([_make_valid_event()])
    dump = result.model_dump()
    ev = dump["events"][1]
    assert ev["camera_id"] == 635097130 and isinstance(ev["camera_id"], int)
    assert ev["camera_name"] == "Hedgehog Cam 1 (cocoa_camera)"


def test_schema_accepts_empty_download_url():  # type: ignore[no-untyped-def]
    """Empty string for download_url is valid (no recording ID found)."""
    result = _build_result([{
        "camera_id": 123456789,
        "camera_name": "Hedgehog Cam X",
        "created_at_utc": "2026-10-18T02:00:00+00:00",
        "download_url": "",
    }])

    dump = result.model_dump()
    assert isinstance(dump["events"][-1]["download_url"], str)


def test_schema_accepts_mixed_valid_events():  # type: ignore[no-untyped-def]
    """Schema accepts events with varying download_url content (empty vs full URL)."""
    empty_ev = {**_make_valid_event(), "download_url": ""}
    full_ev = {**_make_valid_event(), "camera_id": 647902355,
                "download_url": "https://cdn.example.com/clip.mp4?auth=secret"}

    result = _build_result([empty_ev, full_ev])
    dump = result.model_dump()
    assert dump["events"][-2]["download_url"] == ""
    assert dump["events"][-1]["download_url"] != ""


def test_data_empty_events_list_is_valid():  # type: ignore[no-untyped-def]
    """Zero events in window produces valid model with empty list."""
    result = DuskToDawnResult(
        window_start="2026-10-17T19:00:00+00:00",
        window_end="2026-10-18T07:00:00+00:00",
        total_raw_events_scanned=3,
        events_in_window=0,
        cameras_used=["Hedgehog Cam X"],
        events=[],
    )

    assert result.events_in_window == 0
    assert len(result.model_dump()["events"]) == 0


# ---------------------------------------------------------------
# Rejection tests — structural field checks on each event dict
# ---------------------------------------------------------------

def _invalid_missing_camera_id() -> list[dict]:
    return [{"camera_name": "X", "created_at_utc": "y", "download_url": "z"}]


def _invalid_missing_camera_name() -> list[dict]:
    return [{"camera_id": 123, "created_at_utc": "y", "download_url": "z"}]


def _make_wrong_type_event(field: str, wrong_value) -> dict:
    ev = _make_valid_event()
    ev[field] = wrong_value
    return ev


def test_schema_rejects_missing_camera_id():  # type: ignore[no-untyped-def]
    """Event missing camera_id field raises ValidationError."""
    with pytest.raises(VE):
        DuskToDawnResult(
            window_start="2026-10-17T19:00:00+00:00",
            window_end="2026-10-18T07:00:00+00:00",
            total_raw_events_scanned=0,
            events_in_window=1,
            cameras_used=[],
            events=_invalid_missing_camera_id(),
        )


def test_schema_rejects_wrong_type_camera_id():  # type: ignore[no-untyped-def]
    """camera_id as string (not int) raises ValidationError."""
    with pytest.raises(VE):
        DuskToDawnResult(
            window_start="2026-10-17T19:00:00+00:00",
            window_end="2026-10-18T07:00:00+00:00",
            total_raw_events_scanned=0,
            events_in_window=1,
            cameras_used=[],
            events=[_make_wrong_type_event("camera_id", "wrong_type")],
        )


def test_schema_rejects_missing_camera_name():  # type: ignore[no-untyped-def]
    """Event missing camera_name field raises ValidationError."""
    with pytest.raises(VE):
        DuskToDawnResult(
            window_start="2026-10-17T19:00:00+00:00",
            window_end="2026-10-18T07:00:00+00:00",
            total_raw_events_scanned=0,
            events_in_window=1,
            cameras_used=[],
            events=_invalid_missing_camera_name(),
        )


def test_schema_rejects_wrong_type_created_at():  # type: ignore[no-untyped-def]
    """created_at_utc as int (not str) raises ValidationError."""
    with pytest.raises(VE):
        DuskToDawnResult(
            window_start="2026-10-17T19:00:00+00:00",
            window_end="2026-10-18T07:00:00+00:00",
            total_raw_events_scanned=0,
            events_in_window=1,
            cameras_used=[],
            events=[_make_wrong_type_event("created_at_utc", 12345)],
        )


def test_schema_rejects_wrong_type_download_url():  # type: ignore[no-untyped-def]
    """download_url missing or wrong type raises ValidationError."""
    with pytest.raises(VE):
        DuskToDawnResult(
            window_start="2026-10-17T19:00:00+00:00",
            window_end="2026-10-18T07:00:00+00:00",
            total_raw_events_scanned=0,
            events_in_window=1,
            cameras_used=[],
            events=[_make_wrong_type_event("download_url", 12345)],
        )


def test_schema_rejects_invalid_events_in_window():  # type: ignore[no-untyped-def]
    """Events with wrong-structured fields are rejected by Pydantic."""
    bad_event = {
        "camera_id": "not_int",
        "camera_name": "X",
        "created_at_utc": None,
        "download_url": ["unexpected"],
    }

    with pytest.raises(VE):
        DuskToDawnResult(
            window_start="2026-10-17T19:00:00+00:00",
            window_end="2026-10-18T07:00:00+00:00",
            total_raw_events_scanned=1,
            events_in_window=1,
            cameras_used=[],
            events=[bad_event],
        )


# ---------------------------------------------------------------
# Data shape tests — structural checks on model_dump output
# ---------------------------------------------------------------

def test_data_shape_all_required_fields_present():  # type: ignore[no-untyped-def]
    """Every event dict in the result has all 4 required fields with correct types."""
    result = _build_result([{
        "camera_id": 647902355,
        "camera_name": "HC 2",
        "created_at_utc": "2026-10-18T05:00:00+00:00",
        "download_url": "https://example.com/clip.mp4",
    }])

    dump = result.model_dump()
    assert result.events_in_window == 2

    for ev in dump["events"]:
        assert isinstance(ev["camera_id"], int)
        assert isinstance(ev["camera_name"], str)
        assert isinstance(ev["created_at_utc"], str)
        assert isinstance(ev["download_url"], str)


# ---------------------------------------------------------------
# Pydantic model verification
# ---------------------------------------------------------------

def test_schema_is_pydantic_model():  # type: ignore[no-untyped-def]
    """DuskToDawnResult is a Pydantic model with model_validate/model_dump."""
    assert hasattr(DuskToDawnResult, "model_validate")
    assert hasattr(DuskToDawnResult, "model_dump")


def test_schema_model_dump_produces_correct_structure():  # type: ignore[no-untyped-def]
    """model_dump() produces dict with events list and correct counts."""
    result = _build_result([{
        "camera_id": 647902355,
        "camera_name": "HC 2",
        "created_at_utc": "2026-10-18T05:00:00+00:00",
        "download_url": "",
    }])

    dump = result.model_dump()
    assert isinstance(dump["events"], list)
    assert len(dump["events"]) == 2
    assert dump["total_raw_events_scanned"] == 5


# ---------------------------------------------------------------
# Edge case — invalid events in window should still be rejected
# ---------------------------------------------------------------

def test_rejects_multiple_invalid_fields_in_one_event():  # type: ignore[no-untyped-def]
    """Multiple wrong-typed fields on a single event raises once."""
    multi_bad = [_make_wrong_type_event("camera_id", "not_int"),
                  _make_wrong_type_event("created_at_utc", None)]

    with pytest.raises(VE):
        DuskToDawnResult(
            window_start="2026-10-17T19:00:00+00:00",
            window_end="2026-10-18T07:00:00+00:00",
            total_raw_events_scanned=2,
            events_in_window=2,
            cameras_used=["Hedgehog Cam X"],
            events=multi_bad,
        )


# ===========================================================================
# NEW — Internal helper tests (self-contained with mocks)
# ===========================================================================

# ---------------------------------------------------------------------------
# _find_ts()
# ---------------------------------------------------------------------------

def test_find_ts_fast_path_top_level_dict():  # type: ignore[no-untyped-def]
    """Top-level dict with 'created_at' returns datetime instantly."""
    ts = datetime(2026, 10, 18, 2, 30, 0, tzinfo=_tz.utc)
    event = {"created_at": ts}
    assert _find_ts(event) == ts


def test_find_ts_fast_path_alt_keys():  # type: ignore[no-untyped-def]
    """Falls back to 'timestamp' or 'when' keys when 'created_at' absent."""
    ts = datetime(2026, 10, 18, 3, 0, 0, tzinfo=_tz.utc)

    assert _find_ts({"timestamp": ts}) == ts
    assert _find_ts({"when": ts}) == ts


def test_find_ts_slow_path_nested_list():  # type: ignore[no-untyped-def]
    """Deep-search recurses through nested list to find datetime."""
    ts = datetime(2026, 10, 18, 3, 0, 0, tzinfo=_tz.utc)
    nested = {"data": [{"id": 1}, {"created_at": ts}], "meta": "x"}
    assert _find_ts(nested) == ts


def test_find_ts_slow_path_deeply_nested():  # type: ignore[no-untyped-def]
    """Recurses through mixed dict/list structure at arbitrary depth."""
    ts = datetime(2026, 10, 18, 4, 0, 0, tzinfo=_tz.utc)
    deep = {
        "outer": {
            "middle": [
                {"ignored": True},
                {"deep_key": [{"created_at": ts}]},
            ],
        },
    }
    assert _find_ts(deep) == ts


def test_find_ts_returns_none_when_no_ts():  # type: ignore[no-untyped-def]
    """Returns None when event contains no datetime key from _TS_KEYS."""
    empty_event = {"id": 123, "label": "motion", "count": 42}
    assert _find_ts(empty_event) is None


def test_find_ts_no_ts_in_nested_structure():  # type: ignore[no-untyped-def]
    """Deep-search returns None when no matching key exists anywhere."""
    deep_with_wrong_key = {
        "outer": {
            "middle": [
                {"timestamp_id": 1},   # not a TS_KEY
                {"when_ev": "2026-10-18", "date": "x"},
            ],
        },
    }
    assert _find_ts(deep_with_wrong_key) is None


def test_find_ts_stops_after_first_found():  # type: ignore[no-untyped-def]
    """TS_KEYS iterate (created_at, timestamp, when) — 'late' found first in this dict."""
    ts_early = datetime(2026, 10, 18, 3, 0, 0, tzinfo=_tz.utc)
    ts_late = datetime(2026, 10, 18, 5, 0, 0, tzinfo=_tz.utc)
    multi_candidate = {
        "when": ts_early,      # key 'timestamp' is checked before 'when'
        "timestamp": ts_late,   # found first by TS_KEYS iteration
    }
    assert _find_ts(multi_candidate) == ts_late


def test_find_ts_non_dict_input():  # type: ignore[no-untyped-def]
    """Non-dict input (e.g. string or int) returns None via slow path."""
    assert _find_ts("just a string") is None
    assert _find_ts(12345) is None


# ---------------------------------------------------------------------------
# Helpers: fake device / RingGeneric mocks
# ---------------------------------------------------------------------------

def _make_fake_device(
    dev_id: int,
    name: str,
    events: list[dict],
    *,
    recording_urls: dict[int, str] | None = None,
) -> MagicMock:
    """Build a fake RingGeneric mock with async_history() + recording_url support."""

    dev = MagicMock()
    dev.id = dev_id
    dev.name = name

    async def fake_history(kind: str, limit: int) -> list[dict]: # pylint: disable=unused-argument
        if kind == "motion":
            return events
        return []

    dev.async_history = AsyncMock(side_effect=fake_history)

    rec_urls = recording_urls or {}

    async def fake_recording_url(event_id: int):
        return str(rec_urls.get(event_id, ""))

    dev.async_recording_url = AsyncMock(side_effect=fake_recording_url)

    return dev


# ---------------------------------------------------------------------------
# _get_allowed_devices() — use plain dicts + real config, no @patch needed
# ---------------------------------------------------------------------------

def test_get_allowed_devices_filters_by_prefix():  # type: ignore[no-untyped-def]
    """Only devices whose name starts with ring_camera_filter are returned."""

    def _make_dev(name: str, dev_id: int) -> MagicMock:
        """Return a MagicMock() spec=RingGeneric (isinstance passes)."""
        dev = MagicMock(spec=RingGeneric, name=name)  # spec=True → isinstance passes
        dev.id = dev_id
        dev.name = name
        dev.__str__ = lambda self: name               # so str(mock) == device_name
        return dev

    dev_a = _make_dev("Hedgehog Cam 1", 1)
    dev_b = _make_dev("Hedgehog Cam 2 (cocoa)", 2)
    dev_c = _make_dev("Ring Doorbell", 3)

    all_devs: dict[int, MagicMock] = {
        1: dev_a,
        2: dev_b,
        3: dev_c,
    }

    allowed = _get_allowed_devices(all_devs)

    assert len(allowed) == 2
    names = list(allowed.values())
    assert "Hedgehog Cam 1" in names
    assert "Hedgehog Cam 2 (cocoa)" in names


def test_get_allowed_devices_empty_result_raises():  # type: ignore[no-untyped-def]
    """When no cameras match prefix, raises ValueError."""

    with pytest.raises(ValueError, match="No matching cameras"):
        _get_allowed_devices({})


# ---------------------------------------------------------------------------
# _process_camera()  — async, needs event_loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_camera_includes_window_events():  # type: ignore[no-untyped-def]
    """Events within the window are filtered in and include all required fields."""
    window_start = datetime(2026, 10, 17, 19, 0, tzinfo=_tz.utc)
    window_end = datetime(2026, 10, 18, 7, 0, tzinfo=_tz.utc)

    in_window_ts = datetime(2026, 10, 18, 1, 0, 0, tzinfo=_tz.utc)
    out_window_ts = datetime(2026, 10, 18, 8, 0, 0, tzinfo=_tz.utc)

    fake_dev = _make_fake_device(
        dev_id=635097130,
        name="Hedgehog Cam 1",
        events=[
            {"id": 100, "created_at": in_window_ts},
            {"id": 200, "created_at": out_window_ts},
        ],
    )

    result = await _process_camera(fake_dev, window_start, window_end)

    assert len(result) == 1, "Only one event should be inside the dusk-to-dawn window"
    ev = result[0]
    assert ev["camera_id"] == 635097130 and isinstance(ev["camera_id"], int)
    assert ev["camera_name"] == "Hedgehog Cam 1"
    assert ev["created_at_utc"] != ""


@pytest.mark.asyncio
async def test_process_camera_empty_result_no_events():  # type: ignore[no-untyped-def]
    """Camera with no events returns empty list without error."""
    window_start = datetime(2026, 10, 17, 19, 0, tzinfo=_tz.utc)
    window_end = datetime(2026, 10, 18, 7, 0, tzinfo=_tz.utc)

    fake_dev = _make_fake_device(dev_id=999, name="Empty Cam", events=[])

    result = await _process_camera(fake_dev, window_start, window_end)
    assert result == []


@pytest.mark.asyncio
async def test_process_camera_filtering_by_window_boundary():  # type: ignore[no-untyped-def]
    """Events exactly at window_start included; events at window_end excluded (< not <=)."""
    window_start = datetime(2026, 10, 18, 2, 0, 0, tzinfo=_tz.utc)
    window_end = datetime(2026, 10, 18, 7, 0, 0, tzinfo=_tz.utc)

    fake_dev = _make_fake_device(
        dev_id=1,
        name="Boundary Cam",
        events=[
            # before: 1am — outside (before start)
            {"id": "before", "created_at": window_start.replace(hour=1)},
            # at_start: exactly 2am — should be included (window_start <= ts)
            {"id": "at_start", "created_at": window_start},
            # inside: 6:59am — clearly inside
            {"id": "end_event", "created_at": datetime(2026, 10, 18, 6, 59, tzinfo=_tz.utc)},
            # at_end: exactly 7am — should be excluded (ts < window_end fails)
            {"id": "at_end", "created_at": window_end},
        ],
    )

    result = await _process_camera(fake_dev, window_start, window_end)

    expected_count = 2
    assert len(result) == expected_count
    # Check timestamps belong to the accepted events' created_at_utc field.
    ts_strs = {ev["created_at_utc"] for ev in result}
    assert window_start.isoformat() in ts_strs


@pytest.mark.asyncio
async def test_collect_all_events_aggregates_across_cameras():  # type: ignore[no-untyped-def]
    """Events from multiple cameras are merged and sorted by created_at_utc."""
    window_start = datetime(2026, 10, 17, 19, 0, tzinfo=_tz.utc)
    window_end = datetime(2026, 10, 18, 7, 0, tzinfo=_tz.utc)

    cam_a_events = [
        {"id": "a2", "created_at": datetime(2026, 10, 18, 5, 0, tzinfo=_tz.utc)},
        {"id": "a1", "created_at": datetime(2026, 10, 18, 3, 0, tzinfo=_tz.utc)},
    ]
    cam_b_events = [
        {"id": "b1", "created_at": datetime(2026, 10, 18, 4, 0, tzinfo=_tz.utc)},
        {"id": "b2", "created_at": datetime(2026, 10, 18, 6, 0, tzinfo=_tz.utc)},
    ]

    cam_a = _make_fake_device(dev_id=1, name="Cam A", events=cam_a_events)
    cam_b = _make_fake_device(dev_id=2, name="Cam B", events=cam_b_events)

    result_events, total_raw = await _collect_all_events([cam_a, cam_b], window_start, window_end)

    assert len(result_events) == 4
    assert total_raw == 4
    # Sorted ascending by created_at_utc.
    timestamps = [ev["created_at_utc"] for ev in result_events]
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio
async def test_collect_all_events_handles_exclusive_window():  # type: ignore[no-untyped-def]
    """Event exactly at window_end is excluded (< operator)."""
    window_start = datetime(2026, 10, 17, 19, 0, tzinfo=_tz.utc)
    window_end_ts = datetime(2026, 10, 18, 7, 0, tzinfo=_tz.utc)

    fake_dev = _make_fake_device(
        dev_id=1,
        name="Cam X",
        events=[{"id": "e", "created_at": window_end_ts}],  # exactly at end — excluded
    )

    result_events, total_raw = await _collect_all_events([fake_dev], window_start, window_end_ts)

    assert len(result_events) == 0
    assert total_raw == 0


@pytest.mark.asyncio
async def test_collect_all_events_empty_devices():  # type: ignore[no-untyped-def]
    """Empty device list returns two empty results."""
    window_start = datetime(2026, 10, 17, 19, 0, tzinfo=_tz.utc)
    window_end = datetime(2026, 10, 18, 7, 0, tzinfo=_tz.utc)

    result_events, total_raw = await _collect_all_events([], window_start, window_end)

    assert result_events == []
    assert total_raw == 0
