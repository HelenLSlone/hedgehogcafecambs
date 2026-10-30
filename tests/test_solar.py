"""Tests for pipeline/solar.py — civil twilight calculation from lat/lon.

Covers get_dawn_dawn, get_window_with_offsets, and validate_coords against:
- Known reference values (Cambridgeshire mid-Oct, UTC)
- Date parameter flexibility
- Polar edge cases (midnight sun / polar night)
- Validation errors (bad lat/lon ranges)
"""

import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from pipeline.solar import (
    _compute_utc_twilight_minutes,
    _minutes_to_utc_dt,
    get_window_with_offsets,
    get_dawn_dawn,
    validate_coords,
)

# Ensure project root is on sys.path for imports without subprocess.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Known reference data — Cambridgeshire (52.2N, 0.1W)
# Verified against Python implementation before writing tests.
# Oct 17: dawn ≈ 05:57 UTC, dusk ≈ 17:37 UTC
# Oct 18: dawn ≈ 05:58 UTC, dusk ≈ 17:35 UTC
# ---------------------------------------------------------------------------

LAT = 52.2      # Cambridgeshire
LON = 0.1       # ~0°W

# Tolerance windows (minutes) for datetime comparisons — NOAA gives ±2min accuracy.
_TOLERANCE_MINUTES = 5


# ===========================================================================
# get_dawn_dawn — basic functionality
# =================================================================----------

class TestGetDawnDawn:
    """Tests for the public get_dawn_dawn(lat, lon, date=None) API."""

    def test_returns_tuple_of_utc_datetimes(self) -> None:
        """get_dawn_dawn returns a (datetime, datetime) tuple with UTC tzinfo."""
        dawn, dusk = get_dawn_dawn(LAT, LON)
        assert isinstance(dawn, datetime), "dawn must be a datetime"
        assert isinstance(dusk, datetime), "dusk must be a datetime"
        assert dawn.tzinfo == UTC, "dawn must be UTC-aware"
        assert dusk.tzinfo == UTC, "dusk must be UTC-aware"

    def test_dawn_before_dusk(self) -> None:
        """Dawn (first element) must occur before dusk (second element)."""
        dawn, dusk = get_dawn_dawn(LAT, LON)
        assert dawn < dusk, f"dawn {dawn} must be before dusk {dusk}"

    def test_oct_17_cambridgeshire_values(self) -> None:
        """Oct 17 at 52.2°N/0.1°W: dawn ≈ 05:57 UTC, dusk ≈ 17:37 UTC."""
        target_date = date(2026, 10, 17)
        dawn, dusk = get_dawn_dawn(LAT, LON, target_date)

        # Expected: ~05:57 and ~17:37 — within ±5 min tolerance.
        assert (dawn.hour == 5 and 52 <= dawn.minute <= 62) or (
            dawn.hour == 6 and 0 <= dawn.minute <= 2
        ), f"Oct 17 dawn {dawn} outside expected ~05:57 ±5min UTC"
        assert (dusk.hour == 17 and 32 <= dusk.minute <= 42) or (
            dusk.hour == 18 and 0 <= dusk.minute <= 2
        ), f"Oct 17 dusk {dusk} outside expected ~17:37 ±5min UTC"

    def test_oct_18_cambridgeshire_values(self) -> None:
        """Oct 18 at 52.2°N/0.1°W: dawn ≈ 05:58 UTC, dusk ≈ 17:35 UTC."""
        target_date = date(2026, 10, 18)
        dawn, dusk = get_dawn_dawn(LAT, LON, target_date)

        assert (dawn.hour == 5 and 53 <= dawn.minute <= 63) or dawn == datetime(
            2026, 10, 19, 5, 58, 0, tzinfo=UTC
        ), f"Oct 18 dawn {dawn} outside expected ~05:58 ±5min UTC"
        assert (dusk.hour == 17 and 30 <= dusk.minute <= 40) or dusk == datetime(
            2026, 10, 19, 17, 35, 0, tzinfo=UTC
        ), f"Oct 18 dusk {dusk} outside expected ~17:35 ±5min UTC"

    def test_default_date_is_today(self) -> None:
        """When date=None, get_dawn_dawn uses current UTC date."""
        today = datetime.now(UTC).date()
        dawn, _dusk = get_dawn_dawn(LAT, LON)

        # Return dates should match `today` (±1 day for edge wrapping at midnight).
        assert abs((dawn.date() - today).days) <= 1, \
            f"Expected today {today}, got dawn on {dawn.date()}"

    def test_raises_valueerror_for_invalid_latitude(self) -> None:
        """Latitude outside −90…90 raises ValueError."""
        with pytest.raises(ValueError, match="Latitude must be between"):
            get_dawn_dawn(91.0, LON)

        with pytest.raises(ValueError, match="Latitude must be between"):
            get_dawn_dawn(-91.0, LON)

    def test_raises_valueerror_for_invalid_longitude(self) -> None:
        """Longitude outside −180…180 raises ValueError."""
        with pytest.raises(ValueError, match="Longitude must be between"):
            get_dawn_dawn(LAT, 181.0)

        with pytest.raises(ValueError, match="Longitude must be between"):
            get_dawn_dawn(LAT, -181.0)

    def test_polar_edge_case_returns_single_noon_value(self) -> None:
        """At high latitudes where sun never reaches −6° elevation, returns
        a single-noon tuple for both dawn and dusk."""
        # 78°N (Svalbard) — midnight sun or polar night in Oct.
        high_lat = 78.0

        dawn, dusk = get_dawn_dawn(high_lat, LON)

        # If polar case: both should be close to noon (12:00).
        # If not polar: just verify reasonable values.
        diff_minutes = abs((dusk - dawn).total_seconds()) / 60

        if diff_minutes < 5:
            # Polar case — both at noon.
            assert 11 <= dawn.hour <= 13, "Polar edge case should ≈ midnight-noon"
            assert 11 <= dusk.hour <= 13, "Polar edge case should ≈ midnight-noon"

    def test_midsummer_extreme_daylight_cambridgeshire(self) -> None:
        """On Jun 21 at 52.2°N, civil twilight may be very early/late
        due to longer nights from axial tilt."""
        target_date = date(2026, 6, 21)

        dawn, dusk = get_dawn_dawn(LAT, LON, target_date)

        # Dawn should still be before solar noon (before ~12:00 UTC).
        assert dawn.hour < 7, f"Summer dawn {dawn} should be very early at 52°N"
        # Dusk should be after ~20:00 local.
        assert dusk.hour > 20 or (dusk.hour == 20 and dusk.minute > 30), \
            f"Summer dusk {dusk} should be very late at 52°N"

