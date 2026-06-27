import calendar
import datetime
from typing import Any, Dict

from cache import FileCache
from weather_api import fetch_current_weather, fetch_daily_forecast_16d, fetch_historical_weather_period

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


async def handle_get_historical_spb_yearly() -> Dict[str, Any]:
    """Обработчик инструмента get_historical_spb_yearly с кэшированием."""
    cache_key = cache._make_key("spb_historical")
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    today = datetime.date.today()
    start_date = today.replace(year=today.year - 1)

    end_month = today.month - 11
    end_year = today.year
    if end_month <= 0:
        end_month += 12
        end_year -= 1
    last_day = calendar.monthrange(end_year, end_month)[1]
    end_day = min(today.day, last_day)
    end_date = datetime.date(end_year, end_month, end_day)

    result = await fetch_historical_weather_period(
        SPB_LAT, SPB_LON,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )
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
    {
        "name": "get_historical_spb_yearly",
        "description": (
            "Получить историческую погоду в Санкт-Петербурге за прошедший период "
            "(год назад, окно в 1 месяц). Использует фиксированные координаты "
            "(59.93°N, 30.31°E). Период: от текущая дата минус 1 год до текущая "
            "дата минус 11 месяцев. Возвращает исторические данные по дням: "
            "дату, макс/мин температуру (°C), сумму осадков (мм), код погоды, "
            "текстовое описание на русском языке в casual-стиле, время восхода "
            "и заката."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]
