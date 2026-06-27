import asyncio
import json
import os
import uuid
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from user import User, UserManager
from agent import Agent
from mcp_client import MCPClientManager, MCPMultiServerManager

API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
SECRET_KEY = os.getenv("SECRET_KEY", uuid.uuid4().hex)
USERS_DIR = "users"
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "")
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable_http")
VERBOSE = os.getenv("VERBOSE", "False").lower() == "true"
MCP_CONFIG_FILE = "mcp_config.json"

app = FastAPI(title="AI Chat")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

user_manager = UserManager(users_dir=USERS_DIR)
agent = Agent(api_key=API_KEY, base_url=BASE_URL, verbose=VERBOSE)


def _load_mcp_config() -> list[dict]:
    if os.path.exists(MCP_CONFIG_FILE):
        try:
            with open(MCP_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            if "servers" in cfg:
                return cfg["servers"]
            url = cfg.get("server_url", MCP_SERVER_URL)
            if url:
                return [{
                    "id": MCPMultiServerManager.generate_id(),
                    "name": "Default",
                    "server_url": url,
                    "transport": cfg.get("transport", MCP_TRANSPORT),
                    "env": cfg.get("env", {}),
                    "headers": cfg.get("headers", {}),
                    "enabled": True,
                }]
        except Exception:
            pass
    if MCP_SERVER_URL:
        return [{
            "id": MCPMultiServerManager.generate_id(),
            "name": "Default",
            "server_url": MCP_SERVER_URL,
            "transport": MCP_TRANSPORT,
            "env": {},
            "headers": {},
            "enabled": True,
        }]
    return []


def _save_mcp_config(server_configs: list[dict]):
    with open(MCP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"servers": server_configs}, f, indent=2, ensure_ascii=False)


mcp_server_manager = MCPMultiServerManager(verbose=VERBOSE)

_server_configs = _load_mcp_config()
for cfg in _server_configs:
    sid = cfg["id"]
    mcp_server_manager.server_configs[sid] = cfg
    mcp_server_manager.servers[sid] = MCPClientManager(
        server_url=cfg.get("server_url", ""),
        transport=cfg.get("transport", "streamable_http"),
        verbose=VERBOSE,
        env=cfg.get("env"),
        headers=cfg.get("headers"),
    )


@app.on_event("startup")
async def startup():
    if _server_configs:
        await mcp_server_manager.connect_all()
        status = mcp_server_manager.get_status()
        connected_count = sum(1 for s in status["servers"].values() if s["connected"])
        total_count = len(status["servers"])
        print(f"[STARTUP] MCP: {connected_count}/{total_count} servers connected")


def init_demo():
    if not user_manager.get_user_ids():
        user = user_manager.create_user("demo", "Demo User")
        user.add_agent("default")
        user.set_defaults(model="gpt-3.5-turbo", temperature=0.7, max_tokens=500)


init_demo()


def _get_session_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return user_manager.get_user(user_id)


def _resolve_agent(user: User, request: Request):
    agent_id = request.session.get("agent_id")
    if agent_id and agent_id in user.agents:
        user.current_agent_id = agent_id
    else:
        if user.agents:
            user.current_agent_id = next(iter(user.agents))
            request.session["agent_id"] = user.current_agent_id
        else:
            user.current_agent_id = None


def _build_index_context(request: Request):
    user = _get_session_user(request)
    all_users = user_manager.get_all_users()
    history = []
    agents = {}
    settings = {"model": "gpt-3.5-turbo", "temperature": 0.7, "max_tokens": 500}

    if not user and all_users:
        first_user_id = all_users[0]["user_id"]
        request.session["user_id"] = first_user_id
        user = user_manager.get_user(first_user_id)

    if user:
        _resolve_agent(user, request)
        history = user.get_current_history()
        agents = user.agents
        settings = {
            "model": user.get_default_model(),
            "temperature": user.get_default_temperature(),
            "max_tokens": user.get_default_max_tokens(),
        }

        if not user.agents:
            aid = user.add_agent("default")
            user.current_agent_id = aid
            request.session["agent_id"] = aid
            agents = user.agents

    return {
        "request": request,
        "current_user": user,
        "history": history,
        "agents": agents,
        "settings": settings,
        "all_users": all_users,
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    ctx = _build_index_context(request)
    return templates.TemplateResponse("index.html", ctx)


@app.post("/api/chat/stream")
async def chat_stream(request: Request, message: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "No user selected"}, status_code=400)

    user = user_manager.get_user(user_id)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    _resolve_agent(user, request)

    agent.set_user(user)
    agent.model = user.get_default_model()
    agent.temperature = user.get_default_temperature()
    agent.max_tokens = user.get_default_max_tokens()

    tools = mcp_server_manager.get_all_tools()

    async def generate():
        try:
            if tools:
                async def call_tool_wrapper(name: str, arguments: dict) -> dict:
                    return await mcp_server_manager.call_tool(name, arguments)

                events = await agent.chat_with_tools(message, tools, call_tool_wrapper)
                for evt in events:
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            else:
                full_response = ""
                async for token in agent.send_message_stream(message):
                    full_response += token
                    yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

                history = user.get_current_history()
                history.append({"role": "assistant", "content": full_response})
                user.save_agents()
                yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/switch")
