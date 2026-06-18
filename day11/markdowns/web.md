# web.py - FastAPI chat server for Agent

## Overview
FastAPI web server exposing chat endpoints for an LLM agent with conversation history management.

## Imports
- `fastapi`, `uvicorn` (server)
- `jinja2` (templating)
- `pydantic` (validation)
- `python-dotenv` (env loading)
- `agent` (local module)

## API

### `app = FastAPI(lifespan=lifespan)`
Main application instance.

### `GET /` → HTML chat interface
Serves `templates/index.html`.

### `GET /chat.js` → JavaScript client
Serves `static/chat.js`.

### `GET /history` → `{"history": list}`
Returns full conversation history.

### `POST /send` → `{"assistant_reply": str, "history": list}`
Request body: `{"message": str}`. Sends user message to agent.

### `POST /reset` → `{"status": "ok", "message": str}`
Clears conversation history.

### `GET /info` → Agent metadata
Returns `agent.get_agent_info()`.

## Usage
```python
from web import app
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Notes
- Requires `.env` with `LLM_API_KEY` (mandatory). Optional: `LLM_BASE_URL`, `LLM_MODEL`, `TEMPERATURE`, `MAX_TOKENS`, `VERBOSE`, `AGENT_ID`, `HISTORY_DIR`.
- Agent initialized on startup via `lifespan`. History auto-saves to `HISTORY_DIR` on shutdown.
- Static files must exist at `static/chat.js` and templates at `templates/index.html`.
- `/send` and `/reset` return 503 if agent not initialized.
- Agent class assumed from `agent.py` with `send_message`, `reset_conversation`, `conversation_history`, `get_agent_info`.