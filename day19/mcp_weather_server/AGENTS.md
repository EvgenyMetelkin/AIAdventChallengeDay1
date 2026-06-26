# AGENTS.md

## Location
Все исходники в поддиректории `mcp_weather_server/`. Рабочий каталог — `day19/mcp_weather_server/`.

## Запуск
```bash
cd mcp_weather_server
pip install -r requirements.txt
uvicorn server:app --reload --host 0.0.0.0 --port 9001
```
Порт можно переопределить через `MCP_WEATHER_PORT`.

## Переменные окружения (`mcp_weather_server/.env`)
- `MCP_AUTH_KEY` — опционален. Если задан, все запросы (кроме `/health`) требуют заголовок `X-API-Key`.
- `MCP_WEATHER_PORT` — опционален (по умолчанию `9001`).

## Архитектура
Это **MCP-сервер** (Model Context Protocol) с JSON-RPC поверх HTTP, **не** обычный REST API:
- Единственный JSON-RPC endpoint: `POST /`
- Два инструмента: `get_weather_by_coordinates` (latitude + longitude) и `get_weather_spb` (без параметров)
- SSE-транспорт: `GET /sse`, `POST /message`
- Health check: `GET /health`
- Данные погоды: публичное API Open-Meteo (бесплатно, без ключа)

### Файлы
- `server.py` — FastAPI-приложение, JSON-RPC диспетчер, middleware аутентификации
- `handlers.py` — кэширующие обработчики инструментов, схема `TOOLS_SCHEMA`
- `weather_api.py` — клиент Open-Meteo, таблица WMO-кодов → casual-описание на русском
- `cache.py` — файловый кэш (SHA-256 ключи, TTL 5 минут, потокобезопасный, `./cache/*.json`)
- `deploy.sh` — production-деплой на Ubuntu (systemd + nginx + certbot), **не для разработки**

## Зависимости
Внешние библиотеки для кэширования не используются — проект использует собственную реализацию файлового кэша в `cache.py`.

## Тесты
Тестов нет.