async def switch(request: Request, user_id: str = Form(None), agent_id: str = Form(None)):
    if user_id:
        user = user_manager.get_user(user_id)
        if not user:
            return RedirectResponse("/", status_code=302)
        request.session["user_id"] = user_id
        if not user.agents:
            user.add_agent("default")
        request.session["agent_id"] = next(iter(user.agents)) if user.agents else None
    elif agent_id:
        request.session["agent_id"] = agent_id
    return RedirectResponse("/", status_code=302)


@app.post("/api/settings")
async def save_settings(request: Request, model: str = Form(None),
                        temperature: float = Form(None), max_tokens: int = Form(None)):
    user = _get_session_user(request)
    if user:
        user.set_defaults(model=model, temperature=temperature, max_tokens=max_tokens)
        return JSONResponse({"status": "ok"})
    return JSONResponse({"status": "error", "message": "No user"}, status_code=400)


@app.post("/api/user/create")
async def create_user_sidebar(request: Request, name: str = Form("")):
    user = user_manager.create_user(name=name)
    user.add_agent("default")
    request.session["user_id"] = user.user_id
    request.session["agent_id"] = user.current_agent_id
    return RedirectResponse("/", status_code=302)


@app.post("/api/agent/create")
async def create_agent_sidebar(request: Request, name: str = Form("")):
    user = _get_session_user(request)
    if user:
        agent_id = user.add_agent(name or "New Agent")
        user.current_agent_id = agent_id
        user.save_agents()
        request.session["agent_id"] = agent_id
    return RedirectResponse("/", status_code=302)


@app.post("/api/agent/reset")
async def reset_agent_sidebar(request: Request):
    user = _get_session_user(request)
    if user:
        user.reset_current_history()
    return RedirectResponse("/", status_code=302)


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request):
    users_data = []
    for u in user_manager.get_all_users():
        user_obj = user_manager.get_user(u["user_id"])
        if user_obj:
            users_data.append({
                "user_id": user_obj.user_id,
                "name": user_obj.name,
                "agents": {k: {"name": v["name"],
                                "history_length": len(v.get("history", []))}
                           for k, v in user_obj.agents.items()},
            })
    mcp_full_status = mcp_server_manager.get_status()
    return templates.TemplateResponse("admin.html", {
        "request": request, "users": users_data,
        "mcp_servers": mcp_full_status["servers"],
        "mcp_any_connected": mcp_full_status["any_connected"],
    })


@app.post("/admin/user/create")
async def admin_create_user(request: Request, name: str = Form(...)):
    user_manager.create_user(name=name)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/user/delete")
async def admin_delete_user(request: Request, user_id: str = Form(...)):
    user_manager.delete_user(user_id)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/agent/create")
async def admin_create_agent(request: Request, user_id: str = Form(...), name: str = Form(...)):
    user = user_manager.get_user(user_id)
    if user:
        user.add_agent(name)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/agent/delete")
async def admin_delete_agent(request: Request, user_id: str = Form(...), agent_id: str = Form(...)):
    user = user_manager.get_user(user_id)
    if user:
        user.remove_agent(agent_id)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/agent/reset")
async def admin_reset_agent(request: Request, user_id: str = Form(...), agent_id: str = Form(...)):
    user = user_manager.get_user(user_id)
    if user:
        saved = user.current_agent_id
        user.current_agent_id = agent_id
        user.reset_current_history()
        user.current_agent_id = saved
        user.save_agents()
    return RedirectResponse("/admin", status_code=302)


@app.get("/api/admin/mcp/servers")
async def admin_mcp_servers_status(request: Request):
    status = mcp_server_manager.get_status()
    return JSONResponse(status)


@app.post("/api/admin/mcp/server/add")
async def admin_mcp_server_add(request: Request):
    form = await request.form()
    name = form.get("name", "Server").strip()
    server_url = form.get("server_url", "").strip()
    transport = form.get("transport", "streamable_http").strip()
    enabled = form.get("enabled", "true").strip().lower() == "true"
    if not server_url:
        return JSONResponse({"error": "server_url required"}, status_code=400)
    sid = await mcp_server_manager.add_server(
        name=name, server_url=server_url, transport=transport, enabled=enabled,
    )
    _save_mcp_config(mcp_server_manager.get_server_configs())
    return JSONResponse({"status": "ok", "server_id": sid})


