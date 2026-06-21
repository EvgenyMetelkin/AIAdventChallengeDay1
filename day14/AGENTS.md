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

# Run all tests (19 tests, 5 classes)
python -m pytest test_agent.py -v

# Run swarm tests (38 tests)
python -m pytest test_swarm.py -v

# Run all tests (57 total)
python -m pytest test_agent.py test_swarm.py -v

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
web.py ─── FastAPI server (26 endpoints, SSE streaming, AppState DI)
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
swarm.py ── Swarm orchestrator (4-stage pipeline: Planning→Execution→Validation→Done)
  ├── SwarmStage — enum for 11 task states
  ├── SwarmTask — dataclass with stage results, progress tracking
  ├── SwarmOrchestrator — task lifecycle manager, pause/resume, artifact persistence
  └── Specialized system prompts for Planner, Executor, Validator, Finisher agents
static/chat.js ── Vanilla JS SPA (1010 lines, VS Code IDE UI)
  ├── Activity bar, sidebar explorer, tab bar, bottom panel, status bar
  ├── sendMessageStream() — ReadableStream SSE consumer
  └── User/agent CRUD, working memory panel
templates/index.html ── Jinja2 template (CSS in static/style.css, 1037 lines)
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

### Swarm Mode Data Flow

```
Browser → /api/swarm/create → SwarmOrchestrator.create_task()
  → /api/swarm/tasks/{id}/action (start_planning)
    → Planner system prompt + user description → _run_agent() → LLM
      → plan saved to users/{uid}/swarms/{tid}/planning/plan.md
  → (user approves) → start_execution → Executor agent
    → execution_report.md
  → (user approves) → start_validation → Validator agent
    → validation_report.md
  → (user approves) → finish → Finisher agent
    → final_report.md in users/{uid}/swarms/{tid}/done/
State persisted in users/{uid}/swarms/{tid}/state.json at every transition.
```

### Filesystem Layout

```
users/
└── {user_id}/
    ├── preferences.md          # ## STYLE / ## CONSTRAINTS / ## CONTEXT
    ├── working_memory.json     # {"summaries": ["..."], "updated_at": "..."}
    ├── agents/
    │   └── {agent_id}/
    │       ├── metadata.json   # {"name":"...","created":"..."}
    │       └── history.json    # [{"role":"user/assistant","content":"..."}]
    └── swarms/
        └── {task_id}/
            ├── state.json      # task state, stage results, progress
            ├── planning/
            │   └── plan.md
            ├── execution/
            │   └── execution_report.md
            ├── validation/
            │   └── validation_report.md
            └── done/
                └── final_report.md
```

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `web.py` | Server entrypoint (735 lines), 19 endpoints, AppState, CORS, lifespan |
| `agent.py` | LLM API client (343 lines): send, stream, error handling |
| `user.py` | User/agent persistence (469 lines), atomic I/O, locks |
| `cli.py` | CLI with `--user`, `--user-id`, `--preferences` flags |
| `utils.py` | MD parsing (`## STYLE` regex), `generate_summary()` |
| `static/chat.js` | Frontend SPA (1010 lines) — IDE-style interface |
| `static/style.css` | VS Code Dark+ theme (1037 lines) |
| `templates/index.html` | Jinja2 shell, `<link>` to style.css |
| `test_agent.py` | 19 pytest-asyncio tests with `MagicMock` fixtures |
| `test_swarm.py` | 38 tests for swarm orchestrator, stages, pause/resume |
| `requirements.txt` | Pinned deps (6 packages) |
| `.env.example` | Template for `LLM_API_KEY`, model, etc. |
| `markdowns/` | Legacy markdown docs (not used by the app) |
| `agent_history/` | Deprecated history dir (superseded by `users/`) |

## Web API (19 endpoints)

- `GET /` — render IDE page
- `GET/POST /api/users` — list / create users
- `POST /api/users/{id}/switch` — switch active user
- `POST /api/users/{id}/reset` — reset user history
- `DELETE /api/users/{id}` — delete user (cannot delete last)
- `GET/POST /api/agents` — list / create agents
- `POST /api/agents/{id}/switch` — switch agent (generates LLM summary → working memory)
- `DELETE /api/agents/{id}` — delete agent (cannot delete last)
- `GET/DELETE /api/working_memory` — read / clear working memory
- `GET /history` — current agent's conversation history
- `POST /send` — non-streaming message
- `POST /send/stream` — SSE streaming message (`text/event-stream`)
- `POST /reset` — clear conversation
- `GET /api/status` — status bar summary
- `GET /info` — agent info
- `POST /api/swarm/create` — create a new swarm task
- `GET /api/swarm/tasks` — list swarm tasks
- `GET /api/swarm/tasks/{id}` — get task state
- `POST /api/swarm/tasks/{id}/action` — execute action (start_planning, approve_plan, etc.)
- `DELETE /api/swarm/tasks/{id}` — delete task
- `GET /api/swarm/tasks/{id}/artifacts` — list stage artifacts
- `GET /api/swarm/tasks/{id}/artifacts/{stage}/{file}` — read artifact content

## Coding Conventions

- **Python 3.9+**, async/await throughout
- **Error handling**: generic `Exception` with descriptive messages; HTTP errors extract `error.message` from JSON body
- **Mocking in tests**: use `MagicMock` for sync methods (`.json()`, `.raise_for_status()`), `AsyncMock` for async generators (`.aiter_lines()`)
- **User fixture**: create `User(...)` with `save_*` methods mocked to `MagicMock()` — avoids filesystem dependencies
- **AppState pattern**: all endpoints receive `state: AppState = Depends(get_state)`; state access is always `await state.get_agent()` etc.
- **Atomic writes**: never write directly — use `_atomic_write_json(path, data)` / `_atomic_write_text(path, content)` from `user.py`
- **Naming**: functions `snake_case`, classes `PascalCase`, JS functions `camelCase`, Russian comments
- **No framework** on the frontend — vanilla JS, `escapeHtml` via `textContent`
- **Working memory**: triggered on agent switch; `User.switch_agent()` calls `generate_summary()` which uses `send_message_without_history()` to produce an LLM summary saved to `working_memory.json`

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
- **Agent switch generates an LLM summary** via `send_message_without_history()` — this can fail if the API is down, leaving a `[Summary not generated: ...]` fallback string in working memory.
- **Last user/agent cannot be deleted** — the API returns 400.
- **The test suite uses `pytest-asyncio`** with `mode=strict`; all async tests must be decorated with `@pytest.mark.asyncio`.
- **`users/` and `agent_history/` are both gitignored** — no test data leaks into version control.
- **Swarm tasks persist under `users/{uid}/swarms/`** — each task has its own directory with stage subdirectories and a `state.json`. The orchestrator loads all tasks on startup via `load_all_tasks()`.
- **Swarm tests mock `_run_agent` directly** — don't mock `httpx.AsyncClient` for swarm tests; assign a fake async function to `orchestrator._run_agent` instead. Use the `_RunAgentMock` context manager or try/finally pattern.
