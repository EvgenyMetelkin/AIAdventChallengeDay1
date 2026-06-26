"""MCP Weather Scheduler — JSON-RPC сервер управления задачами погоды."""

import json
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response

from handlers import (
    TOOLS_SCHEMA,
    handle_schedule_job,
    handle_repeat_job,
    handle_cancel_job,
    handle_actual_jobs,
    handle_export_jobs_to_file,
)
from scheduler import SchedulerManager

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("weather_scheduler.server")

app = FastAPI(title="MCP Weather Scheduler", version="1.0.0")

SERVER_NAME = "mcp-weather-scheduler"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

# Инициализация менеджера планировщика
scheduler_manager = SchedulerManager(
    weather_host=os.getenv("MCP_WEATHER_HOST", "localhost"),
    weather_port=int(os.getenv("MCP_WEATHER_PORT", "9001")),
    weather_auth_key=os.getenv("MCP_AUTH_KEY", "") or None,
    retention_hours=int(os.getenv("DATA_RETENTION_HOURS", "24")),
    weather_client_timeout=int(os.getenv("WEATHER_CLIENT_TIMEOUT", "30")),
)

# Восстанавливаем сохранённые задачи при старте
scheduler_manager.restore_jobs()


@app.on_event("shutdown")
def shutdown_event():
    scheduler_manager.shutdown()


def _jsonrpc_ok(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_err(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def _handle_method(method: str, params: dict, request_id: Any) -> Optional[dict]:
    """Диспетчер JSON-RPC методов."""
    if method == "initialize":
        return _jsonrpc_ok(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {}},
        })

    elif method == "tools/list":
        return _jsonrpc_ok(request_id, {"tools": TOOLS_SCHEMA})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler_map = {
            "schedule_job": handle_schedule_job,
            "repeat_job": handle_repeat_job,
            "cancel_job": handle_cancel_job,
            "actual_jobs": handle_actual_jobs,
            "export_jobs_to_file": handle_export_jobs_to_file,
        }

        if tool_name not in handler_map:
            return _jsonrpc_err(request_id, -32601, f"Unknown tool: {tool_name}")

        handler = handler_map[tool_name]
        try:
            result = handler(scheduler_manager, arguments)
            text_content = json.dumps(result, ensure_ascii=False, indent=2)
            return _jsonrpc_ok(request_id, {
                "content": [{"type": "text", "text": text_content}],
                "isError": False,
            })
        except ValueError as e:
            logger.warning(f"Ошибка валидации в {tool_name}: {e}")
            return _jsonrpc_err(request_id, -32602, f"Invalid params: {e}")
        except Exception as e:
            logger.exception(f"Ошибка в {tool_name}")
            return _jsonrpc_err(request_id, -32000, str(e))

    elif method == "resources/list":
        return _jsonrpc_ok(request_id, {"resources": []})

    elif method == "resources/templates/list":
        return _jsonrpc_ok(request_id, {"resourceTemplates": []})

    elif method == "resources/read":
        return _jsonrpc_err(request_id, -32601, "No resources available")

    else:
        return _jsonrpc_err(request_id, -32601, f"Method not found: {method}")


@app.post("/")
async def jsonrpc_endpoint(request: Request):
    """Основная точка входа JSON-RPC."""
    try:
        body = await request.json()
    except Exception:
        return Response(
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }),
            media_type="application/json",
            status_code=400,
        )

    method = body.get("method", "")
    params = body.get("params", {})
    request_id = body.get("id")

    if not method:
        return Response(
            content=json.dumps(_jsonrpc_err(request_id, -32600, "Invalid Request: missing method")),
            media_type="application/json",
            status_code=400,
        )

    result = await _handle_method(method, params, request_id)

    return Response(
        content=json.dumps(result, ensure_ascii=False),
        media_type="application/json",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("MCP_SCHEDULER_PORT", "9002"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