@app.post("/api/admin/mcp/server/delete")
async def admin_mcp_server_delete(request: Request):
    form = await request.form()
    server_id = form.get("server_id", "").strip()
    if not server_id:
        return JSONResponse({"error": "server_id required"}, status_code=400)
    await mcp_server_manager.remove_server(server_id)
    _save_mcp_config(mcp_server_manager.get_server_configs())
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/mcp/server/connect")
async def admin_mcp_server_connect(request: Request):
    form = await request.form()
    server_id = form.get("server_id", "").strip()
    if not server_id:
        return JSONResponse({"error": "server_id required"}, status_code=400)
    ok = await mcp_server_manager.connect_server(server_id)
    _save_mcp_config(mcp_server_manager.get_server_configs())
    return JSONResponse({"status": "ok", "connected": ok})


@app.post("/api/admin/mcp/server/disconnect")
async def admin_mcp_server_disconnect(request: Request):
    form = await request.form()
    server_id = form.get("server_id", "").strip()
    if not server_id:
        return JSONResponse({"error": "server_id required"}, status_code=400)
    await mcp_server_manager.disconnect_server(server_id)
    _save_mcp_config(mcp_server_manager.get_server_configs())
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/mcp/server/toggle")
async def admin_mcp_server_toggle(request: Request):
    form = await request.form()
    server_id = form.get("server_id", "").strip()
    enabled = form.get("enabled", "true").strip().lower() == "true"
    if not server_id:
        return JSONResponse({"error": "server_id required"}, status_code=400)
    await mcp_server_manager.toggle_server(server_id, enabled=enabled)
    _save_mcp_config(mcp_server_manager.get_server_configs())
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/mcp/server/refresh")
async def admin_mcp_server_refresh(request: Request):
    form = await request.form()
    server_id = form.get("server_id", "").strip()
    if not server_id:
        return JSONResponse({"error": "server_id required"}, status_code=400)
    await mcp_server_manager.refresh_server_tools(server_id)
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/mcp/server/update")
async def admin_mcp_server_update(request: Request):
    form = await request.form()
    server_id = form.get("server_id", "").strip()
    if not server_id:
        return JSONResponse({"error": "server_id required"}, status_code=400)
    name = form.get("name")
    server_url = form.get("server_url")
    transport = form.get("transport")
    enabled_raw = form.get("enabled")
    enabled = None if enabled_raw is None else enabled_raw.strip().lower() == "true"
    ok = await mcp_server_manager.reconfigure_server(
        server_id, name=name, server_url=server_url,
        transport=transport, enabled=enabled,
    )
    _save_mcp_config(mcp_server_manager.get_server_configs())
    return JSONResponse({"status": "ok", "connected": ok})


@app.post("/api/admin/mcp/server/env")
async def admin_mcp_server_env(request: Request):
    form = await request.form()
    server_id = form.get("server_id", "").strip()
    if not server_id:
        return JSONResponse({"error": "server_id required"}, status_code=400)
    new_env: dict = {}
    i = 0
    while True:
        key = form.get(f"env_key_{i}", "").strip()
        val = form.get(f"env_val_{i}", "").strip()
        if not key:
            break
        new_env[key] = val
        i += 1
    new_key = form.get("env_new_key", "").strip()
    new_val = form.get("env_new_val", "").strip()
    if new_key:
        new_env[new_key] = new_val
    remove_key = form.get("env_remove", "").strip()
    if remove_key and remove_key in new_env:
        del new_env[remove_key]
    await mcp_server_manager.update_server_env(server_id, new_env)
    _save_mcp_config(mcp_server_manager.get_server_configs())
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/mcp/server/headers")
async def admin_mcp_server_headers(request: Request):
    form = await request.form()
    server_id = form.get("server_id", "").strip()
    if not server_id:
        return JSONResponse({"error": "server_id required"}, status_code=400)
    new_headers: dict = {}
    i = 0
    while True:
        key = form.get(f"hdr_key_{i}", "").strip()
        val = form.get(f"hdr_val_{i}", "").strip()
        if not key:
            break
        new_headers[key] = val
        i += 1
    new_key = form.get("hdr_new_key", "").strip()
    new_val = form.get("hdr_new_val", "").strip()
    if new_key:
        new_headers[new_key] = new_val
    remove_key = form.get("hdr_remove", "").strip()
    if remove_key and remove_key in new_headers:
        del new_headers[remove_key]
    reconnect = form.get("reconnect", "").strip().lower() == "true"
    await mcp_server_manager.update_server_headers(server_id, new_headers, reconnect=reconnect)
    _save_mcp_config(mcp_server_manager.get_server_configs())
    return JSONResponse({"status": "ok"})
