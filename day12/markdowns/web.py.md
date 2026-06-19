# web.py – FastAPI chat server with multi‑user agent sessions

## Imports (non‑stdlib)
- `fastapi`, `pydantic`, `python‑dotenv`, `jinja2`

## API

### `app = FastAPI(lifespan=lifespan)`

### `GET /` – serve chat UI (index.html)
### `GET /chat.js` – serve static JS
### `GET /api/users` – list all users + current_id
### `POST /api/users` – create user (`name` form, optional `preferences` file) → auto‑switch
### `POST /api/users/{user_id}/switch` – switch active user
### `POST /api/users/{user_id}/reset` – reset user history
### `DELETE /api/users/{user_id}` – delete user (blocks if last)
### `GET /history` – current user’s history
### `POST /send` – `{"message": str}` → `{"assistant_reply": str, "history": list, "user_id": str}`
### `POST /reset` – clear current user history
### `GET /info` – agent metadata

## Usage
```python
# minimal client example
import requests
BASE = "http://localhost:8000"
r = requests.post(f"{BASE}/send", json={"message": "Hi"})
print(r.json()["assistant_reply"])
```

## Notes
- Requires `LLM_API_KEY` env var; defaults to OpenAI‑compatible endpoint.
- Users stored as JSON + history in `USERS_DIR`; agent per active user.
- Switching/resetting/deleting updates `agent.user` and saves on shutdown.
- Deleting the last user is forbidden; creation auto‑selects new user.
- Agent uses `Agent` from external `agent` module (must be importable).