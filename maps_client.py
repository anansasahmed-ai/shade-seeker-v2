import bisect
import datetime
import math
import os
from dataclasses import dataclass

import polyline
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
REQUEST_TIMEOUT_S = 10
EARTH_RADIUS_M = 6_371_000.0

DEPARTURE_LEAD_TIME = datetime.timedelta(minutes=1)

SUPPORTED_MODES = ("DRIVE", "TRANSIT")
MODE_ALIASES = {
    "DRIVE": "DRIVE",
    "DRIVING": "DRIVE",
    "CAR": "DRIVE",
    "TAXI": "DRIVE",
    # Private / intercity highway buses operate on road networks like cars
    "PRIVATE BUS": "DRIVE",
    "INTERCITY BUS": "DRIVE",
    "GREYHOUND": "DRIVE",
    "FLIXBUS": "DRIVE",
    "TRANSIT": "TRANSIT",
    "TRAIN": "TRANSIT",
    "SUBWAY": "TRANSIT",
    "METRO": "TRANSIT",
    # Public municipal / city transit buses use scheduled transit routing
    "BUS": "TRANSIT",
    "PUBLIC BUS": "TRANSIT",
}


class MapsError(Exception):
    """Raised for Routes API failures. `retryable` marks transient problems."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class RouteData:
    coords: list  # list[tuple[float, float]] as (lat, lon)
    distance_m: float
    duration_s: float


def normalize_travel_mode(mode: str | None) -> str:
    key = (mode or "DRIVE").strip().upper()
    if key not in MODE_ALIASES:
        raise ValueError(
            f"Unsupported travel mode '{mode}'. Supported modes: {', '.join(SUPPORTED_MODES)}."
        )
    return MODE_ALIASES[key]


def to_rfc3339_utc(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Departure time must be timezone-aware.")
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_duration_seconds(value) -> float:
    try:
        return float(str(value).strip().rstrip("s"))
    except ValueError:
        return 0.0


def format_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} hr {minutes} min"
    if hours:
        return f"{hours} hr"
    return f"{max(minutes, 1)} min"


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def cumulative_distances(coords: list[tuple[float, float]]) -> list[float]:
    cumulative = [0.0]
    for (lat1, lon1), (lat2, lon2) in zip(coords, coords[1:]):
        cumulative.append(cumulative[-1] + haversine_m(lat1, lon1, lat2, lon2))
    return cumulative


def point_at_distance(
    coords: list[tuple[float, float]], cumulative: list[float], distance_m: float
) -> tuple[float, float]:
    d = min(max(distance_m, 0.0), cumulative[-1])
    i = min(max(bisect.bisect_right(cumulative, d), 1), len(coords) - 1)
    segment_len = cumulative[i] - cumulative[i - 1]
    frac = (d - cumulative[i - 1]) / segment_len if segment_len > 0 else 0.0
    lat = coords[i - 1][0] + (coords[i][0] - coords[i - 1][0]) * frac
    lon = coords[i - 1][1] + (coords[i][1] - coords[i - 1][1]) * frac
    return lat, lon


def heading_at_distance(
    coords: list[tuple[float, float]],
    cumulative: list[float],
    distance_m: float,
    window_m: float = 250.0,
) -> float:
    start = point_at_distance(coords, cumulative, distance_m - window_m)
    end = point_at_distance(coords, cumulative, distance_m + window_m)
    return calculate_bearing(start[0], start[1], end[0], end[1])


class MapsClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
        if not self.api_key:
            try:
                self.api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
            except Exception:
                pass
        if not self.api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY missing from environment and secrets.")

    def get_route(
        self,
        origin: str,
        destination: str,
        travel_mode: str = "DRIVE",
        departure_time_utc: datetime.datetime | None = None,
    ) -> RouteData:
        mode = normalize_travel_mode(travel_mode)
        now = datetime.datetime.now(datetime.timezone.utc)

        body = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": mode,
        }
        if mode == "DRIVE":
            body["routingPreference"] = "TRAFFIC_AWARE"
            if departure_time_utc and departure_time_utc > now + DEPARTURE_LEAD_TIME:
                body["departureTime"] = to_rfc3339_utc(departure_time_utc)
        elif mode == "TRANSIT" and departure_time_utc:
            body["departureTime"] = to_rfc3339_utc(departure_time_utc)

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
        }

        try:
            res = requests.post(ROUTES_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT_S)
        except requests.exceptions.Timeout:
            raise MapsError("Google Routes API timed out.", retryable=True)
        except requests.exceptions.RequestException as e:
            raise MapsError(f"Network error contacting Google Routes API: {e}", retryable=True)

        if res.status_code != 200:
            try:
                detail = res.json().get("error", {}).get("message", res.text)
            except ValueError:
                detail = res.text
            retryable = res.status_code == 429 or res.status_code >= 500

            if mode == "TRANSIT" and ("no route found" in detail.lower() or res.status_code == 400):
                raise MapsError(
                    "No direct transit connection found for the requested time. "
                    "Consider checking an alternative departure time or switching to driving/private bus."
                )
            raise MapsError(f"Routes API error ({res.status_code}): {detail}", retryable=retryable)

        routes = res.json().get("routes", [])
        if not routes:
            if mode == "TRANSIT":
                raise MapsError(
                    "No transit route found at this exact time. "
                    "Would you like to try a different departure time or check driving/private bus options?"
                )
            raise MapsError(f"No {mode.lower()} route found between these locations.")

        route = routes[0]
        encoded = route.get("polyline", {}).get("encodedPolyline")
        if not encoded:
            raise MapsError("The Routes API returned no route geometry.")

        coords = polyline.decode(encoded)
        if len(coords) < 2:
            raise MapsError("The route geometry is too short to analyse.")

        return RouteData(
            coords=coords,
            distance_m=float(route.get("distanceMeters", 0)),
            duration_s=parse_duration_seconds(route.get("duration", "0s")),
        )
