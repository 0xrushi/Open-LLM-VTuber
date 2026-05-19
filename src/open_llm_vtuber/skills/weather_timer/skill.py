from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal, TypedDict

import requests


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherResult(TypedDict):
    location: str
    temperature_f: float
    feels_like_f: float
    wind_speed_mph: float
    precipitation_in: float
    weather_code: int


LOCATION_COORDS: dict[str, tuple[float, float]] = {
    "shadyside": (40.4506, -79.9348),
    "pittsburgh": (40.4406, -79.9959),
}

LOCATION_ALIASES: dict[str, str] = {
    "pittsburg": "pittsburgh",
    "pititchburgh": "pittsburgh",
    "pitt": "pittsburgh",
}


@dataclass(frozen=True)
class UtilitySkillResolution:
    kind: Literal["weather", "timer"]
    location: str | None = None
    seconds: int | None = None


def get_weather(location: str) -> WeatherResult:
    """
    Fetch current weather from Open-Meteo.

    Args:
        location: Human-readable location key.

    Returns:
        Structured weather data.

    Raises:
        ValueError: If location is unsupported.
        requests.HTTPError: If API request fails.
    """

    normalized = location.strip().lower()
    normalized = LOCATION_ALIASES.get(normalized, normalized)

    if normalized not in LOCATION_COORDS:
        raise ValueError(f"Unsupported location: {location}")

    latitude, longitude = LOCATION_COORDS[normalized]

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": (
            "temperature_2m,"
            "apparent_temperature,"
            "precipitation,"
            "weather_code,"
            "wind_speed_10m"
        ),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/New_York",
    }

    response = requests.get(
        OPEN_METEO_URL,
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()["current"]

    return {
        "location": normalized,
        "temperature_f": data["temperature_2m"],
        "feels_like_f": data["apparent_temperature"],
        "wind_speed_mph": data["wind_speed_10m"],
        "precipitation_in": data["precipitation"],
        "weather_code": data["weather_code"],
    }


def countdown_timer(seconds: int) -> None:
    """
    Blocking countdown timer.

    Args:
        seconds: Duration in seconds.
    """

    if seconds <= 0:
        raise ValueError("seconds must be greater than 0")

    remaining = seconds

    while remaining > 0:
        mins, secs = divmod(remaining, 60)
        print(f"{mins:02d}:{secs:02d}")
        time.sleep(1)
        remaining -= 1

    print("Timer complete")


def format_weather_response(weather: WeatherResult) -> str:
    location = weather["location"].title()
    return (
        f"[neutral] [clear throat] Current weather in {location}: "
        f"{weather['temperature_f']:.0f} degrees, feels like {weather['feels_like_f']:.0f}. "
        f"Wind is {weather['wind_speed_mph']:.0f} miles per hour, "
        f"with {weather['precipitation_in']:.2f} inches of precipitation."
    )


def format_timer_set_response(seconds: int) -> str:
    return f"[joy] [chuckle] Timer set for {_format_duration(seconds)}."


def format_timer_complete_response(seconds: int) -> str:
    return f"[joy] [clear throat] Timer complete. Your {_format_duration(seconds)} timer is done."


def resolve_weather_timer_intent(text: str) -> UtilitySkillResolution | None:
    normalized = text.strip().lower()
    timer_seconds = _parse_timer_seconds(normalized)
    if timer_seconds is not None:
        return UtilitySkillResolution(kind="timer", seconds=timer_seconds)

    if re.search(r"\b(weather|temperature|forecast|outside)\b", normalized):
        return UtilitySkillResolution(kind="weather", location=_parse_location(normalized))

    return None


def _parse_location(normalized_text: str) -> str:
    for location in LOCATION_COORDS:
        if re.search(rf"(^|[^a-z0-9]){re.escape(location)}([^a-z0-9]|$)", normalized_text):
            return location
    for alias, location in LOCATION_ALIASES.items():
        if re.search(rf"(^|[^a-z0-9]){re.escape(alias)}([^a-z0-9]|$)", normalized_text):
            return location
    explicit_location = re.search(
        r"\b(?:in|for)\s+([a-z][a-z -]*?)(?:\?|\.|,|$|\s+(?:right now|today|please|now))",
        normalized_text,
    )
    if explicit_location:
        return explicit_location.group(1).strip()
    return "shadyside"


def _parse_timer_seconds(normalized_text: str) -> int | None:
    if not re.search(r"\b(timer|countdown|remind me)\b", normalized_text):
        return None

    match = re.search(
        r"\b(\d+)\s*(second|seconds|sec|secs|minute|minutes|min|mins|hour|hours|hr|hrs)\b",
        normalized_text,
    )
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        raise ValueError("seconds must be greater than 0")
    if unit in {"second", "seconds", "sec", "secs"}:
        return amount
    if unit in {"minute", "minutes", "min", "mins"}:
        return amount * 60
    if unit in {"hour", "hours", "hr", "hrs"}:
        return amount * 60 * 60
    return None


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''} and {remaining_seconds} second{'s' if remaining_seconds != 1 else ''}"


if __name__ == "__main__":
    weather = get_weather("shadyside")

    print(weather)

    countdown_timer(5)
