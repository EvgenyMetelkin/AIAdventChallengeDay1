import json
import os
import uuid
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from user import User, UserManager
from agent import Agent

API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
SECRET_KEY = os.getenv("SECRET_KEY", uuid.uuid4().hex)
USERS_DIR = "users"

app = FastAPI(title="AI Chat")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

user_manager = UserManager(users_dir=USERS_DIR)
agent = Agent(api_key=API_KEY, base_url=BASE_URL)


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

    async def generate():
        full_response = ""
        try:
            async for token in agent.send_message_stream(message):
                full_response += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            history = user.get_current_history()
            history.append({"role": "assistant", "content": full_response})
            user.save_agents()
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
    return templates.TemplateResponse("admin.html", {"request": request, "users": users_data})


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
