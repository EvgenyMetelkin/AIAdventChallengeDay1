import os
import logging
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv
from agent import Agent
import magic
import PyPDF2
import docx
from io import BytesIO
from PIL import Image
import uuid
import json

# Загружаем переменные окружения из .env
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Переменные окружения
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "500"))
VERBOSE = os.getenv("VERBOSE", "False").lower() == "true"
AGENT_ID = os.getenv("AGENT_ID", None)
HISTORY_DIR = os.getenv("HISTORY_DIR", "agent_history")
FILES_DIR = os.getenv("FILES_DIR", "agent_files")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
ALLOWED_EXTENSIONS = os.getenv("ALLOWED_EXTENSIONS", "jpg,jpeg,png,gif,txt,pdf,docx").split(',')

if not LLM_API_KEY:
    raise RuntimeError("LLM_API_KEY not set in environment variables")

# Глобальный объект агента
agent = None

def extract_text_from_pdf(file_content: bytes) -> str:
    """Извлечение текста из PDF файла."""
    try:
        pdf_reader = PyPDF2.PdfReader(BytesIO(file_content))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text
        return text[:5000]  # Ограничиваем длину
    except Exception as e:
        logger.error(f"Error extracting PDF text: {str(e)}")
        return f"[Ошибка извлечения текста из PDF: {str(e)}]"

def extract_text_from_docx(file_content: bytes) -> str:
    """Извлечение текста из DOCX файла."""
    try:
        doc = docx.Document(BytesIO(file_content))
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs if paragraph.text])
        return text[:5000]  # Ограничиваем длину
    except Exception as e:
        logger.error(f"Error extracting DOCX text: {str(e)}")
        return f"[Ошибка извлечения текста из DOCX: {str(e)}]"

def extract_text_from_txt(file_content: bytes) -> str:
    """Извлечение текста из TXT файла."""
    try:
        text = file_content.decode('utf-8')
        return text[:5000]  # Ограничиваем длину
    except UnicodeDecodeError:
        try:
            text = file_content.decode('cp1251')
            return text[:5000]
        except Exception as e:
            return f"[Ошибка декодирования текстового файла: {str(e)}]"

def process_image_for_preview(file_content: bytes, filename: str, files_dir: str) -> Optional[str]:
    """Создание превью для изображения и сохранение."""
    try:
        img = Image.open(BytesIO(file_content))
        # Создаем миниатюру
        img.thumbnail((200, 200))
        preview_filename = f"preview_{uuid.uuid4().hex}_{filename}"
        preview_path = os.path.join(files_dir, preview_filename)
        img.save(preview_path, optimize=True, quality=85)
        return preview_path
    except Exception as e:
        logger.error(f"Error creating image preview: {str(e)}")
        return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    agent = Agent(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        verbose=VERBOSE,
        agent_id=AGENT_ID or "1",
        history_dir=HISTORY_DIR,
        files_dir=FILES_DIR,
        max_file_size_mb=MAX_FILE_SIZE_MB
    )
    logger.info(f"Agent initialized with ID: {agent.agent_id}, supports_vision: {agent.supports_vision}")
    yield
    logger.info("Shutting down, history saved automatically")

app = FastAPI(lifespan=lifespan)

# Монтируем статические файлы для доступа к загруженным файлам
if os.path.exists(FILES_DIR):
    app.mount("/files", StaticFiles(directory=FILES_DIR), name="files")

templates = Jinja2Templates(directory="templates")

# Pydantic модели
class MessageRequest(BaseModel):
    message: str
    files: Optional[List[dict]] = None

class SendResponse(BaseModel):
    assistant_reply: str
    history: list
    token_stats: dict

# ------------------------------------------------------------
# Эндпоинты API
# ------------------------------------------------------------

