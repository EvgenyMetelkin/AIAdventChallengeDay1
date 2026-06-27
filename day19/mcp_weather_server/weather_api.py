from typing import Any, Dict

import httpx

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_API_BASE = "https://archive-api.open-meteo.com/v1/archive"

# Таблица соответствия WMO-кодов погоды текстовому описанию на русском
WEATHER_DESCRIPTIONS: Dict[int, str] = {
    0: "ясно",
    1: "малооблачно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "туман с инеем",
    51: "лёгкая морось",
    53: "морось",
    55: "сильная морось",
    56: "лёгкая ледяная морось",
    57: "ледяная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "лёгкий ледяной дождь",
    67: "ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежная крупа",
    80: "небольшой ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "небольшой снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с мелким градом",
    99: "гроза с крупным градом",
}


def _describe_weather(code: int, temp: float, precip_pct: int) -> str:
    """Формирует casual-описание погоды на русском языке."""
    desc = WEATHER_DESCRIPTIONS.get(code, "неизвестная погода")

    precip = ""
    if precip_pct >= 70:
        precip = ", не забудь зонт!"
    elif precip_pct >= 30:
        precip = ", возможны осадки"
    elif precip_pct <= 10:
        precip = ", осадков не ожидается"
    else:
        precip = f", вероятность осадков {precip_pct}%"

    if 71 <= code <= 77 or 85 <= code <= 86:
        if precip_pct <= 10:
            precip = ", снега не ожидается"
        elif precip_pct < 50:
            precip = ", возможен снег"
        else:
            precip = ", одевайся теплее!"

    temp_sign = "+" if temp >= 0 else ""
    return f"{desc.capitalize()}, {temp_sign}{temp}°C{precip}."


async def fetch_current_weather(lat: float, lon: float) -> Dict[str, Any]:
    """Запрашивает текущую погоду из Open-Meteo API и возвращает словарь."""
    params: Dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m",
            "precipitation_probability",
            "weather_code",
        ]),
        "timezone": "auto",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(OPEN_METEO_BASE, params=params)

    if resp.status_code != 200:
        try:
            error_data = resp.json()
            reason = error_data.get("reason", resp.text)
        except Exception:
            reason = resp.text
        raise RuntimeError(f"Open-Meteo API error {resp.status_code}: {reason}")

    data = resp.json()

    current = data.get("current", {})
    if not current:
        raise RuntimeError("Open-Meteo API вернул пустой ответ для current")

    temperature = current.get("temperature_2m")
    precip_pct = current.get("precipitation_probability")
    weather_code = current.get("weather_code")

    if temperature is None:
        raise RuntimeError("Open-Meteo API не вернул температуру")

    temperature = float(temperature)
    precip_pct = int(precip_pct) if precip_pct is not None else 0
    weather_code = int(weather_code) if weather_code is not None else 0

    description = _describe_weather(weather_code, temperature, precip_pct)

    return {
        "temperature": temperature,
        "precipitation_probability": precip_pct,
        "description": description,
    }


def _describe_daily(code: int, temp_min: float, temp_max: float, precip_pct: int) -> str:
    """Формирует casual-описание дневной погоды на русском языке."""
    desc = WEATHER_DESCRIPTIONS.get(code, "неизвестная погода")

    precip = ""
    if precip_pct >= 70:
        precip = ", не забудь зонт!"
    elif precip_pct >= 30:
        precip = ", возможны осадки"
    elif precip_pct <= 10:
        precip = ", осадков не ожидается"
    else:
        precip = f", вероятность осадков {precip_pct}%"

    if 71 <= code <= 77 or 85 <= code <= 86:
        if precip_pct <= 10:
            precip = ", снега не ожидается"
        elif precip_pct < 50:
            precip = ", возможен снег"
        else:
            precip = ", одевайся теплее!"

    sign_min = "+" if temp_min >= 0 else ""
    sign_max = "+" if temp_max >= 0 else ""
    return f"{desc.capitalize()}, {sign_min}{temp_min}..{sign_max}{temp_max}°C{precip}."


def _describe_historical_daily(code: int, temp_min: float, temp_max: float, precip_sum: float) -> str:
    """Формирует casual-описание исторической погоды на русском языке."""
    desc = WEATHER_DESCRIPTIONS.get(code, "неизвестная погода")

    precip = ""
    if precip_sum >= 5.0:
        precip = ", были сильные осадки"
    elif precip_sum > 0:
        precip = ", были осадки"
    else:
        precip = ", без осадков"

    if 71 <= code <= 77 or 85 <= code <= 86:
        if precip_sum <= 0:
            precip = ", снега не было"
        elif precip_sum < 3.0:
            precip = ", был небольшой снег"
        else:
            precip = ", был сильный снегопад"

    sign_min = "+" if temp_min >= 0 else ""
    sign_max = "+" if temp_max >= 0 else ""
    return f"{desc.capitalize()}, {sign_min}{temp_min}..{sign_max}{temp_max}°C{precip}."


