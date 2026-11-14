"""
Weather tool: the current weather and the next few days for a place.

Uses Open-Meteo (open-meteo.com), which is free and needs no API key.
It takes two requests:
  1. "geocoding": turn a place name like "Leeds" into map coordinates
  2. the forecast for those coordinates
"""

import os

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 8   # seconds

# Open-Meteo describes the sky with a number (a "WMO weather code").
# These are the words for each one.
WEATHER_WORDS = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}


def get_weather(place: str = "") -> dict:
    """
    Get the current weather and a 3-day forecast for a town or city.
    Leave place empty to use sir's home city. Temperatures are in Celsius.

    Args:
        place: A town or city, optionally with its country, e.g. "Paris" or "Leeds, UK".
    """
    place = place.strip() or os.getenv("EVE_HOME_CITY", "").strip()
    if not place:
        return {"error": "No place given, and EVE_HOME_CITY isn't set in .env"}

    location = _find_place(place)
    if location is None:
        return {"error": f"Couldn't find a place called {place}"}

    forecast = httpx.get(FORECAST_URL, timeout=TIMEOUT, params={
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",       # times in that place's own time zone
        "forecast_days": 3,
        "wind_speed_unit": "mph",
    })
    forecast.raise_for_status()   # turn an HTTP error (e.g. 500) into a Python error
    data = forecast.json()
    now, daily = data["current"], data["daily"]

    return {
        "place": f"{location['name']}, {location.get('country', '')}".strip(", "),
        "now": {
            "conditions": WEATHER_WORDS.get(now["weather_code"], "unknown"),
            "temperature_c": now["temperature_2m"],
            "feels_like_c": now["apparent_temperature"],
            "humidity_percent": now["relative_humidity_2m"],
            "rain_mm": now["precipitation"],
            "wind_mph": now["wind_speed_10m"],
        },
        "next_days": [
            {
                "date": daily["time"][i],
                "conditions": WEATHER_WORDS.get(daily["weather_code"][i], "unknown"),
                "high_c": daily["temperature_2m_max"][i],
                "low_c": daily["temperature_2m_min"][i],
                "chance_of_rain_percent": daily["precipitation_probability_max"][i],
            }
            for i in range(len(daily["time"]))
        ],
    }


def _find_place(place: str) -> dict | None:
    """
    Turn "Leeds, UK" into Open-Meteo's details for Leeds (including its
    coordinates). Returns None if nothing matches.
    """
    # The search only understands the place name, so split off the country...
    name, _, country = (part.strip() for part in place.partition(","))
    response = httpx.get(GEOCODE_URL, timeout=TIMEOUT,
                         params={"name": name, "count": 10, "language": "en"})
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        return None
    # ...then use it to pick the right one (there are lots of Londons in the world).
    if country:
        wanted = country.lower().replace("uk", "united kingdom").replace("usa", "united states")
        for result in results:
            names = (result.get("country", "").lower(), result.get("country_code", "").lower())
            if wanted in names or country.lower() in names:
                return result
    return results[0]   # otherwise the biggest / best-known match
