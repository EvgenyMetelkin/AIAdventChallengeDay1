# LLM Agent Chat with File Support & Smart Context

## Overview
FastAPI-based chat backend with token-aware context management, automatic history summarization, and multimodal file support (images, PDF, DOCX, TXT).

## Imports
- `fastapi`, `uvicorn`
- `httpx` (async OpenAI client)
- `python-multipart` (file uploads)
- `PyPDF2`, `python-docx`, `Pillow`
- `tiktoken` (token counting)

## API

### `POST /api/chat`
`async def chat(request: ChatRequest) -> ChatResponse`  
Processes user message with optional files, maintains conversation history, auto-summarizes old messages when token limit exceeded.

### `GET /api/session/reset`
`async def reset_session() -> dict`  
Clears current session history and returns `{"status": "reset"}`.

### `GET /api/session/status`
`async def session_status() -> dict`  
Returns `{"agent_id": str, "message_count": int, "summaries_count": int, "total_tokens": int}`.

### `POST /api/upload`
`async def upload_file(file: UploadFile) -> dict`  
Extracts text from supported formats, returns `{"filename": str, "content": str, "size": int, "type": str}`.

## Usage

```python
import httpx

async with httpx.AsyncClient() as client:
    # Send message
    resp = await client.post(
        "http://localhost:8000/api/chat",
        json={"message": "Hello", "history": []}
    )
    
    # Upload file
    files = {"file": ("doc.pdf", open("doc.pdf", "rb"), "application/pdf")}
    resp = await client.post("http://localhost:8000/api/upload", files=files)
```

## Notes
- Token limit: 3000 per request (configurable)
- Summarization triggered when history >2500 tokens  
- Supported files: images (OCR via pytesseract optional), PDF, DOCX, TXT, MD, PY  
- Images without OCR return metadata only  
- Large PDFs may be truncated (first 10 pages default)  
- Session history stored in memory (lost on restart)  
- Uses `gpt-3.5-turbo` (hardcoded, change in `config.py`)  
- No authentication or rate limiting implemented