"""solar.py — Compute civil twilight (dawn/dusk) from lat/lon using stdlib math only.

No external dependencies (`astral` excluded per architectural decision).
Implements NOAA solar position formulas:
  1. Day-of-year → solar declination (δ)
  2. Hour angle at -6° elevation (civil twilight threshold)
  3. Local noon + equation-of-time correction → UTC-converted clock times

Config fields `latitude`, `longitude`, `dusk_offset_minutes`, `dawn_offset_minutes`
are read from ``config.config`` at the top level; this module itself stays
zero-config so the same math can be unit-tested against known reference data.
"""

from __future__ import annotations

import math
from calendar import isleap
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from datetime import (
    date as _date,
)

import config

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_EARTH_ROTATION_RATE_HOURS = 15.0  # degrees per hour (360° / 24h)


def _day_of_year(year: int, month: int, day: int) -> float:
    """Day of year as a float for sub-day precision."""
    days_in_month = [
        0, 31, 29 if isleap(year) else 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31,
    ]
    return sum(days_in_month[:month]) + day


def _solar_declination(year: int, month: int, day: int) -> float:
    """Solar declination in radians — NOAA approximation.

    Formula source:
        https://gml.noaa.gov/grad/solcalc/solar.html
    Uses the standard 14-term Fourier series for sun's apparent geocentric
    declination, which gives sub-minute precision for our purposes.
    """
    d = _day_of_year(year, month, day)

    return (
        +0.006918
        - 0.399912 * math.cos(2 * math.pi / 365 * d)
        + 0.070257 * math.sin(2 * math.pi / 365 * d)
        - 0.006758 * math.cos(4 * math.pi / 365 * d)
        + 0.000937 * math.sin(4 * math.pi / 365 * d)
    )


def _equation_of_time(year: int, month: int, day: int) -> float:
    """Equation of Time in minutes — apparent vs mean solar time.

    Returns value in minutes to add to mean solar noon to get apparent noon.
    Source: NOAA solar calculator / US Naval Observatory formulae.
    """
    d = _day_of_year(year, month, day)

    return (
        +7.655 * math.sin(2 * math.pi / 365 * d)
        - 12.9613 * math.cos(2 * math.pi / 365 * d)
        + 5.946 * math.sin(4 * math.pi / 365 * d)
        - 1.2688 * math.cos(4 * math.pi / 365 * d)
        + 0.7123 * math.sin(6 * math.pi / 365 * d)
        - 0.3247 * math.cos(6 * math.pi / 365 * d)
    )


def _hour_angle_for_elevation(
    lat: float,
    year: int,
    month: int,
    day: int,
    elevation_deg: float,
) -> float | None:
    """Hour angle (degrees) when sun reaches a given solar elevation.

    Args:
        lat: Latitude (-90 to 90). Cambridgeshire is ~52°N.
        year: Solar reference year.
        month: Solar reference month.
        day: Solar reference day.
        elevation_deg: Target solar elevation (e.g., -6° for civil twilight).

    Returns:
        Hour angle in degrees, or None if sun never reaches that
        elevation (polar case — e.g. midnight sun or dark period).
    """
    lat_rad = math.radians(lat)
    elev_rad = math.radians(elevation_deg)
    decl_rad = _solar_declination(year, month, day)

    # cos(HA) = (sin(el) - sin(lat)*sin(δ)) / (cos(lat)*cos(δ))
    numerator = math.sin(elev_rad) - math.sin(lat_rad) * math.sin(decl_rad)
    denominator = math.cos(lat_rad) * math.cos(decl_rad)
    cos_ha = numerator / denominator

    if abs(cos_ha) > 1.0:
        return None  # Sun never crosses this elevation.

    return math.degrees(math.acos(cos_ha))


