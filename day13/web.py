import os
import json
import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextvars import ContextVar
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from agent import Agent
from user import User, load_all_users, create_user, create_default_user
from swarm import SwarmOrchestrator, SwarmStage, STAGE_LABELS, STAGE_DESCRIPTIONS

# Загружаем переменные окружения из .env
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Переменные окружения с значениями по умолчанию
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "500"))
VERBOSE = os.getenv("VERBOSE", "False").lower() == "true"
AGENT_ID = os.getenv("AGENT_ID", None)
HISTORY_DIR = os.getenv("HISTORY_DIR", "agent_history")
USERS_DIR = os.getenv("USERS_DIR", "users")

if not LLM_API_KEY:
    raise RuntimeError("LLM_API_KEY not set in environment variables")


# ============================================================
# Состояние приложения (вместо глобальных переменных)
# ============================================================

class AppState:
    """Потокобезопасное состояние приложения."""
    def __init__(self):
        self.users: Dict[str, User] = {}
        self.agent: Optional[Agent] = None
        self.swarm: Optional[SwarmOrchestrator] = None
        self._lock = asyncio.Lock()
    
    async def get_users_snapshot(self) -> Dict[str, User]:
        """Безопасное чтение пользователей (снапшот)."""
        async with self._lock:
            return dict(self.users)
    
    async def get_user(self, user_id: str) -> Optional[User]:
        async with self._lock:
            return self.users.get(user_id)
    
    async def add_user(self, user: User) -> None:
        async with self._lock:
            self.users[user.user_id] = user
    
    async def remove_user(self, user_id: str) -> Optional[User]:
        async with self._lock:
            return self.users.pop(user_id, None)
    
    async def user_count(self) -> int:
        async with self._lock:
            return len(self.users)
    
    async def first_user_id(self) -> Optional[str]:
        async with self._lock:
            if self.users:
                return next(iter(self.users.keys()))
            return None
    
    async def set_agent(self, agent: Agent) -> None:
        async with self._lock:
            self.agent = agent
    
    async def get_agent(self) -> Optional[Agent]:
        async with self._lock:
            return self.agent
    
    async def set_swarm(self, swarm: SwarmOrchestrator) -> None:
        async with self._lock:
            self.swarm = swarm
    
    async def get_swarm(self) -> Optional[SwarmOrchestrator]:
        async with self._lock:
            return self.swarm


# Контекстная переменная для текущего пользователя на запрос
current_user_id_ctx: ContextVar[Optional[str]] = ContextVar('current_user_id', default=None)

# Глобальный экземпляр состояния (инициализируется в lifespan)
app_state = AppState()


# ============================================================
# Зависимости FastAPI
# ============================================================

async def get_state() -> AppState:
    """Dependency: получить состояние приложения."""
    return app_state


async def get_current_user_id() -> Optional[str]:
    """Dependency: получить ID текущего пользователя из контекста запроса."""
    return current_user_id_ctx.get()


# ============================================================
# FastAPI приложение
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Загружаем всех пользователей
    loaded_users = load_all_users(USERS_DIR)
    async with app_state._lock:
        app_state.users = loaded_users
    logger.info(f"Loaded {len(loaded_users)} users")
    
    # Если пользователей нет, создаем дефолтного
    if not loaded_users:
        default_user = create_default_user(USERS_DIR)
        await app_state.add_user(default_user)
        logger.info(f"Created default user: {default_user.name} ({default_user.user_id})")
    
    # Выбираем первого пользователя как текущего по умолчанию
    first_id = await app_state.first_user_id()
    first_user = await app_state.get_user(first_id)
    
    # Инициализируем агента с первым пользователем
    agent = Agent(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        verbose=VERBOSE,
        agent_id=AGENT_ID,
        history_dir=HISTORY_DIR,
        user=first_user
    )
    await app_state.set_agent(agent)
    logger.info(f"Agent initialized with user: {first_user.name} ({first_user.user_id})")
    
    # Инициализируем оркестратор роя
    swarm_base_dir = os.path.join(USERS_DIR, first_user.user_id, "swarms") if first_user else os.path.join(USERS_DIR, "swarms")
    swarm = SwarmOrchestrator(agent=agent, base_dir=swarm_base_dir)
    swarm.load_all_tasks()
    await app_state.set_swarm(swarm)
    logger.info(f"Swarm orchestrator initialized, {len(swarm._tasks)} tasks loaded")
    
    yield
    
    # Сохраняем историю всех пользователей при завершении
    async with app_state._lock:
        for user in app_state.users.values():
            user.save_agents()
            user.save_working_memory()
    logger.info("Shutting down, all histories saved")


