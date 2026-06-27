import json
import os
import logging
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

from handlers import (
    handle_get_weather_by_coordinates,
    handle_get_weather_spb,
    handle_get_forecast_spb_16d,
    handle_get_historical_spb_yearly,
    TOOLS_SCHEMA,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("mcp_weather_server")

app = FastAPI(title="MCP Weather Server", version="1.0.0")

MCP_AUTH_KEY = os.getenv("MCP_AUTH_KEY", "")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not MCP_AUTH_KEY or request.url.path == "/health":
        return await call_next(request)
    if request.headers.get("X-API-Key") != MCP_AUTH_KEY:
        return Response(
            content=json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "unauthorized"}}),
            media_type="application/json",
            status_code=401,
        )
    return await call_next(request)


SERVER_NAME = "mcp-weather-server"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


def _jsonrpc_ok(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_err(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def _handle_method(method: str, params: dict, request_id: Any) -> tuple[Optional[dict], Optional[dict]]:
    """Возвращает (result_dict, stream_generator). Одно из значений всегда None."""
    if method == "initialize":
        return _jsonrpc_ok(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {}},
        }), None

    elif method == "tools/list":
        return _jsonrpc_ok(request_id, {"tools": TOOLS_SCHEMA}), None

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        try:
            if tool_name == "get_weather_by_coordinates":
                lat = arguments.get("latitude")
                lon = arguments.get("longitude")
                if lat is None or lon is None:
                    error_text = json.dumps({"error": "latitude и longitude обязательны"}, ensure_ascii=False)
                    return _jsonrpc_ok(request_id, {
                        "content": [{"type": "text", "text": error_text}],
                        "isError": True,
                    }), None

                if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                    error_text = json.dumps({"error": "latitude и longitude должны быть числами"}, ensure_ascii=False)
                    return _jsonrpc_ok(request_id, {
                        "content": [{"type": "text", "text": error_text}],
                        "isError": True,
                    }), None

                logger.info(f"Calling get_weather_by_coordinates: lat={lat}, lon={lon}")
                result = await handle_get_weather_by_coordinates(latitude=float(lat), longitude=float(lon))
                text_content = json.dumps(result, ensure_ascii=False, indent=2)
                return _jsonrpc_ok(request_id, {
                    "content": [{"type": "text", "text": text_content}],
                    "isError": False,
                }), None

            elif tool_name == "get_weather_spb":
                logger.info("Calling get_weather_spb")
                result = await handle_get_weather_spb()
                text_content = json.dumps(result, ensure_ascii=False, indent=2)
                return _jsonrpc_ok(request_id, {
                    "content": [{"type": "text", "text": text_content}],
                    "isError": False,
                }), None

            elif tool_name == "get_forecast_spb_16d":
                logger.info("Calling get_forecast_spb_16d")
                result = await handle_get_forecast_spb_16d()
                text_content = json.dumps(result, ensure_ascii=False, indent=2)
                return _jsonrpc_ok(request_id, {
                    "content": [{"type": "text", "text": text_content}],
                    "isError": False,
                }), None

            elif tool_name == "get_historical_spb_yearly":
                logger.info("Calling get_historical_spb_yearly")
                result = await handle_get_historical_spb_yearly()
                text_content = json.dumps(result, ensure_ascii=False, indent=2)
                return _jsonrpc_ok(request_id, {
                    "content": [{"type": "text", "text": text_content}],
                    "isError": False,
                }), None

            else:
                return _jsonrpc_err(request_id, -32601, f"Unknown tool: {tool_name}"), None

        except Exception as e:
            logger.exception(f"Error in {tool_name}")
            error_text = json.dumps({"error": str(e)}, ensure_ascii=False)
            return _jsonrpc_ok(request_id, {
                "content": [{"type": "text", "text": error_text}],
                "isError": True,
            }), None

    elif method == "resources/list":
        return _jsonrpc_ok(request_id, {"resources": []}), None

    elif method == "resources/templates/list":
        return _jsonrpc_ok(request_id, {"resourceTemplates": []}), None

    elif method == "resources/read":
        return _jsonrpc_err(request_id, -32601, "No resources available"), None

    else:
        return _jsonrpc_err(request_id, -32601, f"Method not found: {method}"), None


@app.post("/")
async def jsonrpc_endpoint(request: Request):
    """Основная точка входа JSON-RPC (для streamable_http и sse)."""
    try:
        body = await request.json()
    except Exception:
        return Response(
            content=json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}),
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

    accept = request.headers.get("accept", "")
    use_sse = "text/event-stream" in accept

    result_dict, stream_gen = await _handle_method(method, params, request_id)

    if stream_gen is not None:
        return StreamingResponse(stream_gen, media_type="text/event-stream")

    if use_sse and result_dict is not None:
        async def sse_wrapper():
            yield f"data: {json.dumps(result_dict, ensure_ascii=False)}\n\n"
        return StreamingResponse(sse_wrapper(), media_type="text/event-stream")

    return Response(
        content=json.dumps(result_dict, ensure_ascii=False),
        media_type="application/json",
    )


@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE endpoint: возвращает URL для отправки JSON-RPC сообщений."""
    base_url = str(request.base_url).rstrip("/")

    async def event_stream():
        yield f"event: endpoint\ndata: {base_url}/\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/message")
async def message_endpoint(request: Request):
    """Альтернативная точка входа для сообщений SSE-транспорта."""
    return await jsonrpc_endpoint(request)


@app.get("/health")
async def health():
    return {"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("MCP_WEATHER_PORT", "9001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
