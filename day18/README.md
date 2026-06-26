# weather_scheduler

MCP-сервер для управления отложенными и периодическими запросами к mcp_weather_server.

## Запуск

```bash
cd day18
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Скопируйте .env.example в .env и настройте переменные
cp .env.example .env

# Запуск
uvicorn server:app --reload --host 0.0.0.0 --port 9002
```

## Переменные окружения (.env)

| Переменная | По умолчанию | Описание |
|---|---|---|
| MCP_WEATHER_HOST | localhost | Хост погодного сервера |
| MCP_WEATHER_PORT | 9001 | Порт погодного сервера |
| MCP_AUTH_KEY | (пусто) | Ключ аутентификации погодного сервера |
| MCP_SCHEDULER_PORT | 9002 | Порт weather_scheduler |
| DATA_RETENTION_HOURS | 24 | Срок хранения данных (часов) |
| WEATHER_CLIENT_TIMEOUT | 30 | Таймаут запроса к погодному серверу (сек) |

## API (JSON-RPC)

Единый endpoint: `POST /`

### Инструменты

| Инструмент | Описание |
|---|---|
| `schedule_job` | Однократная задача на получение погоды |
| `repeat_job` | Периодическая задача (интервал >= 60с) |
| `cancel_job` | Отмена задачи по ID |
| `actual_jobs` | Список активных задач |
| `export_jobs_to_file` | Экспорт всех задач в JSON-файл |

### MCP-методы

| Метод | Описание |
|---|---|
| `initialize` | Инициализация соединения |
| `tools/list` | Список инструментов |
| `tools/call` | Вызов инструмента |

## Health check

```
GET /health → {"status": "ok"}
```

## Деплой на сервер

### Копирование файлов (без venv)

```bash
# Переменные — замени на свои
SERVER_IP=178.253.39.45
SERVER_DIR=/opt/weather_scheduler

# Создать директорию на сервере
ssh root@$SERVER_IP mkdir -p $SERVER_DIR

# Скопировать исходные файлы
scp server.py         root@$SERVER_IP:$SERVER_DIR/
scp handlers.py       root@$SERVER_IP:$SERVER_DIR/
scp scheduler.py      root@$SERVER_IP:$SERVER_DIR/
scp storage.py        root@$SERVER_IP:$SERVER_DIR/
scp weather_client.py root@$SERVER_IP:$SERVER_DIR/
scp requirements.txt  root@$SERVER_IP:$SERVER_DIR/
scp .env.example      root@$SERVER_IP:$SERVER_DIR/
scp deploy.sh         root@$SERVER_IP:$SERVER_DIR/
```

### Вариант А — скриптом deploy.sh (рекомендуется)

```bash
ssh root@$SERVER_IP
cd $SERVER_DIR
chmod +x deploy.sh
./deploy.sh
```

Скрипт автоматически: установит системные зависимости, создаст venv, настроит .env, пропишет systemd-сервис и nginx.

### Вариант Б — ручной запуск

```bash
ssh root@$SERVER_IP
cd $SERVER_DIR

# Настройка .env
cp .env.example .env
nano .env   # укажи MCP_WEATHER_HOST, MCP_AUTH_KEY и т.д.

# Установка зависимостей
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Запуск
uvicorn server:app --host 0.0.0.0 --port 9002
```

### Проверка после деплоя

```bash
curl http://$SERVER_IP:9002/health
# → {"status":"ok","server":"mcp-weather-scheduler","version":"1.0.0"}
```
