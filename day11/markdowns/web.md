# Overview
FastAPI web server for an LLM agent with file upload, conversation history, and token tracking.

## Imports
- `fastapi`, `uvicorn` (implied)
- `PyPDF2`, `python-docx`, `Pillow`, `python-magic`
- `dotenv`

## API

### `@app.get("/")`
Render chat index page.

### `@app.get("/history")`
Return conversation history with attachment metadata.

### `@app.get("/stats")`
Return token usage stats.

### `@app.get("/context-stats")`
Return context management stats (message retention, summarization).

### `@app.post("/send")`
`message: str = Form("")`, `files: List[UploadFile] = File(None)` → `SendResponse`
Send user message with optional files. Returns assistant reply, history, token_stats.

### `@app.post("/reset")`
Clear conversation, delete files, reset token stats.

### `@app.get("/info")`
Return agent configuration.

## Usage
```python
from fastapi.testclient import TestClient
from web import app

client = TestClient(app)
response = client.post("/send", data={"message": "Hello"})
assert response.status_code == 200
```

## Notes
- Requires `LLM_API_KEY` in `.env`
- Files saved to `FILES_DIR` (default `agent_files`)
- Supported extensions: `txt,md,py,json,pdf,docx,jpg,png,...` (see `ALLOWED_EXTENSIONS`)
- Text extraction limited to 5000 chars per file
- Vision support depends on LLM model
- Conversation summary occurs every `SUMMARY_INTERVAL` messages
- History keeps last `KEEP_LAST_N_MESSAGES` before summarization