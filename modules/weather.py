"""
weather.py — Live weather for Newcastle, Australia.

Primary:   OpenWeatherMap API  (needs OPENWEATHER_API_KEY)
Fallback:  wttr.in             (free, no key needed)
"""

import logging
import os

import requests

logger = logging.getLogger("JARVIS.Weather")

# Default location — can be overridden in .env
DEFAULT_CITY    = "Newcastle"
DEFAULT_COUNTRY = "AU"

# OpenWeatherMap free endpoint
OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

# wttr.in fallback (returns JSON, no key)
WTTR_URL = "https://wttr.in/{city}?format=j1"


class WeatherModule:
    """Fetches and narrates weather conditions."""

    def __init__(self):
        self._api_key = os.getenv("OPENWEATHER_API_KEY")
        self._city    = os.getenv("WEATHER_CITY",    DEFAULT_CITY)
        self._country = os.getenv("WEATHER_COUNTRY", DEFAULT_COUNTRY)

        if self._api_key:
            logger.info("Weather: OpenWeatherMap (%s, %s).", self._city, self._country)
        else:
            logger.info("Weather: wttr.in fallback (%s).", self._city)

    # ── Public interface ──────────────────────────────────────────────────────

    def get_weather(self) -> str:
        """Return a spoken weather briefing."""
        if self._api_key:
            data = self._fetch_owm()
        else:
            data = self._fetch_wttr()

        if data is None:
            return (
                "I'm unable to retrieve the weather at the moment, sir. "
                "Please check your internet connection or API key."
            )

        return self._format(data)

    # ── OpenWeatherMap ────────────────────────────────────────────────────────

    def _fetch_owm(self) -> dict | None:
        try:
            resp = requests.get(
                OWM_URL,
                params={
                    "q":     f"{self._city},{self._country}",
                    "appid": self._api_key,
                    "units": "metric",
                },
                timeout=10,
            )
            resp.raise_for_status()
            j = resp.json()

            return {
                "city":        j["name"],
                "country":     j["sys"]["country"],
                "temp":        round(j["main"]["temp"]),
                "feels_like":  round(j["main"]["feels_like"]),
                "humidity":    j["main"]["humidity"],
                "description": j["weather"][0]["description"].capitalize(),
                "wind_speed":  round(j["wind"]["speed"] * 3.6),  # m/s → km/h
                "source":      "owm",
            }
        except requests.exceptions.HTTPError as exc:
            if exc.response.status_code == 401:
                logger.error("OpenWeatherMap: invalid API key.")
            else:
                logger.error("OpenWeatherMap HTTP error: %s", exc)
            return None
        except Exception as exc:
            logger.error("OpenWeatherMap fetch error: %s", exc)
            return None

    # ── wttr.in fallback ──────────────────────────────────────────────────────

    def _fetch_wttr(self) -> dict | None:
        try:
            url = WTTR_URL.format(city=f"{self._city}+{self._country}")
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            j    = resp.json()
            cur  = j["current_condition"][0]
            area = j["nearest_area"][0]

            city_name = area["areaName"][0]["value"]
            country   = area["country"][0]["value"]

            return {
                "city":        city_name,
                "country":     country,
                "temp":        int(cur["temp_C"]),
                "feels_like":  int(cur["FeelsLikeC"]),
                "humidity":    int(cur["humidity"]),
                "description": cur["weatherDesc"][0]["value"],
                "wind_speed":  int(cur["windspeedKmph"]),
                "source":      "wttr",
            }
        except Exception as exc:
            logger.error("wttr.in fetch error: %s", exc)
            return None

    # ── Formatting ────────────────────────────────────────────────────────────

    def _format(self, d: dict) -> str:
        return (
            f"Currently in {d['city']}, {d['country']}: {d['description']}, "
            f"{d['temp']} degrees Celsius, feeling like {d['feels_like']}. "
            f"Humidity is {d['humidity']} percent with winds at {d['wind_speed']} kilometres per hour."
        )
