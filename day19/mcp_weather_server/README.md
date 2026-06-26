# MCP Weather Server

MCP-сервер (Model Context Protocol) для получения текущей погоды через публичное API Open-Meteo. Предоставляет JSON-RPC поверх HTTP, SSE-транспорт, файловое кэширование (5 мин) и опциональную аутентификацию.

## Инструменты

| Инструмент | Параметры | Описание |
|---|---|---|
| `get_weather_spb` | — | Погода в Санкт-Петербурге (59.93°N, 30.31°E) на сегодня |
| `get_weather_by_coordinates` | `latitude` (float), `longitude` (float) | Погода по координатам на сегодня |

Данные: Open-Meteo (бесплатно, без ключа). Возвращает температуру (°C), вероятность осадков (%) и casual-описание на русском.

## Разработка (локально)

```bash
cd day19/mcp_weather_server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload --host 0.0.0.0 --port 9001
```

Порт можно переопределить: `MCP_WEATHER_PORT=9002 uvicorn server:app ...`

## Деплой на Ubuntu-сервер

### Одноразовый деплой (sudo ./deploy.sh)

Скрипт делает **всё**: установит зависимости, создаст systemd-сервис, настроит nginx, сгенерирует API-ключ.

```bash
# 1. Копируем файлы на сервер
scp -r mcp_weather_server/ user@178.253.39.45:/tmp/

# 2. Запускаем деплой
ssh user@178.253.39.45
sudo SERVER_IP=178.253.39.45 bash /tmp/mcp_weather_server/deploy.sh
```

Что спросит скрипт:
- **Domain name** — если есть домен, введёте его, и скрипт сам настроит HTTPS через Let's Encrypt. Если нет — нажмите Enter, будет HTTP на порту 80.
- Если домен **не указан**, сервер будет доступен по `http://178.253.39.45/` (nginx на порту 80 проксирует на 9001).

### Переменные окружения (можно задать перед запуском деплоя)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `SERVER_IP` | `178.253.39.45` | Публичный IP для отображения в итоговом URL |
| `MCP_AUTH_KEY` | генерируется автоматически | Ключ для заголовка `X-API-Key` |
| `MCP_WEATHER_PORT` | `9001` | Порт uvicorn |

### Что создаётся на сервере

| Компонент | Путь |
|---|---|
| Исходники и venv | `/opt/mcp_weather_server/` |
| Systemd-сервис | `/etc/systemd/system/mcp-weather-server.service` |
| Nginx rate-limit | `/etc/nginx/conf.d/mcp-weather-rate-limit.conf` |
| Nginx сайт (без домена) | `/etc/nginx/sites-available/mcp-weather.conf` |

### Повторный деплой

Скрипт идемпотентен — можно запускать повторно. Пересоздаст systemd-юнит и nginx-конфиги, но **сохранит** `.env` и `venv`.

Для обновления только кода — просто скопируйте новые файлы:

```bash
scp server.py handlers.py weather_api.py cache.py user@178.253.39.45:/opt/mcp_weather_server/
ssh user@178.253.39.45 sudo systemctl restart mcp-weather-server
```

## Управление сервисом на сервере

```bash
# Статус
sudo systemctl status mcp-weather-server

# Перезапуск (после обновления кода)
sudo systemctl restart mcp-weather-server

# Логи (реального времени)
sudo journalctl -u mcp-weather-server -f

# Логи за последний час
sudo journalctl -u mcp-weather-server --since "1 hour ago"

# Остановка / запуск
sudo systemctl stop mcp-weather-server
sudo systemctl start mcp-weather-server

# Отключить автозапуск при старте системы
sudo systemctl disable mcp-weather-server
```

## Тестирование JSON-RPC

### Health check (без аутентификации)

```bash
curl http://178.253.39.45/health
# → {"status":"ok","server":"mcp-weather-server","version":"1.0.0"}
```

### Список инструментов

```bash
curl -s -X POST http://178.253.39.45/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <ваш-ключ>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Вызов инструмента

```bash
# Погода в СПб
curl -s -X POST http://178.253.39.45/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <ваш-ключ>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_weather_spb","arguments":{}}}'

# Погода по координатам (Москва)
curl -s -X POST http://178.253.39.45/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <ваш-ключ>" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_weather_by_coordinates","arguments":{"latitude":55.75,"longitude":37.62}}}'
```

## Конфигурация MCP-клиента

Пример `mcp_config.json`:

```json
{
  "server_url": "http://178.253.39.45/",
  "transport": "streamable_http"
}
```

Если задан `MCP_AUTH_KEY`, добавьте заголовок:
```json
{
  "server_url": "http://178.253.39.45/",
  "transport": "streamable_http",
  "env": {
    "HEADERS": {
      "X-API-Key": "<ваш-ключ>"
    }
  }
}
```

## Архитектура

| Файл | Назначение |
|---|---|
| `server.py` | FastAPI-приложение, JSON-RPC диспетчер, auth middleware, эндпоинты (`/`, `/sse`, `/message`, `/health`) |
| `handlers.py` | Обработчики инструментов, `TOOLS_SCHEMA`, кэширование вызовов |
| `weather_api.py` | Клиент Open-Meteo, WMO-коды → русское описание погоды |
| `cache.py` | Файловый кэш (SHA-256 ключи, TTL 5 минут, потокобезопасный) |
| `deploy.sh` | Production-деплой на Ubuntu (systemd + nginx + certbot) |

### Эндпоинты

| Метод | Путь | Описание | Аутентификация |
|---|---|---|---|
| `POST` | `/` | Основной JSON-RPC endpoint | `X-API-Key` |
| `GET` | `/sse` | SSE-транспорт (возвращает endpoint URL) | `X-API-Key` |
| `POST` | `/message` | Альтернативный вход для SSE-сообщений | `X-API-Key` |
| `GET` | `/health` | Health check | **нет** |

### JSON-RPC методы

- `initialize` — handshake (protocolVersion, capabilities)
- `tools/list` — список инструментов
- `tools/call` — вызов инструмента

## Переменные окружения

| Переменная | Обязательность | По умолчанию | Описание |
|---|---|---|---|
| `MCP_AUTH_KEY` | опционально | — | API-ключ для `X-API-Key`. Если не задан — аутентификация отключена |
| `MCP_WEATHER_PORT` | опционально | `9001` | Порт uvicorn при локальном запуске |

## Устранение неполадок

### Сервис не стартует

```bash
sudo journalctl -u mcp-weather-server -n 50 --no-pager
```

### Nginx не может перезагрузиться после второго деплоя

Если на этом же сервере развёрнут `mcp_news_server` (day17) без домена — оба сервера используют один порт 80 без `default_server`, конфликтов быть не должно. При проблемах:

```bash
sudo nginx -t               # проверить конфиг
sudo nginx -T | grep listen # показать все listen-директивы
```

### Порт занят

```bash
sudo lsof -i :9001          # кто занял порт
```

### Очистить кэш вручную

```bash
sudo rm -rf /opt/mcp_weather_server/cache/
sudo systemctl restart mcp-weather-server
```

## Зависимости

- `fastapi` — веб-фреймворк
- `uvicorn` — ASGI-сервер
- `httpx` — асинхронный HTTP-клиент
- `python-dotenv` — загрузка `.env`

Внешние библиотеки для кэширования (`cachetools`) **не используются** — проект использует собственную реализацию файлового кэша в `cache.py`.
