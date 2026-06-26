# AGENTS.md

## Location
Все исходники в поддиректории `mcp_news_server/`. Рабочий каталог — `day17/mcp_news_server/`.

## Запуск
```bash
cd mcp_news_server
pip install -r requirements.txt
uvicorn server:app --reload --host 0.0.0.0 --port 9000
```
Порт можно переопределить через `MCP_NEWS_PORT`.

## Переменные окружения (`mcp_news_server/.env`)
- `NEWS_API_KEY` — **обязателен** (ключ NewsAPI с https://newsapi.org). Без него сервер не стартует.
- `MCP_AUTH_KEY` — опционален. Если задан, все запросы (кроме `/health`) требуют заголовок `X-API-Key`.

## Архитектура
Это **MCP-сервер** (Model Context Protocol) с JSON-RPC поверх HTTP, **не** обычный REST API:
- Единственный JSON-RPC endpoint: `POST /`
- Единственный инструмент: `get_positive_news` (country + pageSize)
- SSE-транспорт: `GET /sse`, `POST /message`
- health check: `GET /health`

### Файлы
- `server.py` — FastAPI-приложение, JSON-RPC диспетчер, middleware аутентификации
- `handlers.py` — кэширующий обработчик инструмента `get_positive_news`, схема `TOOL_SCHEMA`
- `news_api.py` — клиент NewsAPI, фильтрация по позитивным ключевым словам
- `cache.py` — собственный in-memory TTLCache (потокобезопасный, SHA-256 ключи)
- `deploy.sh` — production-деплой на Ubuntu (systemd + nginx + certbot), **не для разработки**

## Зависимости
`cachetools` в `requirements.txt` **не используется** — проект использует собственную реализацию кэша в `cache.py`.

## Тесты
Тестов нет.