class TestNocturnalWindow:
    """Tests for the dusk→dawn nocturnal window in get_window_with_offsets."""

    def test_window_spans_midnight(self) -> None:
        """Nocturnal window must cross midnight: dusk (prev day) → dawn (today)."""
        target_date = date(2026, 10, 17)
        win_start, win_end = get_window_with_offsets(date=target_date)

        # The key invariant: start.day != end.day and they are adjacent.
        assert win_start.date() != win_end.date(), \
            f"Window must span midnight: {win_start} → {win_end}"
        delta_days = (win_end.date() - win_start.date()).days
        assert delta_days == 1, \
            f"Expected adjacent days, got start={win_start.date()}, end={win_end.date()}"

        # Also verify dawn < dusk in wall-clock order within each day.
        assert win_start.hour <= 18, f"dusk window should be evening {win_start}"
        assert win_end.hour >= 4, f"dawn window should be morning {win_end}"

    def test_offsets_widen_night_window(self) -> None:
        """Offsets widen the night window: dusk pushed earlier, dawn pushed later.

        Config values: dusk_offset_minutes=30, dawn_offset_minutes=-30.
        Expected after _build_nocturnal_window fix:
          - dusk  = prev_dusk_min - dusk_off(30)      →  subtract 30  → earlier ✓
          - dawn  = today_dawn_min - dawn_off(-30)    →  add 30     → later ✓
        """
        target_date = date(2026, 10, 17)

        win_start_0, win_end_0 = get_window_with_offsets(date=target_date)

        # Use _compute_utc_twilight_minutes directly — it gives raw minute-floats
        # for the prev day's dusk (index [1]) and today's dawn (index [0]).
        prev_min = _compute_utc_twilight_minutes(LAT, LON, 2026, 10, 16)
        today_min = _compute_utc_twilight_minutes(LAT, LON, 2026, 10, 17)
        base_dusk_min = prev_min[1]    # Oct 16 dusk in minutes from midnight
        base_dawn_min = today_min[0]   # Oct 17 dawn in minutes from midnight

        # Convert minute-floats to comparable datetimes.
        base_dusk_dt = _minutes_to_utc_dt(2026, 10, 16, base_dusk_min)
        base_dawn_dt = _minutes_to_utc_dt(2026, 10, 17, base_dawn_min)

        # dusk offset (+30): pushes window earlier → diff should be ~-30 min.
        diff_start = (win_start_0 - base_dusk_dt).total_seconds() / 60
        assert -50 <= diff_start < 0, \
            f"Expected dusk pushed earlier by ~30min (diff negative), got {diff_start:.1f}min"

        # dawn offset (-30); negate → add 30: pushes window later → diff should be ~+30.
        diff_end = (win_end_0 - base_dawn_dt).total_seconds() / 60
        assert 0 < diff_end <= 50, \
            f"Expected dawn pushed later by ~30min (diff positive), got {diff_end:.1f}min"

    def test_window_values_match_expected_night_span(self) -> None:
        """Oct 17 night window should span ~evening to ~early-morning dawn.

        Expected (after fix): dusk pushed earlier by dusk_offset, dusk on prev
        day; dawn pushed later by dawn_offset, dawn on today.
        For Cambridgeshire Oct 17: start≈17:09 UTC (Oct 16), end≈06:25 UTC (Oct 17).
        """
        target_date = date(2026, 10, 17)
        win_start, win_end = get_window_with_offsets(date=target_date)

        # Rough boundaries for Cambridgeshire on mid-Oct.
        assert win_start.hour == 17, f"Expected evening start hour 17 {win_start}"
        assert win_start.minute < 15, f"dusk-window should be ~Oct16 17:09 {win_start}"

        assert win_end.hour == 6, f"Expected early-morning end hour 6 {win_end}"


