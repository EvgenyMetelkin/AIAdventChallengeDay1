import os
import logging
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from agent import Agent
from user import User, load_all_users, create_user, create_default_user

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

# Глобальные объекты
agent = None
users = {}  # словарь user_id -> User
current_user_id = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent, users, current_user_id
    
    # Загружаем всех пользователей
    users = load_all_users(USERS_DIR)
    logger.info(f"Loaded {len(users)} users")
    
    # Если пользователей нет, создаем дефолтного
    if not users:
        default_user = create_default_user(USERS_DIR)
        users[default_user.user_id] = default_user
        logger.info(f"Created default user: {default_user.name} ({default_user.user_id})")
    
    # Выбираем первого пользователя
    current_user_id = list(users.keys())[0]
    current_user = users[current_user_id]
    
    # Инициализируем агента с текущим пользователем
    agent = Agent(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        verbose=VERBOSE,
        agent_id=AGENT_ID,
        history_dir=HISTORY_DIR,
        user=current_user
    )
    logger.info(f"Agent initialized with user: {current_user.name} ({current_user.user_id})")
    
    yield
    
    # Сохраняем историю всех пользователей при завершении
    for user in users.values():
        user.save_history()
    logger.info("Shutting down, all histories saved")

app = FastAPI(lifespan=lifespan)

# Шаблоны и статика
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Pydantic модели для запросов
class MessageRequest(BaseModel):
    message: str

class SendResponse(BaseModel):
    assistant_reply: str
    history: list
    user_id: str

# ------------------------------------------------------------
# Эндпоинты API
# ------------------------------------------------------------

@app.get("/")
async def get_index(request: Request):
    """Главная страница чата"""
    users_list = [user.to_dict() for user in users.values()]
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request,
            "users": users_list,
            "current_user_id": current_user_id
        }
    )

@app.get("/chat.js")
async def serve_chat_js():
    """Отдаёт JavaScript файл для клиентской части"""
    if not os.path.exists("static/chat.js"):
        raise HTTPException(status_code=404, detail="chat.js not found")
    return FileResponse("static/chat.js", media_type="application/javascript")

@app.get("/api/users")
async def get_users():
    """Получить список всех пользователей."""
    return {
        "users": [user.to_dict() for user in users.values()],
        "current_user_id": current_user_id
    }

@app.post("/api/users")
async def create_user_endpoint(
    name: str = Form(...),
    preferences: UploadFile = File(None)
):
    """
    Создать нового пользователя.
    
    - **name**: Имя пользователя
    - **preferences**: (опционально) MD файл с предпочтениями
    """
    global users, current_user_id, agent
    
    # Проверяем, что имя не пустое
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    
    # Читаем предпочтения, если файл передан
    preferences_content = None
    if preferences:
        try:
            preferences_content = await preferences.read()
            preferences_content = preferences_content.decode('utf-8')
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid preferences file: {str(e)}")
    
    # Создаем пользователя
    try:
        new_user = create_user(USERS_DIR, name.strip(), preferences_content)
        users[new_user.user_id] = new_user
        
        # Автоматически переключаемся на нового пользователя
        current_user_id = new_user.user_id
        agent.set_user(new_user)
        
        logger.info(f"Created new user: {new_user.name} ({new_user.user_id})")
        
        return {
            "status": "ok",
            "user": new_user.to_dict(),
            "current_user_id": current_user_id
        }
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")

@app.post("/api/users/{user_id}/switch")
async def switch_user(user_id: str):
    """Переключиться на другого пользователя."""
    global current_user_id, agent
    
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_user_id = user_id
    agent.set_user(users[user_id])
    
    logger.info(f"Switched to user: {users[user_id].name} ({user_id})")
    
    return {
        "status": "ok",
        "user": users[user_id].to_dict(),
        "current_user_id": current_user_id
    }

@app.post("/api/users/{user_id}/reset")
async def reset_user_history(user_id: str):
    """Сбросить историю диалога пользователя."""
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = users[user_id]
    user.reset_history()
    
    # Если это текущий пользователь, обновляем агента
    if user_id == current_user_id:
        agent.user = user
    
    logger.info(f"Reset history for user: {user.name} ({user_id})")
    
    return {
        "status": "ok",
        "message": f"History reset for user {user.name}"
    }

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str):
    """Удалить пользователя."""
    global users, current_user_id, agent
    
    if user_id not in users:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Не даем удалить последнего пользователя
    if len(users) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last user")
    
    user = users[user_id]
    
    # Если удаляем текущего пользователя, переключаемся на первого попавшегося
    if user_id == current_user_id:
        new_user_id = next(uid for uid in users.keys() if uid != user_id)
        current_user_id = new_user_id
        agent.set_user(users[new_user_id])
    
    # Удаляем папку пользователя
    user_path = os.path.join(USERS_DIR, user_id)
    if os.path.exists(user_path):
        shutil.rmtree(user_path)
    
    del users[user_id]
    
    logger.info(f"Deleted user: {user.name} ({user_id})")
    
    return {
        "status": "ok",
        "message": f"User {user.name} deleted",
        "current_user_id": current_user_id
    }

@app.get("/history")
async def get_history():
    """Вернуть текущую историю диалога."""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    return {
        "history": agent.user.history,
        "user_id": agent.user.user_id,
        "user_name": agent.user.name
    }

@app.post("/send")
async def send_message(req: MessageRequest):
    """Отправить сообщение агенту и получить ответ."""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.user:
        raise HTTPException(status_code=400, detail="No user selected")
    
    try:
        assistant_reply = await agent.send_message(req.message)
        return SendResponse(
            assistant_reply=assistant_reply,
            history=agent.user.history,
            user_id=agent.user.user_id
        )
    except Exception as e:
        logger.error(f"Error in /send: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

@app.post("/reset")
async def reset_conversation():
    """Очистить историю диалога текущего пользователя."""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        agent.reset_conversation()
        return {
            "status": "ok", 
            "message": "History cleared",
            "user_id": agent.user.user_id if agent.user else None
        }
    except Exception as e:
        logger.error(f"Error in /reset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Reset error: {str(e)}")

@app.get("/info")
async def get_agent_info():
    """Получить информацию об агенте."""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent.get_agent_info()