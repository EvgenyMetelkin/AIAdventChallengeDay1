# Overview
FastAPI + SSE chat server with per-user message history, user creation/deletion, and file-based preferences.

## Imports
- `fastapi`, `fastapi.responses`, `fastapi.staticfiles`
- `uvicorn`
- `sse_starlette.sse`
- `asyncio`, `json`, `uuid`, `pathlib`, `typing`

## API

### `GET /`
Serves `index.html`.

### `GET /static/{filename}`
Serves static files from `./static`.

### `GET /users`
Returns `{"users": list[str]}`.

### `POST /users`
Body: `{"name": str, "preferences": str | None}`. Creates user with empty history, returns `{"status": "created", "user": name, "preferences": preferences}`.

### `DELETE /users/{user}`
Deletes user and their history file, returns `{"status": "deleted"}`.

### `GET /history/{user}`
Returns `{"user": user, "history": list[{"role", "content"}]}`.

### `DELETE /history/{user}`
Clears message history for user, returns `{"status": "cleared"}`.

### `POST /chat/{user}`
Body: `{"message": str}`. Streams SSE events:
- `"thinking"` event with `{"status": "thinking"}`
- `"token"` events with `{"token": str}` for each response chunk
- `"done"` event with `{"status": "done"}`

## Usage
```bash
pip install fastapi uvicorn sse-starlette
python server.py  # runs on http://localhost:8000
```

## Notes
- Static files must be in `./static/` (index.html references `/static/chat.js`).
- User data stored in `./users/{user}.json` with `{"preferences": str | null, "history": list}`.
- Server echoes user message with simulated streaming: chunks every 0.1s.
- No persistence for agent ID (always "agent-001").
- Chat history is per-user, persists across server restarts.
- Deleting a user removes their JSON file.
- Empty message or unknown user returns appropriate error responses.