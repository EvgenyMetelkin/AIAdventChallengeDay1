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
from mcp_client import MCPClientManager

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


def _load_mcp_config() -> tuple[str, str, dict, dict]:
    if os.path.exists(MCP_CONFIG_FILE):
        try:
            with open(MCP_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            url = cfg.get("server_url", MCP_SERVER_URL)
            transport = cfg.get("transport", MCP_TRANSPORT)
            env = cfg.get("env", {})
            headers = cfg.get("headers", {})
            return url, transport, env, headers
        except Exception:
            pass
    return MCP_SERVER_URL, MCP_TRANSPORT, {}, {}


def _save_mcp_config(url: str, transport: str, env: Optional[dict] = None,
                     headers: Optional[dict] = None):
    existing = {}
    if os.path.exists(MCP_CONFIG_FILE):
        try:
            with open(MCP_CONFIG_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    existing["server_url"] = url
    existing["transport"] = transport
    if env is not None:
        existing["env"] = dict(env)
    if headers is not None:
        existing["headers"] = dict(headers)
    with open(MCP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


_mcp_url, _mcp_transport, _mcp_env, _mcp_headers = _load_mcp_config()
mcp_client = MCPClientManager(
    server_url=_mcp_url,
    transport=_mcp_transport,
    verbose=VERBOSE,
    env=_mcp_env,
    headers=_mcp_headers,
)


_mcp_bg_task = None


@app.on_event("startup")
async def startup():
    if _mcp_url:
        global _mcp_bg_task
        _mcp_bg_task = asyncio.create_task(_mcp_connect_bg(_mcp_url))


async def _mcp_connect_bg(url: str):
    await mcp_client.connect()
    if mcp_client.connected:
        print(f"[STARTUP] MCP connected to {url} "
              f"({len(mcp_client.get_cached_tools())} tools)")
    else:
        print(f"[STARTUP] MCP connection failed, continuing without tools")


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

    mcp_available = mcp_client.connected or (MCP_SERVER_URL and await mcp_client.ensure_connected())
    tools = mcp_client.tools_to_openai_format() if mcp_available else []

    async def generate():
        try:
            if tools:
                async def call_tool_wrapper(name: str, arguments: dict) -> dict:
                    if not mcp_client.connected:
                        await mcp_client.ensure_connected()
                    return await mcp_client.call_tool(name, arguments)

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
    mcp_status = mcp_client.get_status()
    return templates.TemplateResponse("admin.html", {
        "request": request, "users": users_data, "mcp_status": mcp_status,
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


@app.post("/admin/mcp/connect")
async def admin_mcp_connect(request: Request, server_url: str = Form(...),
                            transport: str = Form("streamable_http")):
    global _mcp_bg_task
    _save_mcp_config(server_url, transport, env=mcp_client.env, headers=mcp_client.headers)
    if transport == "stdio":
        mcp_client.server_url = server_url
    else:
        mcp_client.server_url = server_url.rstrip("/")
    mcp_client.transport = transport or "streamable_http"
    if _mcp_bg_task and not _mcp_bg_task.done():
        _mcp_bg_task.cancel()
    _mcp_bg_task = asyncio.create_task(_mcp_reconnect_bg())
    return RedirectResponse("/admin", status_code=302)


async def _mcp_reconnect_bg():
    try:
        await mcp_client.reconfigure(mcp_client.server_url, mcp_client.transport)
    except Exception:
        pass


@app.post("/admin/mcp/disconnect")
async def admin_mcp_disconnect(request: Request):
    global _mcp_bg_task
    if _mcp_bg_task and not _mcp_bg_task.done():
        _mcp_bg_task.cancel()
        _mcp_bg_task = None
    await mcp_client.disconnect()
    mcp_client.server_url = ""
    _save_mcp_config("", mcp_client.transport, env=mcp_client.env, headers=mcp_client.headers)
    return RedirectResponse("/admin", status_code=302)


@app.get("/api/admin/mcp/status")
async def admin_mcp_status(request: Request):
    status = mcp_client.get_status()
    return JSONResponse({
        "connected": status["connected"],
        "server_url": status.get("server_url", ""),
        "transport": status.get("transport", ""),
        "tools_count": status["tools_count"],
        "resources_count": status["resources_count"],
        "templates_count": status["templates_count"],
        "tools": status.get("tools", []),
        "resources": status.get("resources", []),
        "last_error": status.get("last_error", ""),
    })


@app.post("/admin/mcp/refresh")
async def admin_mcp_refresh(request: Request):
    if mcp_client.connected:
        await mcp_client.refresh_tools()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/mcp/env")
async def admin_mcp_env(request: Request):
    form = await request.form()
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

    mcp_client.env = new_env
    _save_mcp_config(mcp_client.server_url, mcp_client.transport,
                     env=new_env, headers=mcp_client.headers)
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/mcp/headers")
async def admin_mcp_headers(request: Request):
    form = await request.form()
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

    mcp_client.headers = new_headers
    if mcp_client.connected and mcp_client.transport != "stdio":
        global _mcp_bg_task
        if _mcp_bg_task and not _mcp_bg_task.done():
            _mcp_bg_task.cancel()
        _mcp_bg_task = asyncio.create_task(_mcp_reconnect_bg())

    _save_mcp_config(mcp_client.server_url, mcp_client.transport,
                     env=mcp_client.env, headers=new_headers)
    return RedirectResponse("/admin", status_code=302)
