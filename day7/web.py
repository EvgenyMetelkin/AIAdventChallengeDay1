import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from agent import Agent  # предполагается, что agent.py в той же папке

# Загружаем переменные окружения из .env
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Переменные окружения с значениями по умолчанию
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "500"))
VERBOSE = os.getenv("VERBOSE", "False").lower() == "true"
AGENT_ID = os.getenv("AGENT_ID", None)  # опционально, можно не задавать
HISTORY_DIR = os.getenv("HISTORY_DIR", "agent_history")

if not LLM_API_KEY:
    raise RuntimeError("LLM_API_KEY not set in environment variables")

# Глобальный объект агента (инициализируется при старте)
agent = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: создаём агента
    global agent
    agent = Agent(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        verbose=VERBOSE,
        agent_id="1",
        history_dir=HISTORY_DIR
    )
    logger.info(f"Agent initialized with ID: {agent.agent_id}")
    yield
    # Shutdown: ничего специально делать не нужно, агент уже сохранил историю
    logger.info("Shutting down, history saved automatically")

app = FastAPI(lifespan=lifespan)

# Шаблоны (папка templates)
templates = Jinja2Templates(directory="templates")

# Pydantic модели для запросов
class MessageRequest(BaseModel):
    message: str

class SendResponse(BaseModel):
    assistant_reply: str
    history: list  # полная история после ответа

# ------------------------------------------------------------
# Эндпоинты API
# ------------------------------------------------------------

@app.get("/")
async def get_index(request: Request):
    """Главная страница чата"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/history")
async def get_history():
    """Вернуть текущую историю диалога"""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return {"history": agent.conversation_history}

@app.post("/send")
async def send_message(req: MessageRequest):
    """Отправить сообщение агенту и получить ответ"""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        # Асинхронный вызов send_message
        assistant_reply = await agent.send_message(req.message)
        # Возвращаем обновлённую историю вместе с ответом
        return SendResponse(
            assistant_reply=assistant_reply,
            history=agent.conversation_history
        )
    except Exception as e:
        logger.error(f"Error in /send: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

@app.post("/reset")
async def reset_conversation():
    """Очистить историю диалога"""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        agent.reset_conversation()
        return {"status": "ok", "message": "History cleared"}
    except Exception as e:
        logger.error(f"Error in /reset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Reset error: {str(e)}")

# Дополнительный эндпоинт для информации об агенте (опционально)
@app.get("/info")
async def get_agent_info():
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent.get_agent_info()