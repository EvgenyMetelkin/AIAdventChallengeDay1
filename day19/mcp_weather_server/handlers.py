from typing import Any, Dict

from cache import FileCache
from weather_api import fetch_current_weather, fetch_daily_forecast_16d

# Файловый кэш с TTL 5 минут
cache = FileCache(cache_dir="./cache", ttl_seconds=300)

# Фиксированные координаты Санкт-Петербурга
SPB_LAT = 59.93
SPB_LON = 30.31


async def handle_get_weather_by_coordinates(
    latitude: float,
    longitude: float,
) -> Dict[str, Any]:
    """Обработчик инструмента get_weather_by_coordinates с кэшированием."""
    cache_key = cache._make_key("coords", latitude, longitude)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = await fetch_current_weather(latitude, longitude)
    cache.set(cache_key, result)
    return result


async def handle_get_weather_spb() -> Dict[str, Any]:
    """Обработчик инструмента get_weather_spb с кэшированием."""
    cache_key = cache._make_key("spb")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = await fetch_current_weather(SPB_LAT, SPB_LON)
    cache.set(cache_key, result)
    return result


async def handle_get_forecast_spb_16d() -> Dict[str, Any]:
    """Обработчик инструмента get_forecast_spb_16d с кэшированием."""
    cache_key = cache._make_key("spb_16d")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = await fetch_daily_forecast_16d(SPB_LAT, SPB_LON)
    cache.set(cache_key, result)
    return result


TOOLS_SCHEMA = [
    {
        "name": "get_weather_by_coordinates",
        "description": (
            "Получить текущую погоду на сегодня по координатам. "
            "Возвращает температуру (°C), вероятность осадков (%) и "
            "текстовое описание на русском языке в casual-стиле."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Широта (число с плавающей точкой), например 59.93",
                },
                "longitude": {
                    "type": "number",
                    "description": "Долгота (число с плавающей точкой), например 30.31",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_weather_spb",
        "description": (
            "Получить текущую погоду в Санкт-Петербурге на сегодня. "
            "Использует фиксированные координаты (59.93°N, 30.31°E). "
            "Возвращает температуру (°C), вероятность осадков (%) и "
            "текстовое описание на русском языке в casual-стиле."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_forecast_spb_16d",
        "description": (
            "Получить прогноз погоды в Санкт-Петербурге на 16 дней. "
            "Использует фиксированные координаты (59.93°N, 30.31°E). "
            "Возвращает прогноз по дням: дату, макс/мин температуру (°C), "
            "вероятность осадков (%), код погоды, текстовое описание на русском "
            "языке в casual-стиле, время восхода и заката."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