@app.get("/")
async def get_index(request: Request):
    """Главная страница чата"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/history")
async def get_history():
    """Вернуть текущую историю диалога с обработкой вложений"""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    # Форматируем историю для фронтенда
    formatted_history = []
    for msg in agent.conversation_history:
        formatted_msg = {
            "role": msg.get("role", "unknown"),
            "content": msg.get("content", "")
        }
        
        # Добавляем информацию о токенах для сообщений ассистента
        if msg.get("role") == "assistant" and msg.get("tokens"):
            formatted_msg["tokens"] = msg["tokens"]
        
        # Добавляем информацию о вложениях для пользовательских сообщений
        if msg.get("role") == "user" and "attachments" in msg and msg["attachments"]:
            formatted_msg["attachments"] = []
            for att in msg["attachments"]:
                attachment_info = {
                    "filename": att.get("filename", "unknown"),
                    "mime_type": att.get("mime_type", "application/octet-stream"),
                    "size_bytes": att.get("size_bytes", 0),
                }
                
                # Добавляем URL для превью, если файл существует
                saved_path = att.get("saved_path")
                if saved_path and os.path.exists(saved_path):
                    # Создаем относительный URL для статической раздачи
                    rel_path = os.path.relpath(saved_path, FILES_DIR)
                    attachment_info["url"] = f"/files/{rel_path}"
                    
                    # Если это изображение, добавляем превью
                    if att.get("mime_type", "").startswith("image/"):
                        attachment_info["is_image"] = True
                        attachment_info["preview_url"] = f"/files/{rel_path}"
                
                if att.get("extracted_text"):
                    attachment_info["extracted_text_preview"] = att["extracted_text"][:200]
                
                formatted_msg["attachments"].append(attachment_info)
        
        formatted_history.append(formatted_msg)
    
    return {"history": formatted_history}

@app.get("/stats")
async def get_token_stats():
    """Вернуть текущую статистику использования токенов"""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent.get_token_stats()

@app.post("/send")
async def send_message(
    message: str = Form(""),
    files: List[UploadFile] = File(None)
):
    """Отправить сообщение агенту с возможностью прикрепления файлов"""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        processed_files = []
        
        if files:
            for file in files:
                # Проверка размера файла
                file_content = await file.read()
                file_size_mb = len(file_content) / (1024 * 1024)
                
                if file_size_mb > agent.max_file_size_mb:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Файл {file.filename} превышает максимальный размер {agent.max_file_size_mb}MB"
                    )
                
                # Определение MIME типа
                mime = magic.from_buffer(file_content[:1024], mime=True)
                file_extension = file.filename.split('.')[-1].lower()
                
                # Проверка разрешенных типов
                if file_extension not in ALLOWED_EXTENSIONS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Тип файла {file_extension} не поддерживается. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}"
                    )
                
                # Сохраняем файл
                unique_filename = f"{uuid.uuid4().hex}_{file.filename}"
                saved_path = os.path.join(agent.agent_files_dir, unique_filename)
                
                # Создаем директорию если не существует
                os.makedirs(agent.agent_files_dir, exist_ok=True)
                
                with open(saved_path, "wb") as f:
                    f.write(file_content)
                
                file_info = {
                    "filename": file.filename,
                    "mime_type": mime,
                    "size_bytes": len(file_content),
                    "saved_path": saved_path,
                }
                
                # Извлечение текста для документов
                if mime == "application/pdf" or file_extension == "pdf":
                    extracted_text = extract_text_from_pdf(file_content)
                    if extracted_text:
                        file_info["extracted_text"] = extracted_text
                        file_info["content"] = extracted_text  # Добавляем для совместимости
                
                elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or file_extension == "docx":
                    extracted_text = extract_text_from_docx(file_content)
                    if extracted_text:
                        file_info["extracted_text"] = extracted_text
                        file_info["content"] = extracted_text
                
                elif mime.startswith("text/") or file_extension == "txt":
                    extracted_text = extract_text_from_txt(file_content)
                    if extracted_text:
                        file_info["extracted_text"] = extracted_text
                        file_info["content"] = extracted_text
                
                elif mime.startswith("image/"):
                    # Создаем превью для изображений
                    preview_path = process_image_for_preview(file_content, file.filename, agent.agent_files_dir)
                    if preview_path:
                        file_info["preview_path"] = preview_path
                        file_info["content"] = f"[Изображение: {file.filename}]"
                
                processed_files.append(file_info)
        
        # Отправляем сообщение агенту
        user_message = message if message else ""
        
        logger.info(f"Sending to agent: message='{user_message}', files={len(processed_files)}")
        
        # Получаем ответ и статистику токенов
        assistant_reply, token_stats = await agent.send_message(
            user_message=user_message,
            files=processed_files if processed_files else None
        )
        
        # Форматируем историю для ответа
        formatted_history = []
        for msg in agent.conversation_history:
            formatted_msg = {
                "role": msg.get("role", "unknown"),
                "content": msg.get("content", "")
            }
            
            # Добавляем информацию о токенах
            if msg.get("role") == "assistant" and msg.get("tokens"):
                formatted_msg["tokens"] = msg["tokens"]
            
            if msg.get("role") == "user" and "attachments" in msg and msg["attachments"]:
                formatted_msg["attachments"] = []
                for att in msg["attachments"]:
                    att_info = {
                        "filename": att.get("filename", "unknown"),
                        "mime_type": att.get("mime_type", "application/octet-stream"),
                        "size_bytes": att.get("size_bytes", 0),
                    }
                    saved_path = att.get("saved_path")
                    if saved_path and os.path.exists(saved_path):
                        rel_path = os.path.relpath(saved_path, FILES_DIR)
                        att_info["url"] = f"/files/{rel_path}"
                        if att.get("mime_type", "").startswith("image/"):
                            att_info["is_image"] = True
                            att_info["preview_url"] = f"/files/{rel_path}"
                    formatted_msg["attachments"].append(att_info)
            formatted_history.append(formatted_msg)
        
        return SendResponse(
            assistant_reply=assistant_reply,
            history=formatted_history,
            token_stats=token_stats
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /send: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

@app.post("/reset")
async def reset_conversation():
    """Очистить историю диалога, удалить файлы и обнулить статистику токенов"""
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        agent.reset_conversation()
        return {"status": "ok", "message": "History cleared and token stats reset"}
    except Exception as e:
        logger.error(f"Error in /reset: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Reset error: {str(e)}")

@app.get("/info")
async def get_agent_info():
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent.get_agent_info()