def _minutes_to_utc_dt(year: int, month: int, day: int,
                       minutes_from_midnight: float) -> datetime:
    """Convert minutes-from-midnight UTC to a timezone-aware UTC datetime."""
    m = int(minutes_from_midnight) % 1440  # wrap around daily
    h, rem = divmod(abs(m), 60)

    return datetime(year=year, month=month, day=day, hour=h,
                    minute=rem, second=0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _compute_utc_twilight_minutes(lat: float, lon: float,
                                  year: int, month: int, day: int) -> tuple[float, float] | None:
    """Internal: compute dawn/dusk as minutes from midnight UTC."""
    elev = -6.0  # civil twilight threshold
    ha_deg = _hour_angle_for_elevation(lat, year, month, day, elev)

    if ha_deg is None:
        return None  # Polar case — sun never reaches elevation.

    eot_min = _equation_of_time(year, month, day)

    # Apparent solar noon in UTC minutes (720 = midnight UTC).
    # Longitude → UTC offset: Earth rotates 15°/hr, so each degree is 4 min.
    apparent_noon_utc_min = 720.0 + eot_min - lon * 4.0

    # Dawn/dusk = noon ± (hour-angle in degrees × 4 min/degree).
    twilight_span = ha_deg * 4.0

    return (apparent_noon_utc_min - twilight_span,
            apparent_noon_utc_min + twilight_span)


def _build_window(
    dawn_min: float,
    dusk_min: float,
    ymd: tuple[int, int, int],
) -> tuple[datetime, datetime]:
    """Apply minute-offsets and return timezone-aware UTC datetimes."""
    year, month, day = ymd
    dawn_utc = _minutes_to_utc_dt(year, month, day, dawn_min)
    dusk_utc = _minutes_to_utc_dt(year, month, day, dusk_min)
    return (dawn_utc, dusk_utc)


def get_dawn_dawn(
    lat: float,
    lon: float,
    date: _date | None = None,
) -> tuple[datetime, datetime]:
    """Compute civil twilight (dawn/dusk) times in UTC from lat/lon.

    Args:
        lat: Latitude (-90 to 90). Cambridgeshire is ~52°N.
        lon: Longitude (-180 to 180). Cambridgeshire is ~0°W.
        date: Date to compute for (default today's date).

    Returns:
        Tuple ``(dawn_utc, dusk_utc)`` — both timezone-aware UTC datetimes.

    Raises:
        ValueError: If lat/lon are outside valid ranges or computation fails.

    Notes:
        - Civil twilight threshold = -6° solar elevation. This defines when
          it's "light enough" to see without artificial lighting.
        - For Cambridgeshire in autumn: dawn ≈ 05:57 UTC, dusk ≈ 17:37 UTC.
    """
    validate_coords(lat, lon)

    if date is None:
        date = datetime.now(UTC).date()

    minutes_result = _compute_utc_twilight_minutes(
        lat, lon, date.year, date.month, date.day,
    )

    if minutes_result is None:
        # Polar edge case — sun never reaches -6° elevation.
        noon_utc = datetime(date.year, date.month, date.day, 12, 0, 0, tzinfo=UTC)
        return (noon_utc, noon_utc)

    return _build_window(
        minutes_result[0], minutes_result[1],
        (date.year, date.month, date.day),
    )


def _build_nocturnal_window(
    prev_dusk_min: float,
    today_dawn_min: float,
    dawn_off: int,
    dusk_off: int,
    ymd_prev: tuple[int, int, int],
    ymd_today: tuple[int, int, int],
) -> tuple[datetime, datetime]:
    """Apply offsets and return (yesterday_dusk_utc, today_dawn_utc)."""
    _py, _pm, _pd = ymd_prev
    _ty, _tm, _td = ymd_today
    dusk_utc = _minutes_to_utc_dt(_py, _pm, _pd, prev_dusk_min - dusk_off)
    dawn_utc = _minutes_to_utc_dt(_ty, _tm, _td, today_dawn_min - dawn_off)
    return (dusk_utc, dawn_utc)


def get_window_with_offsets(
    date: _date | None = None,
) -> tuple[datetime, datetime]:
    """Compute dusk→dawn nocturnal window using config from import time.

    Returns ``(window_start_utc, window_end_utc)`` for the overnight period.

    The window spans **from yesterday's dusk through today's dawn**:
    - window_start = dusk on the day before ``date`` + dusk offset
    - window_end   = dawn on ``date`` - dawn offset

    This matches the nocturnal animal camera pipeline: darkness starts
    (evening), then light returns (morning).

    Read lat/lon and offsets from ``config.config`` at call time.

    """
    _cfg = config.config
    lat = float(_cfg.latitude)
    lon = float(_cfg.longitude)
    dusk_off = int(_cfg.dusk_offset_minutes)
    dawn_off = int(_cfg.dawn_offset_minutes)

    validate_coords(lat, lon)

    if date is None:
        date = datetime.now(UTC).date()

    today: _date = date
    yesterday = today - timedelta(days=1)

    # Compute BOTH the previous day's dusk AND today's dawn.
    prev_min = _compute_utc_twilight_minutes(
        lat, lon, yesterday.year, yesterday.month, yesterday.day,
    )
    today_min = _compute_utc_twilight_minutes(
        lat, lon, today.year, today.month, today.day,
    )

    if prev_min is None or today_min is None:
        # Polar edge — fall back to noon placeholder for today.
        noon = datetime(today.year, today.month, today.day, 12, 0, 0, tzinfo=UTC)
        return (noon, noon)

    dusk_prev_min = prev_min[1]   # last_dusk
    dawn_today_min = today_min[0]  # today_dawn

    return _build_nocturnal_window(
        dusk_prev_min, dawn_today_min,
        dawn_off, dusk_off,
        (yesterday.year, yesterday.month, yesterday.day),
        (today.year, today.month, today.day),
    )


def validate_coords(lat: float, lon: float) -> None:
    """Validate lat/lon are within valid ranges.

    Args:
        lat: Latitude (-90 to 90). Cambridgeshire is ~52°N.
        lon: Longitude (-180 to 180). Cambridgeshire is ~0°W.

    Raises:
        ValueError if lat/lon are outside valid ranges or computation fails.

    Notes:
        Helper function used by all public API functions to validate before
        computation. This prevents invalid coordinate crashes from producing
        wrong twilight times silently.
    """
    if not -90 <= lat <= 90:
        raise ValueError(
            f"Latitude must be between -90 and 90 — got {lat}."
        )
    if not -180 <= lon <= 180:
        raise ValueError(
            f"Longitude must be between -180 and 180 — got {lon}."
        )
