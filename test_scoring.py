import datetime
from unittest.mock import MagicMock, patch
import pytest

from maps_client import RouteData
from scoring import (
    InvalidRouteParametersError,
    RouteCalculationError,
    build_seat_recommendation,
    evaluate_route_shade,
    parse_departure,
    resolve_timezone,
)


# --------------------------------------------------------------------------- #
# 1. Unit Tests: Timezone & Departure Parsing (Including DST Edge Cases)
# --------------------------------------------------------------------------- #

def test_resolve_timezone_mumbai():
    tz = resolve_timezone(19.0760, 72.8777)
    assert getattr(tz, "key", "") == "Asia/Kolkata"


def test_parse_departure_local_to_utc_mumbai():
    # Leaving Mumbai at 2:00 PM local time (IST is UTC+5:30) -> 8:30 AM UTC
    tz = resolve_timezone(19.0760, 72.8777)
    utc_dt = parse_departure("2026-06-21T14:00:00", tz)
    assert utc_dt == datetime.datetime(2026, 6, 21, 8, 30, tzinfo=datetime.timezone.utc)


def test_parse_departure_dst_transition_uk():
    # Penzance, UK during British Summer Time (BST = UTC+1) vs Standard Time (GMT = UTC+0)
    tz_uk = resolve_timezone(50.1186, -5.5371)
    
    # Summer (BST)
    summer_utc = parse_departure("2026-07-15T12:00:00", tz_uk)
    assert summer_utc == datetime.datetime(2026, 7, 15, 11, 0, tzinfo=datetime.timezone.utc)
    
    # Winter (GMT)
    winter_utc = parse_departure("2026-11-15T12:00:00", tz_uk)
    assert winter_utc == datetime.datetime(2026, 11, 15, 12, 0, tzinfo=datetime.timezone.utc)


def test_parse_departure_invalid_format():
    tz = datetime.timezone.utc
    with pytest.raises(InvalidRouteParametersError):
        parse_departure("not-a-valid-date", tz)


# --------------------------------------------------------------------------- #
# 2. Unit Tests: Seat Recommendation Logic
# --------------------------------------------------------------------------- #

def test_seat_recommendation_nighttime():
    res = build_seat_recommendation(left_load=0.0, right_load=0.0, samples=20, daylight_samples=0)
    assert res["recommended_side"] == "either"
    assert "below the horizon" in res["seat_advice"]


def test_seat_recommendation_prefers_shaded_side():
    # Heavy sun on right side (80%) -> recommend sitting on LEFT side
    res = build_seat_recommendation(left_load=2.0, right_load=8.0, samples=10, daylight_samples=10)
    assert res["recommended_side"] == "left"
    assert res["sun_exposure_left_percent"] == 20.0
    assert res["sun_exposure_right_percent"] == 80.0


# --------------------------------------------------------------------------- #
# 3. Integration Tests: Mocking External Maps API
# --------------------------------------------------------------------------- #

@patch("scoring._get_client")
def test_evaluate_route_shade_integration_mocked_maps(mock_get_client):
    """
    Tests the full scoring pipeline (Timezone lookup -> UTC conversion -> Solar Math -> Seat Advice)
    while mocking the external MapsClient so no real network/API calls are made.
    """
    # Create a fake north-bound route in Oaxaca, Mexico (~10 km, 20 mins)
    fake_route = RouteData(
        coords=[
            (17.0600, -96.7250),
            (17.1050, -96.7250),
            (17.1500, -96.7250),
        ],
        distance_m=10000.0,
        duration_s=1200.0,
    )
    
    mock_client_instance = MagicMock()
    mock_client_instance.get_route.return_value = fake_route
    mock_get_client.return_value = mock_client_instance

    # Clear Streamlit cache before test so mocked client is always used
    from scoring import _fetch_route
    _fetch_route.clear()

    # Simulate morning departure (8:00 AM local time in Oaxaca) driving North -> sun is on the East (RIGHT)
    result = evaluate_route_shade(
        origin="Oaxaca Centro",
        destination="Etla, Oaxaca",
        travel_mode="DRIVE",
        departure_time_str="2026-06-21T08:00:00",
    )

    assert result["origin"] == "Oaxaca Centro"
    assert result["timezone"] == "America/Mexico_City"
    # Driving North in the morning means the eastern sun hits the RIGHT side -> recommend LEFT seat
    assert result["recommended_side"] == "left"
    assert 10.0 <= result["average_shade_percentage"] <= 85.0
    assert mock_client_instance.get_route.call_count == 2


def test_evaluate_route_shade_rejects_blank_inputs():
    with pytest.raises(InvalidRouteParametersError):
        evaluate_route_shade(origin="   ", destination="Oaxaca")


@patch("scoring._get_client")
def test_evaluate_route_shade_empty_coords_raises_calculation_error(mock_get_client):
    mock_client_instance = MagicMock()
    mock_client_instance.get_route.return_value = RouteData(coords=[], distance_m=0.0, duration_s=0.0)
    mock_get_client.return_value = mock_client_instance

    from scoring import _fetch_route
    _fetch_route.clear()

    with pytest.raises(RouteCalculationError):
        evaluate_route_shade(origin="Point A", destination="Point B")
@patch("scoring._get_client")
def test_evaluate_route_shade_dst_transition_edge_case(mock_get_client):
    """
    Integration test verifying that route shade evaluation handles a trip
    occurring across the autumn DST transition (clocks falling back).
    """
    # Create a fake route in the UK (Penzance to Truro, ~40km, 45 minutes)
    fake_route = RouteData(
        coords=[
            (50.1186, -5.5371),
            (50.1500, -5.2500),
            (50.2632, -5.0510),
        ],
        distance_m=40000.0,
        duration_s=2700.0, # 45 minutes
    )
    
    mock_client_instance = MagicMock()
    mock_client_instance.get_route.return_value = fake_route
    mock_get_client.return_value = mock_client_instance

    from scoring import _fetch_route
    _fetch_route.clear()

    # Departure time on October 25, 2026, at 1:30 AM local time (right during the DST shift week)
    result = evaluate_route_shade(
        origin="Penzance",
        destination="Truro",
        travel_mode="DRIVE",
        departure_time_str="2026-10-25T01:30:00",
    )

    # Verify the evaluation succeeds and returns valid metrics despite the clock shift
    assert result["origin"] == "Penzance"
    assert result["timezone"] == "Europe/London"
    assert "average_shade_percentage" in result
    assert result["recommended_side"] in ["left", "right", "either"]
