import datetime
import pytest
from pydantic import ValidationError
from solar_math import get_sun_position, side_sun_load


def test_get_sun_position_basic():
    # Test a known location and time (e.g., Oaxaca, Mexico at summer noon UTC)
    dt = datetime.datetime(2026, 6, 21, 18, 0, 0, tzinfo=datetime.timezone.utc)
    res = get_sun_position(17.0753, -96.7236, dt)
    
    assert isinstance(res["azimuth"], float)
    assert isinstance(res["elevation"], float)
    assert res["elevation"] > 0.0


def test_get_sun_position_boundaries():
    # Equator & Prime Meridian
    dt = datetime.datetime(2026, 3, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
    res_eq = get_sun_position(0.0, 0.0, dt)
    assert 85.0 <= res_eq["elevation"] <= 90.0

    # North & South Poles
    res_north = get_sun_position(90.0, 180.0, dt)
    res_south = get_sun_position(-90.0, -180.0, dt)
    assert isinstance(res_north["elevation"], float)
    assert isinstance(res_south["elevation"], float)


@pytest.mark.parametrize("invalid_lat,invalid_lon", [
    (95.0, 0.0),      # Latitude > 90
    (-90.1, 0.0),     # Latitude < -90
    (0.0, 185.0),     # Longitude > 180
    (0.0, -180.1),    # Longitude < -180
])
def test_get_sun_position_invalid_coordinates(invalid_lat, invalid_lon):
    dt = datetime.datetime(2026, 6, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)
    with pytest.raises(ValidationError):
        get_sun_position(invalid_lat, invalid_lon, dt)


def test_side_sun_load():
    # Sun below horizon -> 0 load
    assert side_sun_load(180.0, -5.0, 0.0) == 0.0
    
    # Heading North (0), sun due East (90) at 0 deg elevation -> max right-side load (+1.0)
    load_right = side_sun_load(90.0, 0.001, 0.0)
    assert load_right > 0.99
    
    # Heading North (0), sun due West (270) at 0 deg elevation -> max left-side load (-1.0)
    load_left = side_sun_load(270.0, 0.001, 0.0)
    assert load_left < -0.99