async def fetch_historical_weather_period(
    lat: float, lon: float, start_date: str, end_date: str
) -> Dict[str, Any]:
    """Запрашивает историческую погоду из Open-Meteo Archive API и возвращает словарь."""
    params: Dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "weather_code",
            "sunrise",
            "sunset",
        ]),
        "timezone": "auto",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(HISTORICAL_API_BASE, params=params)

    if resp.status_code != 200:
        try:
            error_data = resp.json()
            reason = error_data.get("reason", resp.text)
        except Exception:
            reason = resp.text
        raise RuntimeError(f"Open-Meteo Archive API error {resp.status_code}: {reason}")

    data = resp.json()

    daily = data.get("daily", {})
    if not daily:
        raise RuntimeError("Open-Meteo Archive API вернул пустой ответ для daily")

    time_list = daily.get("time", [])
    temp_max_list = daily.get("temperature_2m_max", [])
    temp_min_list = daily.get("temperature_2m_min", [])
    precip_list = daily.get("precipitation_sum", [])
    code_list = daily.get("weather_code", [])
    sunrise_list = daily.get("sunrise", [])
    sunset_list = daily.get("sunset", [])

    if not time_list:
        raise RuntimeError("Open-Meteo Archive API не вернул временные метки daily")

    forecast = []
    for i, date_str in enumerate(time_list):
        temp_max = float(temp_max_list[i]) if i < len(temp_max_list) and temp_max_list[i] is not None else 0.0
        temp_min = float(temp_min_list[i]) if i < len(temp_min_list) and temp_min_list[i] is not None else 0.0
        precip_sum = float(precip_list[i]) if i < len(precip_list) and precip_list[i] is not None else 0.0
        weather_code = int(code_list[i]) if i < len(code_list) and code_list[i] is not None else 0
        sunrise = sunrise_list[i] if i < len(sunrise_list) else None
        sunset = sunset_list[i] if i < len(sunset_list) else None

        description = _describe_historical_daily(weather_code, temp_min, temp_max, precip_sum)

        forecast.append({
            "date": date_str,
            "temperature_max": temp_max,
            "temperature_min": temp_min,
            "precipitation_sum": precip_sum,
            "weather_code": weather_code,
            "description": description,
            "sunrise": sunrise,
            "sunset": sunset,
        })

    return {
        "latitude": data.get("latitude", lat),
        "longitude": data.get("longitude", lon),
        "timezone": data.get("timezone", ""),
        "forecast": forecast,
    }


async def fetch_daily_forecast_16d(lat: float, lon: float) -> Dict[str, Any]:
    """Запрашивает прогноз на 16 дней из Open-Meteo API и возвращает словарь."""
    params: Dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "weather_code",
            "sunrise",
            "sunset",
        ]),
        "forecast_days": 16,
        "timezone": "auto",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(OPEN_METEO_BASE, params=params)

    if resp.status_code != 200:
        try:
            error_data = resp.json()
            reason = error_data.get("reason", resp.text)
        except Exception:
            reason = resp.text
        raise RuntimeError(f"Open-Meteo API error {resp.status_code}: {reason}")

    data = resp.json()

    daily = data.get("daily", {})
    if not daily:
        raise RuntimeError("Open-Meteo API вернул пустой ответ для daily")

    time_list = daily.get("time", [])
    temp_max_list = daily.get("temperature_2m_max", [])
    temp_min_list = daily.get("temperature_2m_min", [])
    precip_list = daily.get("precipitation_probability_max", [])
    code_list = daily.get("weather_code", [])
    sunrise_list = daily.get("sunrise", [])
    sunset_list = daily.get("sunset", [])

    if not time_list:
        raise RuntimeError("Open-Meteo API не вернул временные метки daily")

    forecast = []
    for i, date_str in enumerate(time_list):
        temp_max = float(temp_max_list[i]) if i < len(temp_max_list) and temp_max_list[i] is not None else 0.0
        temp_min = float(temp_min_list[i]) if i < len(temp_min_list) and temp_min_list[i] is not None else 0.0
        precip_pct = int(precip_list[i]) if i < len(precip_list) and precip_list[i] is not None else 0
        weather_code = int(code_list[i]) if i < len(code_list) and code_list[i] is not None else 0
        sunrise = sunrise_list[i] if i < len(sunrise_list) else None
        sunset = sunset_list[i] if i < len(sunset_list) else None

        description = _describe_daily(weather_code, temp_min, temp_max, precip_pct)

        forecast.append({
            "date": date_str,
            "temperature_max": temp_max,
            "temperature_min": temp_min,
            "precipitation_probability": precip_pct,
            "weather_code": weather_code,
            "description": description,
            "sunrise": sunrise,
            "sunset": sunset,
        })

    return {
        "latitude": data.get("latitude", lat),
        "longitude": data.get("longitude", lon),
        "timezone": data.get("timezone", ""),
        "forecast": forecast,
    }