app = FastAPI(lifespan=lifespan)

# CORS middleware для разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Шаблоны и статика
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ============================================================
# Pydantic модели
# ============================================================

class MessageRequest(BaseModel):
    message: str
    user_id: Optional[str] = None  # ID пользователя (если не указан, используется текущий)


class SendResponse(BaseModel):
    assistant_reply: str
    history: list
    user_id: str
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None


class CreateAgentRequest(BaseModel):
    name: str


# ============================================================
# Вспомогательная функция
# ============================================================

async def _resolve_user(state: AppState, user_id: Optional[str] = None) -> User:
    """Разрешить пользователя: приоритет — явный user_id, затем контекст."""
    if user_id:
        user = await state.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    
    ctx_id = current_user_id_ctx.get()
    if ctx_id:
        user = await state.get_user(ctx_id)
        if user:
            return user
    
    # Fallback: первый пользователь
    first_id = await state.first_user_id()
    if first_id:
        user = await state.get_user(first_id)
        if user:
            return user
    
    raise HTTPException(status_code=400, detail="No users available")


# ============================================================
# Эндпоинты
# ============================================================

@app.get("/")
async def get_index(request: Request, state: AppState = Depends(get_state)):
    """Главная страница чата"""
    users_snapshot = await state.get_users_snapshot()
    users_list = []
    for user in users_snapshot.values():
        user_dict = user.to_dict()
        user_dict["agent_count"] = len(user.agents) if user.agents else 0
        users_list.append(user_dict)
    
    agent = await state.get_agent()
    current_agent_id = agent.user.current_agent_id if agent and agent.user else None
    current_agent_name = "None"
    if agent and agent.user and current_agent_id and current_agent_id in agent.user.agents:
        current_agent_name = agent.user.agents[current_agent_id]['name']
    
    ctx_user_id = current_user_id_ctx.get()
    if not ctx_user_id and users_snapshot:
        ctx_user_id = next(iter(users_snapshot.keys()))
    
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request,
            "users": users_list,
            "current_user_id": ctx_user_id,
            "current_agent_id": current_agent_id,
            "current_agent_name": current_agent_name
        }
    )


@app.get("/chat.js")
async def serve_chat_js():
    """Отдаёт JavaScript файл для клиентской части"""
    if not os.path.exists("static/chat.js"):
        raise HTTPException(status_code=404, detail="chat.js not found")
    return FileResponse("static/chat.js", media_type="application/javascript")


# ------------------------------------------------------------
# Эндпоинты для управления пользователями
# ------------------------------------------------------------

@app.get("/api/users")
async def get_users(state: AppState = Depends(get_state)):
    """Получить список всех пользователей."""
    users_snapshot = await state.get_users_snapshot()
    users_list = []
    for user in users_snapshot.values():
        user_dict = user.to_dict()
        user_dict["agent_count"] = len(user.agents) if user.agents else 0
        users_list.append(user_dict)
    
    ctx_user_id = current_user_id_ctx.get()
    if not ctx_user_id and users_snapshot:
        ctx_user_id = next(iter(users_snapshot.keys()))
    
    return {
        "users": users_list,
        "current_user_id": ctx_user_id
    }


