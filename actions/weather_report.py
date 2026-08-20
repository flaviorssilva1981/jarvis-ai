from __future__ import annotations

import webbrowser
from typing import Optional
from urllib.parse import quote_plus

import requests

_CITY_ALIASES = {
    "san paulo": "São Paulo",
    "sao paulo": "São Paulo",
    "san paulo brazil": "São Paulo, Brazil",
    "sao paulo brazil": "São Paulo, Brazil",
    "sp": "São Paulo",
}

_WMO: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    80: "rain showers",
    81: "rain showers",
    82: "heavy rain showers",
    95: "thunderstorm",
}


def _normalize_city(city: str) -> str:
    raw = city.strip()
    key = raw.lower()
    return _CITY_ALIASES.get(key, raw)


def _describe(code: int) -> str:
    return _WMO.get(code, "mixed conditions")


def _geocode(city: str) -> tuple[float, float, str]:
    resp = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or []
    if not results:
        raise ValueError(f"City not found: {city}")
    hit = results[0]
    label = ", ".join(
        x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x
    )
    return float(hit["latitude"]), float(hit["longitude"]), label


def _fetch_forecast(lat: float, lon: float, days: int = 4) -> dict:
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": days,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _format_forecast(label: str, data: dict) -> str:
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []

    temp = cur.get("temperature_2m")
    humidity = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")
    now_code = cur.get("weather_code", 0)

    lines = [f"Weather for {label}:"]
    if temp is not None:
        lines.append(
            f"Now: {round(temp)}°C, {_describe(int(now_code))}"
            + (f", humidity {round(humidity)}%" if humidity is not None else "")
            + (f", wind {round(wind)} km/h" if wind is not None else "")
            + "."
        )

    day_labels = ("Today", "Tomorrow", "Day after tomorrow")
    for i, date_str in enumerate(dates[:4]):
        if i >= len(highs) or i >= len(lows):
            break
        hi, lo = round(highs[i]), round(lows[i])
        cond = _describe(int(codes[i])) if i < len(codes) else "mixed conditions"
        name = day_labels[i] if i < len(day_labels) else date_str
        lines.append(f"{name}: high {hi}°C, low {lo}°C, {cond}.")

    return "\n".join(lines)


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    city = parameters.get("city")
    when = (parameters.get("time") or parameters.get("when") or "today").strip()
    open_browser = bool(parameters.get("open_browser", False))
    days = 4 if "3 day" in when.lower() or "next" in when.lower() else 4

    if not city or not isinstance(city, str) or not city.strip():
        msg = "Sir, the city is missing for the weather report."
        _log(msg, player)
        return msg

    city = _normalize_city(city)

    try:
        lat, lon, label = _geocode(city)
        forecast = _fetch_forecast(lat, lon, days=days)
        msg = _format_forecast(label, forecast)
    except Exception as e:
        print(f"[Weather] ⚠️ API failed ({e}) — trying web search fallback")
        try:
            from actions.web_search import web_search as _search
            msg = _search({
                "query": f"weather forecast {city} today and next 3 days",
                "mode": "research",
            })
        except Exception as e2:
            msg = f"Sir, I could not fetch weather for {city}: {e2}"

    if open_browser:
        search_query = f"weather in {city} {when}"
        url = f"https://www.google.com/search?q={quote_plus(search_query)}"
        try:
            webbrowser.open(url)
            msg += "\n(Also opened the forecast in your browser.)"
        except Exception as e:
            msg += f"\n(Could not open browser: {e})"

    _log(msg.split("\n")[0], player)

    if session_memory:
        try:
            session_memory.set_last_search(query=f"weather {city}", response=msg)
        except Exception:
            pass

    return msg


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass
