from typing import Any, Dict

import httpx

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

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
