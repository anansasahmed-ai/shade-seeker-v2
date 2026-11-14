import datetime
import logging
import math
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st
from pydantic import BaseModel, Field, ValidationError, field_validator
from timezonefinder import TimezoneFinder

from maps_client import (
    MapsClient,
    RouteData,
    cumulative_distances,
    format_duration,
    heading_at_distance,
    normalize_travel_mode,
    point_at_distance,
)
from solar_math import get_sun_position, side_sun_load

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ScoringError(Exception):
    """Base exception for route shade scoring errors."""


class InvalidRouteParametersError(ScoringError, ValueError):
    """Raised when route inputs are invalid."""


class RouteCalculationError(ScoringError):
    """Raised when route geometry or duration cannot be evaluated."""


class RouteEvaluationRequest(BaseModel):
    origin: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)
    travel_mode: str = Field(default="DRIVE")
    departure_time_str: str | None = Field(default=None)

    @field_validator("origin", "destination")
    @classmethod
    def validate_location(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Location cannot be blank.")
        return cleaned

    @field_validator("travel_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        return normalize_travel_mode(v)


SUNNY_ELEVATION_DEG = 10.0
MIN_SHADE_PCT = 10.0
MAX_SHADE_PCT = 85.0
SAMPLE_INTERVAL_MIN = 2
MIN_SAMPLES = 12
MAX_SAMPLES = 200
HEADING_WINDOW_M = 250.0
MIN_AVG_SIDE_LOAD = 0.05
BALANCED_MARGIN_PCT = 10.0
CACHE_BUCKET_MIN = 10
CACHE_TTL_S = 600

_client: MapsClient | None = None


def _get_client() -> MapsClient:
    global _client
    if _client is None:
        _client = MapsClient()
    return _client


@st.cache_data(ttl=CACHE_TTL_S, show_spinner=False)
def _fetch_route(origin: str, destination: str, mode: str, departure_iso: str | None) -> RouteData:
    departure = datetime.datetime.fromisoformat(departure_iso) if departure_iso else None
    return _get_client().get_route(origin, destination, mode, departure)


@lru_cache(maxsize=1)
def _timezone_finder() -> TimezoneFinder:
    return TimezoneFinder()


def resolve_timezone(lat: float, lon: float) -> datetime.tzinfo:
    try:
        name = _timezone_finder().timezone_at(lat=lat, lng=lon)
        if name:
            return ZoneInfo(name)
    except (ZoneInfoNotFoundError, Exception):
        pass
    return datetime.timezone(datetime.timedelta(hours=round(lon / 15)))


def parse_departure(departure_str: str | None, tz: datetime.tzinfo) -> datetime.datetime | None:
    if not departure_str:
        return None
    text = departure_str.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise InvalidRouteParametersError(f"Invalid departure time format: '{departure_str}'.") from exc
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(datetime.timezone.utc)


def build_seat_recommendation(left_load: float, right_load: float, samples: int, daylight_samples: int) -> dict:
    total = left_load + right_load
    left_pct = round(100 * left_load / total, 1) if total > 0 else 0.0
    right_pct = round(100 * right_load / total, 1) if total > 0 else 0.0

    if daylight_samples == 0:
        advice = "The sun is below the horizon for the whole trip, so no seat gets direct sun."
    elif total / samples < MIN_AVG_SIDE_LOAD:
        advice = "The sun stays mostly ahead of, behind, or high above the vehicle, so neither side gets much direct sun. Either side is fine."
    elif abs(left_pct - right_pct) < BALANCED_MARGIN_PCT:
        advice = f"Side sun is split almost evenly ({left_pct:.0f}% left / {right_pct:.0f}% right), so either side is fine."
    else:
        side = "left" if left_pct < right_pct else "right"
        other = "right" if side == "left" else "left"
        side_pct, other_pct = (left_pct, right_pct) if side == "left" else (right_pct, left_pct)
        return {
            "recommended_side": side,
            "sun_exposure_left_percent": left_pct,
            "sun_exposure_right_percent": right_pct,
            "seat_advice": f"Sit on the {side.upper()} side (~{side_pct:.0f}% vs {other_pct:.0f}% on the {other}).",
        }

    return {
        "recommended_side": "either",
        "sun_exposure_left_percent": left_pct,
        "sun_exposure_right_percent": right_pct,
        "seat_advice": advice,
    }


def evaluate_route_shade(origin: str, destination: str, travel_mode: str = "DRIVE", departure_time_str: str | None = None) -> dict:
    try:
        req = RouteEvaluationRequest(origin=origin, destination=destination, travel_mode=travel_mode, departure_time_str=departure_time_str)
    except ValidationError as exc:
        messages = [err.get("msg", "").replace("Value error, ", "") for err in exc.errors()]
        raise InvalidRouteParametersError("; ".join(messages)) from exc

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    base_route = _fetch_route(req.origin, req.destination, req.travel_mode, None)
    if not base_route.coords:
        raise RouteCalculationError("Route returned no coordinates.")

    tz = resolve_timezone(*base_route.coords[0])
    departure_utc = parse_departure(req.departure_time_str, tz) or now_utc

    route = base_route
    if req.departure_time_str:
        bucket_dt = departure_utc.replace(minute=(departure_utc.minute // CACHE_BUCKET_MIN) * CACHE_BUCKET_MIN, second=0, microsecond=0)
        route = _fetch_route(req.origin, req.destination, req.travel_mode, bucket_dt.isoformat())

    coords = route.coords
    cumulative = cumulative_distances(coords)
    if cumulative[-1] <= 0:
        raise InvalidRouteParametersError("Origin and destination are identical.")

    n = max(MIN_SAMPLES, min(MAX_SAMPLES, math.ceil(route.duration_s / 60 / SAMPLE_INTERVAL_MIN) + 1))
    sunny = daylight = 0
    left_load = right_load = 0.0

    for i in range(n):
        fraction = i / (n - 1)
        dist = fraction * cumulative[-1]
        lat, lon = point_at_distance(coords, cumulative, dist)
        heading = heading_at_distance(coords, cumulative, dist, HEADING_WINDOW_M)
        pt_time = departure_utc + datetime.timedelta(seconds=fraction * route.duration_s)

        sun = get_sun_position(lat, lon, pt_time)
        if sun["elevation"] > SUNNY_ELEVATION_DEG:
            sunny += 1
        if sun["elevation"] > 0:
            daylight += 1

        load = side_sun_load(sun["azimuth"], sun["elevation"], heading)
        if load > 0:
            right_load += load
        else:
            left_load -= load

    shade_pct = max(MIN_SHADE_PCT, min(MAX_SHADE_PCT, round((1.0 - sunny / n) * 100, 1)))
    seat = build_seat_recommendation(left_load, right_load, n, daylight)
    local_dep = departure_utc.astimezone(tz)

    return {
        "origin": req.origin,
        "destination": req.destination,
        "travel_mode": req.travel_mode,
        "departure_local": local_dep.strftime("%A, %B %d, %Y at %I:%M %p"),
        "timezone": getattr(tz, "key", str(tz)),
        "distance_km": round(route.distance_m / 1000, 1),
        "distance_miles": round(route.distance_m / 1609.344, 1),
        "duration": format_duration(route.duration_s),
        "average_shade_percentage": shade_pct,
        **seat,
        "summary": f"Departing {local_dep.strftime('%I:%M %p')}, route is ~{shade_pct}% shaded. {seat['seat_advice']}",
        "coords": coords,
    }
