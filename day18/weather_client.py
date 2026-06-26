import json
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("weather_scheduler.weather_client")

DEFAULT_TIMEOUT = 30


def call_weather_tool(
    tool_name: str,
    params: Dict[str, Any],
    host: str = "localhost",
    port: int = 9001,
    auth_key: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    """Вызывает инструмент mcp_weather_server через HTTP JSON-RPC.

    Возвращает результат выполнения (поле result из ответа).
    В случае ошибки выбрасывает исключение с описанием.
    """
    url = f"http://{host}:{port}/"

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params,
        },
        "id": 1,
    }

    headers = {"Content-Type": "application/json"}
    if auth_key:
        headers["X-API-Key"] = auth_key

    logger.info(f"Calling weather tool '{tool_name}' at {host}:{port}")

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Таймаут при запросе к погодному серверу ({timeout}с)")
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Ошибка соединения с погодным сервером: {e}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ошибка запроса к погодному серверу: {e}")

    if resp.status_code != 200:
        body = resp.text[:500]
        raise RuntimeError(f"Погодный сервер вернул HTTP {resp.status_code}: {body}")

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Некорректный JSON в ответе погодного сервера: {e}")

    # Проверяем JSON-RPC ошибку
    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err))
        raise RuntimeError(f"JSON-RPC ошибка погодного сервера: {msg}")

    rpc_result = data.get("result", {})
    if rpc_result.get("isError"):
        content = rpc_result.get("content", [])
        text = content[0].get("text", str(content)) if content else str(rpc_result)
        raise RuntimeError(f"Ошибка выполнения инструмента погоды: {text}")

    return rpc_result