@app.post("/api/users")
async def create_user_endpoint(
    name: str = Form(...),
    preferences: UploadFile = File(None),
    state: AppState = Depends(get_state)
):
    """Создать нового пользователя."""
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    
    preferences_content = None
    if preferences:
        try:
            preferences_content = await preferences.read()
            preferences_content = preferences_content.decode('utf-8')
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid preferences file: {str(e)}")
    
    try:
        new_user = create_user(USERS_DIR, name.strip(), preferences_content)
        await state.add_user(new_user)
        
        # Устанавливаем контекст текущего пользователя
        current_user_id_ctx.set(new_user.user_id)
        
        # Обновляем агента
        agent = await state.get_agent()
        if agent:
            agent.set_user(new_user)
        
        logger.info(f"Created new user: {new_user.name} ({new_user.user_id})")
        
        return {
            "status": "ok",
            "user": new_user.to_dict(),
            "current_user_id": new_user.user_id
        }
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")


@app.post("/api/users/{user_id}/switch")
async def switch_user(user_id: str, state: AppState = Depends(get_state)):
    """Переключиться на другого пользователя."""
    user = await state.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Устанавливаем контекст
    current_user_id_ctx.set(user_id)
    
    agent = await state.get_agent()
    if agent:
        agent.set_user(user)
    
    logger.info(f"Switched to user: {user.name} ({user_id})")
    
    return {
        "status": "ok",
        "user": user.to_dict(),
        "current_user_id": user_id
    }


@app.post("/api/users/{user_id}/reset")
async def reset_user_history(user_id: str, state: AppState = Depends(get_state)):
    """Сбросить историю диалога пользователя."""
    user = await state.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.reset_current_history()
    
    logger.info(f"Reset history for user: {user.name} ({user_id})")
    
    return {
        "status": "ok",
        "message": f"History reset for user {user.name}"
    }


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str, state: AppState = Depends(get_state)):
    """Удалить пользователя."""
    user = await state.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    count = await state.user_count()
    if count <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last user")
    
    # Если удаляем текущего пользователя, переключаем контекст
    ctx_id = current_user_id_ctx.get()
    if user_id == ctx_id:
        users_snapshot = await state.get_users_snapshot()
        new_user_id = next(uid for uid in users_snapshot.keys() if uid != user_id)
        current_user_id_ctx.set(new_user_id)
        agent = await state.get_agent()
        if agent:
            new_user = await state.get_user(new_user_id)
            if new_user:
                agent.set_user(new_user)
    
    # Удаляем папку пользователя
    user_path = os.path.join(USERS_DIR, user_id)
    if os.path.exists(user_path):
        shutil.rmtree(user_path)
    
    await state.remove_user(user_id)
    
    logger.info(f"Deleted user: {user.name} ({user_id})")
    
    return {
        "status": "ok",
        "message": f"User {user.name} deleted",
        "current_user_id": current_user_id_ctx.get()
    }


# ------------------------------------------------------------
# Эндпоинты для управления агентами
# ------------------------------------------------------------

@app.get("/api/agents")
async def get_agents(state: AppState = Depends(get_state)):
    """Получить список всех агентов текущего пользователя."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    agents_list = []
    for agent_id, data in agent.user.agents.items():
        agents_list.append({
            "agent_id": agent_id,
            "name": data["name"],
            "history_length": len(data["history"]),
            "created": data.get("created", ""),
            "is_current": agent_id == agent.user.current_agent_id
        })
    
    return {
        "agents": agents_list,
        "current_agent_id": agent.user.current_agent_id
    }


@app.post("/api/agents")
async def create_agent(req: CreateAgentRequest, state: AppState = Depends(get_state)):
    """Создать нового агента."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="Agent name cannot be empty")
    
    try:
        new_agent_id = agent.user.add_agent(req.name.strip())
        agent.user.current_agent_id = new_agent_id
        agent.user.save_agents()
        
        logger.info(f"Created new agent: {req.name} ({new_agent_id}) for user {agent.user.name}")
        
        return {
            "status": "ok",
            "agent_id": new_agent_id,
            "name": req.name,
            "current_agent_id": new_agent_id
        }
    except Exception as e:
        logger.error(f"Error creating agent: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating agent: {str(e)}")


