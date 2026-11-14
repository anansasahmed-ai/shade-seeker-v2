import datetime
import os
import time
from typing import Optional

import requests
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

from maps_client import MapsError
from scoring import InvalidRouteParametersError, evaluate_route_shade

load_dotenv()

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

gemini_key = os.environ.get("GEMINI_API_KEY")
if not gemini_key:
    try:
        gemini_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

if not gemini_key:
    raise ValueError("GEMINI_API_KEY is missing from environment and Streamlit secrets.")

client = genai.Client(api_key=gemini_key)

route_state = {"coords": None}


def load_agent_guide() -> str:
    """Loads operational guidelines and rules from the Agent Skills & Operational Guide."""
    for filename in ["Agent Skills & Operational Guide.md", "skills.md"]:
        guide_path = os.path.join(os.path.dirname(__file__), filename)
        if os.path.exists(guide_path):
            with open(guide_path, "r", encoding="utf-8") as f:
                return f.read()
    return ""


def get_weather(location: str) -> dict:
    """Gets current weather and forecast conditions for a given city or location.
    Args:
        location: City name or address (e.g., 'Oaxaca City', 'San Francisco').
    """
    try:
        url = f"https://wttr.in/{location}?format=j1"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            current = data.get("current_condition", [{}])[0]
            forecast = data.get("weather", [])
            return {
                "location": location,
                "current_temp_c": current.get("temp_C"),
                "current_condition": current.get("weatherDesc", [{}])[0].get("value"),
                "humidity": current.get("humidity"),
                "cloudcover": current.get("cloudcover"),
                "forecast_summary": forecast[0] if forecast else "No forecast available",
            }
    except Exception:
        pass
    return {"error": f"Could not retrieve weather data for {location}."}


def get_shade_recommendation(
    origin: str,
    destination: str,
    travel_mode: str = "DRIVE",
    departure_datetime: Optional[str] = None,
) -> dict:
    """Calculates how shaded a trip is and which side of the vehicle (left or right) to sit on.
    Args:
        origin: Start location.
        destination: End location.
        travel_mode: 'DRIVE' for cars, private/intercity buses, or 'TRANSIT' for public trains/subways/city buses.
        departure_datetime: Local departure time at the origin in ISO format without a
            timezone offset (e.g. '2026-06-21T08:00:00'). Omit to depart now.
    """
    max_retries = 3
    delay = 2

    for attempt in range(max_retries):
        try:
            res = evaluate_route_shade(
                origin=origin,
                destination=destination,
                travel_mode=travel_mode,
                departure_time_str=departure_datetime or None,
            )
        except InvalidRouteParametersError as e:
            return {"error": str(e)}
        except MapsError as e:
            if e.retryable and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            return {"error": str(e)}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Unexpected error while analysing the route: {e}"}

        route_state["coords"] = res["coords"]
        return {k: v for k, v in res.items() if k != "coords"}

    return {"error": "Service temporarily busy. Please try again in a moment."}


def build_system_instruction() -> str:
    today = datetime.datetime.now()
    guide_content = load_agent_guide()

    return (
        "You are Shade Seeker, a geospatial solar exposure and weather agent "
        f"(Today: {today:%A, %B %d, %Y}).\n\n"
        "--- AGENT SKILLS & OPERATIONAL GUIDE ---\n"
        f"{guide_content}\n"
        "---------------------------------------\n\n"
        "Core Rules:\n"
        "1. You have two tools: get_shade_recommendation and get_weather.\n"
        "2. If the user asks about weather conditions or forecasts, use get_weather.\n"
        "3. CRITICAL LOCATION DISAMBIGUATION RULE: Before calling `get_shade_recommendation`, check if the origin or destination is a major ambiguous city name listed without a state, province, or country (e.g., 'San Jose', 'Portland', 'Springfield', 'Paris', 'London' without country context). If it is ambiguous, **DO NOT call the tool**. Instead, immediately ask the user a clarifying question (e.g., 'Did you mean San Jose, California or San Jose, Costa Rica?').\n"
        "4. Convert the user's date and local departure time into ISO format at the ORIGIN's "
        "local time, with no timezone offset (e.g. '2026-06-21T08:00:00'), for departure_datetime. "
        "If the user gives no departure time, leave departure_datetime empty; never invent one.\n"
        "5. Set travel_mode='TRANSIT' for public transit (trains, subways, local municipal buses). "
        "Set travel_mode='DRIVE' for cars, taxis, or private/intercity highway buses (e.g., Greyhound, FlixBus).\n"
        "6. Never guess percentages or seat sides; rely strictly on tool output.\n"
        "7. When recommending a seat, state the recommended_side and sun exposure percentages "
        "from the tool, making clear that left/right means as seen facing the direction of travel.\n"
        "8. If a tool returns an error or transit availability issue, explain it clearly and offer alternatives."
    )


chat = client.chats.create(
    model=MODEL_NAME,
    config=types.GenerateContentConfig(
        temperature=0.1,
        tools=[get_shade_recommendation, get_weather],
        system_instruction=build_system_instruction(),
    ),
)
