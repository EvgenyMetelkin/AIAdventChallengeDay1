import os
import httpx
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

NEWS_API_BASE = "https://newsapi.org/v2"

POSITIVE_KEYWORDS = [
    "good news", "positive", "happy", "joy", "wonderful",
    "breakthrough", "success", "celebrate", "hope", "inspiring",
    "kindness", "generous", "hero", "miracle", "triumph",
    "achievement", "record", "award", "discovery", "cure",
    "rescue", "reunion", "donation", "volunteer", "community",
]

POSITIVE_CATEGORIES = ["entertainment", "science", "health"]


def _has_positive_keywords(title: str, description: Optional[str]) -> bool:
    text = (title or "").lower()
    if description:
        text += " " + description.lower()
    for kw in POSITIVE_KEYWORDS:
        if kw in text:
            return True
    return False


def _is_today(published_at: Optional[str]) -> bool:
    if not published_at:
        return False
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        return dt.date() == date.today()
    except (ValueError, TypeError):
        return False


async def fetch_top_headlines(
    country: str,
    category: Optional[str] = None,
    page_size: int = 100,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Получает топ-заголовки из NewsAPI для указанной страны и категории."""
    key = api_key or os.getenv("NEWS_API_KEY")
    if not key:
        raise ValueError("NEWS_API_KEY is not set")

    params: Dict[str, Any] = {
        "apiKey": key,
        "country": country,
        "pageSize": min(page_size, 100),
    }
    if category:
        params["category"] = category

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{NEWS_API_BASE}/top-headlines", params=params)

    if resp.status_code == 401:
        raise PermissionError("NewsAPI returned 401: invalid or missing API key")
    if resp.status_code == 429:
        raise RuntimeError("NewsAPI rate limit exceeded (429). Try again later.")
    if resp.status_code != 200:
        error_msg = resp.json().get("message", resp.text)
        raise RuntimeError(f"NewsAPI error {resp.status_code}: {error_msg}")

    data = resp.json()
    return data.get("articles", [])


def filter_positive_articles(
    articles: List[Dict[str, Any]],
    page_size: int = 20,
) -> List[Dict[str, Any]]:
    """Фильтрует статьи по позитивным ключевым словам и обрезает до page_size."""
    positive = []
    for article in articles:
        title = article.get("title") or ""
        description = article.get("description")
        if _has_positive_keywords(title, description):
            positive.append(article)

    return positive[:page_size]


async def fetch_everything(
    page_size: int = 100,
    api_key: Optional[str] = None,
    language: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Поиск позитивных новостей через /v2/everything."""
    key = api_key or os.getenv("NEWS_API_KEY")
    if not key:
        raise ValueError("NEWS_API_KEY is not set")

    today_str = date.today().isoformat()
    query = " OR ".join(POSITIVE_KEYWORDS[:10])

    params: Dict[str, Any] = {
        "apiKey": key,
        "q": query,
        "from": from_date or today_str,
        "to": to_date or today_str,
        "sortBy": "publishedAt",
        "pageSize": min(page_size, 100),
    }
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{NEWS_API_BASE}/everything", params=params)

    if resp.status_code in (401, 429):
        return []
    if resp.status_code != 200:
        return []

    data = resp.json()
    return data.get("articles", [])


def country_to_language(country: str) -> str:
    lang_map = {
        "ru": "ru", "us": "en", "gb": "en", "de": "de", "fr": "fr",
        "es": "es", "it": "it", "jp": "ja", "cn": "zh", "br": "pt",
    }
    return lang_map.get(country.lower(), "en")


async def _collect_from_everything(
    needed: int,
    seen_urls: set,
    api_key: Optional[str],
    language: Optional[str],
    from_date: str,
    to_date: str,
) -> List[Dict[str, Any]]:
    """Вызывает fetch_everything и дедуплицирует позитивные статьи."""
    raw = await fetch_everything(
        page_size=needed,
        api_key=api_key,
        language=language,
        from_date=from_date,
        to_date=to_date,
    )
    collected: List[Dict[str, Any]] = []
    for article in raw:
        url = article.get("url", "")
        if not url or url in seen_urls:
            continue
        if not _has_positive_keywords(
            article.get("title") or "", article.get("description")
        ):
            continue
        seen_urls.add(url)
        collected.append(article)
    return collected


async def get_positive_articles(
    country: str = "ru",
    page_size: int = 20,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Собирает статьи из позитивных категорий за сегодня и фильтрует."""
    categories = POSITIVE_CATEGORIES

    all_articles: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for cat in categories:
        articles = await fetch_top_headlines(
            country=country,
            category=cat,
            page_size=100,
            api_key=api_key,
        )
        for article in articles:
            if not _is_today(article.get("publishedAt")):
                continue
            url = article.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_articles.append(article)

    result = filter_positive_articles(all_articles, page_size)
    seen_urls_pos = {a.get("url", "") for a in result}

    needed = page_size - len(result)
    if needed > 0:
        today_str = date.today().isoformat()
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        lang = country_to_language(country)

        extra = await _collect_from_everything(
            needed, seen_urls_pos, api_key, lang, today_str, today_str,
        )
        result.extend(extra)

        needed = page_size - len(result)
        if needed > 0:
            extra = await _collect_from_everything(
                needed, seen_urls_pos, api_key, None, today_str, today_str,
            )
            result.extend(extra)

        needed = page_size - len(result)
        if needed > 0:
            extra = await _collect_from_everything(
                needed, seen_urls_pos, api_key, None, week_ago, today_str,
            )
            result.extend(extra)

        result = result[:page_size]

    return result


def format_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """Форматирует одну статью в выходной формат."""
    title = article.get("title") or "No title"
    description = article.get("description") or ""
    content = article.get("content") or ""

    if description:
        summary = description
    elif content:
        summary = content[:500] + ("..." if len(content) > 500 else "")
    else:
        summary = title[:500]

    return {
        "title": title,
        "description": description,
        "summary": summary,
        "url": article.get("url", ""),
        "publishedAt": article.get("publishedAt", ""),
        "positive_score": True,
    }
