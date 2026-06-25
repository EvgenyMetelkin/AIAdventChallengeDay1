import json
from datetime import date
from typing import Any, Dict, List

from cache import TTLCache
from news_api import get_positive_articles, format_article


cache = TTLCache(max_size=100, ttl_seconds=3600)


def _build_cache_key(country: str, page_size: int) -> str:
    today = date.today().isoformat()
    return cache._make_key(country, page_size, today)


async def handle_get_positive_news(
    country: str = "ru",
    page_size: int = 20,
) -> List[Dict[str, Any]]:
    """Обработчик инструмента get_positive_news с кэшированием."""
    cache_key = _build_cache_key(country, page_size)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    raw_articles = await get_positive_articles(
        country=country,
        page_size=page_size,
    )

    articles = [format_article(a) for a in raw_articles]

    result = {
        "totalResults": len(articles),
        "articles": articles,
    }

    cache.set(cache_key, result)
    return result


TOOL_SCHEMA = {
    "name": "get_positive_news",
    "description": (
        "Fetch positive and uplifting news headlines. "
        "Searches across entertainment, science, and health categories, "
        "filtering articles by positive keywords (e.g. 'happy', 'breakthrough', "
        "'success', 'hope', 'kindness'). Results are cached for 1 hour."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "country": {
                "type": "string",
                "description": "ISO 3166-1 country code (e.g. 'ru' for Russia, 'us' for USA, 'gb' for UK). Default: 'ru'",
                "default": "ru",
            },
            "pageSize": {
                "type": "integer",
                "description": "Maximum number of articles to return (1-100). Default: 20",
                "minimum": 1,
                "maximum": 100,
                "default": 20,
            },
        },
        "required": [],
    },
}
