import datetime
from unittest.mock import MagicMock, patch
import pytest

from maps_client import RouteData
from scoring import evaluate_route_shade


@patch("scoring._get_client")
def test_e2e_amtrak_cross_timezone_journey(mock_get_client):
    """
    End-to-End simulation of an Amtrak passenger journey crossing timezones.
    Simulates a long-distance train ride from Chicago (Central Time) 
    to Denver (Mountain Time), spanning multiple hours and a timezone boundary.
    """
    # 1. Simulate a long-distance route geometry across states (~1,600 km, 18 hours of train travel)
    # We provide a simplified sequence of coordinate points representing the rail corridor.
    fake_amtrak_route = RouteData(
        coords=[
            (41.8781, -87.6298),  # Chicago, IL (Central Time)
            (41.5868, -93.6250),  # Des Moines, IA
            (41.2565, -95.9345),  # Omaha, NE
            (39.7392, -104.9903), # Denver, CO (Mountain Time)
        ],
        distance_m=1600000.0, # ~1,600 km
        duration_s=64800.0,   # 18 hours duration
    )

    mock_client_instance = MagicMock()
    # Pass 1 (timezone resolution) and Pass 2 (timed route evaluation) will both use this route mock
    mock_client_instance.get_route.return_value = fake_amtrak_route
    mock_get_client.return_value = mock_client_instance

    # Clear cache to guarantee a fresh run
    from scoring import _fetch_route
    _fetch_route.clear()

    # 2. Execute the full E2E user workflow: 
    # User departs Chicago at 8:00 AM Central Time. 
    # As the 18-hour train rolls west, it crosses the Central -> Mountain timezone boundary.
    result = evaluate_route_shade(
        origin="Chicago Union Station, Chicago, IL",
        destination="Denver Union Station, Denver, CO",
        travel_mode="TRANSIT", # Train/Transit mode
        departure_time_str="2026-06-21T08:00:00",
    )

    # 3. Assertions: Verify the entire pipeline produced a valid, production-ready output structure
    assert result["origin"] == "Chicago Union Station, Chicago, IL"
    assert result["destination"] == "Denver Union Station, Denver, CO"
    assert result["travel_mode"] == "TRANSIT"
    
    # Verify timezone at origin (Chicago is Central Time -> America/Chicago)
    assert result["timezone"] == "America/Chicago"
    
    # Verify distance conversion metrics
    assert result["distance_km"] == 1600.0
    assert result["distance_miles"] > 900.0
    
    # Verify shade scoring & seat recommendation are fully computed
    assert 0.0 <= result["average_shade_percentage"] <= 100.0
    assert result["recommended_side"] in ["left", "right", "either"]
    assert "seat_advice" in result
    assert "summary" in result
    
    # Verify coordinates passed through successfully for rendering maps/uis
    assert len(result["coords"]) == 4
    
    print("\n🚆 E2E Amtrak Simulation Output Summary:")
    print(f" -> {result['summary']}")
    print(f" -> Recommended Seat Side: {result['recommended_side'].upper()}")
