import datetime
import math
import pandas as pd
from pvlib import solarposition
from pydantic import BaseModel, Field, field_validator


class SolarCoordinates(BaseModel):
    lat: float = Field(..., description="Latitude in decimal degrees")
    lon: float = Field(..., description="Longitude in decimal degrees")

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError(f"Latitude {v} is invalid. Must be between -90.0 and 90.0.")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError(f"Longitude {v} is invalid. Must be between -180.0 and 180.0.")
        return v


def get_sun_position(lat: float, lon: float, dt_utc: datetime.datetime | pd.Timestamp) -> dict:
    """
    Calculates solar azimuth and apparent elevation for a place and UTC time.
    Validated via Pydantic to ensure geographic safety.
    """
    # Validate inputs using Pydantic
    coords = SolarCoordinates(lat=lat, lon=lon)
    
    ts = pd.Timestamp(dt_utc)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    solpos = solarposition.get_solarposition(pd.DatetimeIndex([ts]), coords.lat, coords.lon)

    return {
        "azimuth": float(solpos["azimuth"].iloc[0]),
        "elevation": float(solpos["apparent_elevation"].iloc[0]),
    }


def side_sun_load(sun_azimuth: float, sun_elevation: float, heading: float) -> float:
    """
    Signed strength of the sun shining through the vehicle's side windows.
    """
    if sun_elevation <= 0:
        return 0.0
    relative_angle = math.radians((sun_azimuth - heading) % 360)
    return math.sin(relative_angle) * math.cos(math.radians(sun_elevation))