@app.post("/api/agents/{agent_id}/switch")
async def switch_agent(agent_id: str, state: AppState = Depends(get_state)):
    """Переключиться на другого агента с генерацией сводки."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    if agent_id not in agent.user.agents:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if agent_id == agent.user.current_agent_id:
        return {
            "status": "ok",
            "current_agent_id": agent_id,
            "summary_generated": False,
            "message": "Already on this agent"
        }
    
    try:
        summary = await agent.user.switch_agent(agent_id, agent)
        
        logger.info(f"Switched to agent: {agent.user.agents[agent_id]['name']} ({agent_id})")
        logger.info(f"Summary generated: {bool(summary)}")
        
        return {
            "status": "ok",
            "current_agent_id": agent_id,
            "summary_generated": bool(summary),
            "summary_preview": summary[:200] + "..." if summary and len(summary) > 200 else summary,
            "working_memory_length": len(agent.user.working_memory)
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error switching agent: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error switching agent: {str(e)}")


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str, state: AppState = Depends(get_state)):
    """Удалить агента."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    if agent_id not in agent.user.agents:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    try:
        success = agent.user.delete_agent(agent_id)
        if not success:
            raise HTTPException(status_code=400, detail="Cannot delete the last agent")
        
        logger.info(f"Deleted agent: {agent_id} for user {agent.user.name}")
        
        return {
            "status": "ok",
            "message": "Agent deleted",
            "current_agent_id": agent.user.current_agent_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting agent: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting agent: {str(e)}")


# ------------------------------------------------------------
# Эндпоинты для рабочей памяти
# ------------------------------------------------------------

@app.get("/api/working_memory")
async def get_working_memory(state: AppState = Depends(get_state)):
    """Получить содержимое рабочей памяти."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    return {
        "working_memory": agent.user.working_memory,
        "count": len(agent.user.working_memory),
        "user_id": agent.user.user_id,
        "user_name": agent.user.name
    }


@app.delete("/api/working_memory")
async def clear_working_memory(state: AppState = Depends(get_state)):
    """Очистить рабочую память."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    agent.user.working_memory = []
    agent.user.save_working_memory()
    
    return {
        "status": "ok",
        "message": "Working memory cleared"
    }


# ------------------------------------------------------------
# Основные эндпоинты для работы с чатом
# ------------------------------------------------------------

@app.get("/history")
async def get_history(state: AppState = Depends(get_state)):
    """Вернуть историю текущего агента."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    history = agent.user.get_current_history()
    current_agent_id = agent.user.current_agent_id
    agent_name = "Unknown"
    if current_agent_id and current_agent_id in agent.user.agents:
        agent_name = agent.user.agents[current_agent_id]['name']
    
    return {
        "history": history,
        "user_id": agent.user.user_id,
        "user_name": agent.user.name,
        "agent_id": current_agent_id,
        "agent_name": agent_name
    }


@app.post("/send")
async def send_message(req: MessageRequest, state: AppState = Depends(get_state)):
    """Отправить сообщение агенту и получить ответ."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    # Разрешаем пользователя
    user = await _resolve_user(state, req.user_id)
    agent.set_user(user)
    
    # Проверяем наличие текущего агента
    if user.current_agent_id is None or user.current_agent_id not in user.agents:
        default_id = user.add_agent("default")
        user.current_agent_id = default_id
        user.save_agents()
    
    try:
        assistant_reply = await agent.send_message(req.message)
        
        history = user.get_current_history()
        current_agent_id = user.current_agent_id
        agent_name = "Unknown"
        if current_agent_id and current_agent_id in user.agents:
            agent_name = user.agents[current_agent_id]['name']
        
        return SendResponse(
            assistant_reply=assistant_reply,
            history=history,
            user_id=user.user_id,
            agent_id=current_agent_id,
            agent_name=agent_name
        )
    except Exception as e:
        logger.error(f"Error in /send: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@app.post("/send/stream")
async def send_message_stream(req: MessageRequest, state: AppState = Depends(get_state)):
    """Отправить сообщение и получить потоковый ответ через SSE."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    user = await _resolve_user(state, req.user_id)
    agent.set_user(user)
    
    if user.current_agent_id is None or user.current_agent_id not in user.agents:
        default_id = user.add_agent("default")
        user.current_agent_id = default_id
        user.save_agents()
    
    async def event_stream():
        try:
            full_response = ""
            async for token in agent.send_message_stream(req.message):
                full_response += token
                yield f"data: {json.dumps({'token': token})}\n\n"
            
            # Сохраняем полный ответ в историю
            history = user.get_current_history()
            history.append({"role": "assistant", "content": full_response})
            user.save_agents()
            
            yield f"data: {json.dumps({'done': True, 'agent_id': user.current_agent_id})}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {str(e)}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/reset")
async def reset_conversation(state: AppState = Depends(get_state)):
    """Очистить историю диалога текущего агента."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        agent.reset_conversation()
        return {
            "status": "ok", 
            "message": "History cleared",
            "user_id": agent.user.user_id if agent.user else None,
            "agent_id": agent.user.current_agent_id if agent.user else None
        }
    except Exception as e:
        logger.error(f"Error in /reset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Reset error: {str(e)}")


@app.get("/api/status")
async def get_status(state: AppState = Depends(get_state)):
    """Статус-бар: сводка о пользователях, агентах, сообщениях."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    users_snapshot = await state.get_users_snapshot()
    users_count = len(users_snapshot)
    agents_count = len(agent.user.agents) if agent.user else 0
    messages_count = len(agent.user.get_current_history()) if agent.user else 0
    
    return {
        "users_count": users_count,
        "agents_count": agents_count,
        "messages_count": messages_count,
        "model": agent.model,
        "current_user": agent.user.to_dict() if agent.user else None,
        "current_agent_id": agent.user.current_agent_id if agent.user else None
    }


@app.get("/info")
async def get_agent_info(state: AppState = Depends(get_state)):
    """Получить информацию об агенте."""
    agent = await state.get_agent()
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent.get_agent_info()


# ============================================================
# Swarm Mode эндпоинты
# ============================================================

class SwarmCreateRequest(BaseModel):
    description: str
    user_id: Optional[str] = None


class SwarmActionRequest(BaseModel):
    action: str  # start_planning, approve_plan, reject_plan, start_execution,
                 # approve_execution, reject_execution, start_validation,
                 # approve_validation, reject_validation, finish,
                 # pause, resume, retry, cancel


@app.post("/api/swarm/create")
async def swarm_create(req: SwarmCreateRequest, state: AppState = Depends(get_state)):
    """Создать новую задачу для роя агентов."""
    swarm = await state.get_swarm()
    if not swarm:
        raise HTTPException(status_code=503, detail="Swarm orchestrator not initialized")

    user = await _resolve_user(state, req.user_id)

    try:
        task = await swarm.create_task(req.description, user.user_id)
        return {
            "status": "ok",
            "task": task.to_dict(),
        }
    except Exception as e:
        logger.error(f"Error creating swarm task: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating task: {str(e)}")


@app.get("/api/swarm/tasks")
async def swarm_list_tasks(state: AppState = Depends(get_state), user_id: Optional[str] = None):
    """Получить список задач роя."""
    swarm = await state.get_swarm()
    if not swarm:
        raise HTTPException(status_code=503, detail="Swarm orchestrator not initialized")

    if not user_id:
        user = await _resolve_user(state, None)
        user_id = user.user_id

    tasks = swarm.list_tasks(user_id)
    return {
        "tasks": [t.to_dict() for t in tasks],
        "count": len(tasks),
        "stage_labels": {s.value: l for s, l in STAGE_LABELS.items()},
        "stage_descriptions": {s.value: d for s, d in STAGE_DESCRIPTIONS.items()},
    }


@app.get("/api/swarm/tasks/{task_id}")
async def swarm_get_task(task_id: str, state: AppState = Depends(get_state)):
    """Получить состояние задачи роя."""
    swarm = await state.get_swarm()
    if not swarm:
        raise HTTPException(status_code=503, detail="Swarm orchestrator not initialized")

    task = swarm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task": task.to_dict(),
        "stage_labels": {s.value: l for s, l in STAGE_LABELS.items()},
        "stage_descriptions": {s.value: d for s, d in STAGE_DESCRIPTIONS.items()},
        "progress_pct": task.progress_pct,
    }


@app.post("/api/swarm/tasks/{task_id}/action")
async def swarm_action(task_id: str, req: SwarmActionRequest, state: AppState = Depends(get_state)):
    """Выполнить действие над задачей роя."""
    swarm = await state.get_swarm()
    if not swarm:
        raise HTTPException(status_code=503, detail="Swarm orchestrator not initialized")

    action_map = {
        "start_planning": swarm.start_planning,
        "approve_plan": swarm.approve_plan,
        "reject_plan": swarm.reject_plan,
        "start_execution": swarm.start_execution,
        "approve_execution": swarm.approve_execution,
        "reject_execution": swarm.reject_execution,
        "start_validation": swarm.start_validation,
        "approve_validation": swarm.approve_validation,
        "reject_validation": swarm.reject_validation,
        "finish": swarm.start_finishing,
        "pause": swarm.pause,
        "resume": swarm.resume,
        "retry": swarm.retry_stage,
        "cancel": swarm.cancel,
    }

    handler = action_map.get(req.action)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    try:
        task = await handler(task_id)
        return {
            "status": "ok",
            "task": task.to_dict(),
            "action": req.action,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in swarm action '{req.action}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.delete("/api/swarm/tasks/{task_id}")
async def swarm_delete_task(task_id: str, state: AppState = Depends(get_state)):
    """Удалить задачу роя."""
    swarm = await state.get_swarm()
    if not swarm:
        raise HTTPException(status_code=503, detail="Swarm orchestrator not initialized")

    try:
        await swarm.delete_task(task_id)
        return {"status": "ok", "message": f"Task {task_id} deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting swarm task: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/swarm/tasks/{task_id}/artifacts")
async def swarm_list_artifacts(task_id: str, stage: Optional[str] = None, state: AppState = Depends(get_state)):
    """Получить список артефактов задачи роя."""
    swarm = await state.get_swarm()
    if not swarm:
        raise HTTPException(status_code=503, detail="Swarm orchestrator not initialized")

    task = swarm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    artifacts = {}
    task_dir = os.path.join(swarm._base_dir, task_id)

    if stage:
        stage_dir = os.path.join(task_dir, stage)
        if os.path.exists(stage_dir):
            files = []
            for f in sorted(os.listdir(stage_dir)):
                fpath = os.path.join(stage_dir, f)
                if os.path.isfile(fpath):
                    files.append({"name": f, "size": os.path.getsize(fpath)})
            artifacts[stage] = files
    else:
        for s_name in ["planning", "execution", "validation", "done"]:
            stage_dir = os.path.join(task_dir, s_name)
            if os.path.exists(stage_dir):
                files = []
                for f in sorted(os.listdir(stage_dir)):
                    fpath = os.path.join(stage_dir, f)
                    if os.path.isfile(fpath):
                        files.append({"name": f, "size": os.path.getsize(fpath)})
                if files:
                    artifacts[s_name] = files

    return {"task_id": task_id, "artifacts": artifacts}


@app.get("/api/swarm/tasks/{task_id}/artifacts/{stage}/{filename:path}")
async def swarm_read_artifact(task_id: str, stage: str, filename: str, state: AppState = Depends(get_state)):
    """Прочитать содержимое артефакта."""
    swarm = await state.get_swarm()
    if not swarm:
        raise HTTPException(status_code=503, detail="Swarm orchestrator not initialized")

    task = swarm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    filepath = os.path.join(swarm._base_dir, task_id, stage, filename)
    filepath = os.path.normpath(filepath)

    # Security: ensure the file is within the task directory
    task_dir = os.path.normpath(os.path.join(swarm._base_dir, task_id))
    if not filepath.startswith(task_dir):
        raise HTTPException(status_code=403, detail="Access denied")

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return {"filename": filename, "stage": stage, "content": content}
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not a text file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")