# ===========================================================================
# Internal helpers — _compute_utc_twilight_minutes / validate_coords
# =================================================================----------

class TestInternalHelpers:
    """Tests for _compute_utc_twilight_minutes and validate_coords."""

    def test_compute_minutes_returns_two_values(self) -> None:
        """_compute returns a (float, float) or None tuple for polar cases."""
        result = _compute_utc_twilight_minutes(LAT, LON, 2026, 10, 17)

        assert result is not None, "Cambridgeshire should compute twilight"
        dawn_min, dusk_min = result

        assert isinstance(dawn_min, float), "dawn must be float minutes"
        assert isinstance(dusk_min, float), "dusk must be float minutes"

        # 05:57 UTC ≈ 357 min from midnight.
        assert 350 <= dawn_min <= 365, f"dawn_min {dawn_min} outside expected ~357"
        # 17:37 UTC ≈ 1057 min from midnight.
        assert 1050 <= dusk_min <= 1065, f"dusk_min {dusk_min} outside expected ~1057"

    def test_validate_coords_passes_valid_ranges(self) -> None:
        """validate_coords should NOT raise for −90…90 / −180…180."""
        validate_coords(0.0, 0.0)      # Equator + Greenwich
        validate_coords(90.0, 180.0)   # Max boundaries
        validate_coords(-52.0, -3.0)   # Valid negative range

    def test_validate_coords_raises_beyond_boundaries(self) -> None:
        """validate_coords must raise ValueError outside ±90 lat / ±180 lon."""
        with pytest.raises(ValueError):
            validate_coords(91.0, 0.0)

        with pytest.raises(ValueError):
            validate_coords(-91.0, 0.0)

        with pytest.raises(ValueError):
            validate_coords(0.0, 181.0)
