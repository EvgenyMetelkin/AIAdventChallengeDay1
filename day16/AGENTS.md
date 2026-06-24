# AGENTS.md

Don't use skills.

## Day 16 — AI Chat (FastAPI + MCP)

### Run the app

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

`python main.py` does **not** work — no `__name__ == "__main__"` guard. `load_dotenv()` and `init_demo()` run at module import time.

### Install deps

```bash
pip install -r requirements.txt
```

`python-dotenv` is **missing** from `requirements.txt` but is imported by `main.py`. Install it manually if venv doesn't already have it.

### No tests, no lint, no typecheck

Day 16 has zero tests and no linter/formatter/typechecker config.

### Environment (`.env`)

- `.env` contains a real API key. **Never commit it.** Root `.gitignore` covers `.env`, but verify before staging.
- `SECRET_KEY` defaults to `uuid.uuid4().hex` — all sessions invalidated on restart unless `SECRET_KEY` is set in `.env`.
- Env vars: `OPENAI_API_KEY` (required), `OPENAI_BASE_URL` (defaults to `https://api.openai.com/v1`), model defaults to `deepseek-v4-flash` in `user.py`. Works with any OpenAI-compatible endpoint.
- `VERBOSE` — set to `"true"` to enable debug logging in agent and MCP client.

### API quirks

- Chat endpoint (`/api/chat/stream`) uses `Form(...)` (multipart/form-data), **not** JSON. The JS frontend sends via `FormData()`.
- `/api/switch` and `/api/settings` use `application/x-www-form-urlencoded`. FastAPI's `Form()` handles both.

### MCP (Model Context Protocol)

- MCP client in `mcp_client.py` supports three transports: `streamable_http`, `sse`, `stdio`.
- Config persisted in `mcp_config.json` (no file locking — concurrent admin requests may corrupt).
- MCP connection is attempted at startup if `MCP_SERVER_URL` env var or `mcp_config.json` is set. Connection failure is non-fatal (app continues without tools).
- When MCP is connected, chat automatically enables tool calling via `agent.chat_with_tools()` (10-iteration tool loop max).
- Admin panel at `/admin` for managing MCP connection, users, and agents.

### Persistence

- Users/agents stored as JSON files under `users/{user_id}/settings.json` and `users/{user_id}/agents.json`.
- **No file locking** on reads/writes. Concurrent requests to the same user may corrupt data.
- `init_demo()` runs at module import time. Creates a "demo" user if `users/` is empty.

### Framework notes

- FastAPI with Jinja2 templates, starlette `SessionMiddleware`.
- SSE streaming via `StreamingResponse` with `text/event-stream`.
- LLM calls via `httpx.AsyncClient` to the `/chat/completions` OpenAI-compatible endpoint.
- No CSRF protection. No structured logging (only optional `verbose` print).
