# AGENTS.md

## Repo layout

Multi-day challenge repo. Each `dayN/` is an independent project with its own `venv/`, `requirements.txt`, and source files. No shared code between days. Current working directory is `day16/`.

## Day 16 — AI Chat (FastAPI)

### Run the app

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

`python main.py` does NOT work — there is no `__name__ == "__main__"` guard.

### Install deps

```bash
pip install -r requirements.txt
```

### No tests, no lint, no typecheck

Day 16 has zero tests and no linter/formatter/typechecker config. Other days (e.g. day15) have pytest suites.

### Environment (`.env`)

- `.env` contains a real API key. **Never commit it.** The root `.gitignore` covers `.env`, but verify before staging.
- `SECRET_KEY` defaults to `uuid.uuid4().hex` at startup — all sessions are invalidated on restart unless `SECRET_KEY` is set in `.env`.
- Default API: DeepSeek (`https://api.deepseek.com`, model `deepseek-v4-flash`). Works with any OpenAI-compatible endpoint.

### API quirks

- Chat endpoints use `Form(...)` (multipart/form-data), **not** JSON. The JS frontend sends via `FormData()`.
- The `/api/switch` endpoints send `application/x-www-form-urlencoded`, not multipart. FastAPI's `Form()` handles both.

### Persistence

- Users/agents stored as JSON files under `users/{user_id}/settings.json` and `users/{user_id}/agents.json`.
- **No file locking** on reads/writes. Concurrent requests to the same user may corrupt data.
- `init_demo()` runs at module import time (not on first request). Creates a "demo" user if `users/` is empty.

### Framework notes

- FastAPI with Jinja2 templates, starlette `SessionMiddleware`.
- SSE streaming via `StreamingResponse` with `text/event-stream`.
- LLM calls via `httpx.AsyncClient` to the `/chat/completions` OpenAI-compatible endpoint.
- No CSRF protection. No structured logging (only optional `verbose` print).
