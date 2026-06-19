# AGENTS.md — LLM Agent Web Chat

Async web chat for OpenAI-compatible LLM APIs with multi-user, multi-agent sessions.

## Build / Test / Lint

```bash
# Install deps
pip install -r requirements.txt

# Run web server
uvicorn web:app --reload --host 0.0.0.0 --port 8000

# Run CLI
python cli.py "Your question"
python cli.py --interactive --user "MyName"

# Run all tests
python -m pytest test_agent.py -v

# Run a single test class
python -m pytest test_agent.py::TestAgentSendMessage -v

# Check syntax (no test runner needed)
python -m py_compile agent.py user.py web.py cli.py utils.py
```

No linter/formatter is configured. Dependencies: `fastapi`, `uvicorn`, `httpx`, `python-dotenv`, `jinja2`, `python-multipart`.

## Architecture

The project is a **single-process FastAPI web app** with an in-process CLI. No database — all state is filesystem-based under `users/`.

### Component Tree

```
cli.py ─── CLI entrypoint (argparse → Agent + User)
web.py ─── FastAPI server (17 endpoints, SSE streaming, AppState DI)
  ├── AppState     — thread-safe container (asyncio.Lock) for users + agent
  ├── ContextVar   — per-request current_user_id
  └── _resolve_user() — user lookup: explicit ID > context var > first user
agent.py ── LLM HTTP client (httpx)
  ├── send_message()             — full request-response with history
  ├── send_message_without_history() — stateless request (used for summaries)
  └── send_message_stream()      — AsyncGenerator, SSE tokens from streaming API
user.py ── User model + persistence
  ├── User dataclass — preferences (STYLE/CONSTRAINTS/CONTEXT), agents[], working_memory[]
  ├── switch_agent() — generates LLM summary → working_memory
  ├── save/load methods — atomic writes via _atomic_write_json/text (.tmp + os.replace)
  └── threading.Lock — per-User lock on all save operations
utils.py ── Markdown preference parser, summary generator
static/chat.js ── Vanilla JS SPA (755 lines)
  ├── User/agent CRUD modals
  ├── sendMessageStream() — ReadableStream SSE consumer
  └── working memory panel (toggle, clear)
templates/index.html ── Jinja2 template (CSS in static/style.css)
test_agent.py ── 19 tests, 5 classes, mock User fixture
```

### Data Flow

```
Browser (SSE/JSON) → web.py /send or /send/stream
  → AppState.get_agent() → Agent.send_message()
    → User.get_system_prompt() + User.get_current_history()
      → httpx POST → LLM API
        → response saved to User.agents[id].history[]
          → User.save_agents() (atomic, locked)
```

### Filesystem Layout

```
users/
└── {user_id}/
    ├── preferences.md          # ## STYLE / ## CONSTRAINTS / ## CONTEXT
    ├── working_memory.json     # {"summaries": ["..."]}
    └── agents/
        └── {agent_id}/
            ├── metadata.json   # {"name":"...","created":"..."}
            └── history.json    # [{"role":"user/assistant","content":"..."}]
```

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `web.py` | Server entrypoint, all endpoints, AppState, CORS, lifespan |
| `agent.py` | LLM API client: send, stream, error handling |
| `user.py` | User/agent persistence, atomic I/O, locks |
| `cli.py` | CLI with `--user`, `--user-id`, `--preferences` flags |
| `utils.py` | MD parsing (`## STYLE` regex), `generate_summary()` |
| `static/chat.js` | Frontend SPA |
| `static/style.css` | Extracted CSS (453 lines) |
| `templates/index.html` | Jinja2 shell, `<link>` to style.css |
| `test_agent.py` | 19 pytest-asyncio tests with `MagicMock` fixtures |
| `requirements.txt` | Pinned deps |
| `.env.example` | Template for `LLM_API_KEY`, model, etc. |
| `markdowns/` | Legacy markdown docs (not used by the app) |
| `agent_history/` | Deprecated history dir (superseded by `users/`) |

## Coding Conventions

- **Python 3.9+**, async/await throughout
- **Error handling**: generic `Exception` with descriptive messages; HTTP errors extract `error.message` from JSON body
- **Mocking in tests**: use `MagicMock` for sync methods (`.json()`, `.raise_for_status()`), `AsyncMock` for async generators (`.aiter_lines()`)
- **User fixture**: create `User(...)` with `save_*` methods mocked to `MagicMock()` — avoids filesystem dependencies
- **AppState pattern**: all endpoints receive `state: AppState = Depends(get_state)`; state access is always `await state.get_agent()` etc.
- **Atomic writes**: never write directly — use `_atomic_write_json(path, data)` / `_atomic_write_text(path, content)` from `user.py`
- **Naming**: functions `snake_case`, classes `PascalCase`, JS functions `camelCase`, Russian comments
- **No framework** on the frontend — vanilla JS, `escapeHtml` via `textContent`

## Git Workflow

- Branch: `main` (single-branch)
- Commits: Russian-titled, format `Day N. Description`
- Remote: `https://github.com/EvgenyMetelkin/AIAdventChallengeDay1.git`

## Tips for AI Agents

- **Tests must mock `User.save_*` methods** or they'll hit the filesystem. Use the `mock_user` fixture pattern from `test_agent.py`.
- **`httpx.Response.json()` is sync**, not async. Mock it with `MagicMock`, not `AsyncMock`.
- **Streaming endpoint** (`/send/stream`) returns `text/event-stream`; the frontend `sendMessageStream()` consumes it via `response.body.getReader()`.
- **AppState is a global singleton** (`app_state = AppState()` at module level) — initialized in `lifespan`, injected via `Depends`. Never create a second instance.
- **User switching** is done by `agent.set_user(user)` — this mutates the shared Agent. The `/send` endpoint resolves the user fresh per-request via `_resolve_user()`.
- **CLI creates users on disk** under `users/` — it shares the same `User` persistence layer as the web server.
- **`.env.example`** uses `deepseek-v4-flash` as default model; the codebase is OpenAI-API compatible.
- **`os.replace()`** is used for atomic writes — it's atomic on POSIX but not on Windows (use `os.rename` fallback if cross-platform is needed).
