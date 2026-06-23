# AGENTS.md — LLM Agent Web Chat (Day 15)

Async web chat for OpenAI-compatible LLM APIs with multi-user, multi-agent sessions,
Swarm multi-stage task orchestrator, and invariant enforcement.

## Build / Test / Lint

```bash
# Install deps
pip install -r requirements.txt

# Run web server
uvicorn web:app --reload --host 0.0.0.0 --port 8000

# Run CLI
python cli.py "Your question"
python cli.py --interactive --user "MyName"

# Run all tests (85 total: 66 swarm + 19 agent)
python -m pytest test_agent.py test_swarm.py -v

# Run a single test class
python -m pytest test_swarm.py::TestOrchestratorInvariants -v

# Check syntax
python -m py_compile agent.py user.py web.py cli.py utils.py swarm.py
```

No linter/formatter. Dependencies: `fastapi`, `uvicorn`, `httpx`, `python-dotenv`, `jinja2`, `python-multipart`.

## Architecture

Single-process **FastAPI web app** with in-process CLI. No database — all state is filesystem-based under `users/`.

### Component Tree

```
cli.py ─── CLI entrypoint (argparse → Agent + User)
web.py ─── FastAPI server (28 endpoints, SSE streaming, AppState DI)
  ├── AppState     — thread-safe container (asyncio.Lock) for users + agent + swarm
  ├── ContextVar   — per-request current_user_id
  └── _resolve_user() — user lookup: explicit ID > context var > first user
agent.py ── LLM HTTP client (httpx, ~340 lines)
  ├── send_message()             — full request-response with history
  ├── send_message_without_history() — stateless request (summaries, invariant checks)
  └── send_message_stream()      — AsyncGenerator, SSE tokens from streaming API
user.py ── User model + persistence (~470 lines)
  ├── User dataclass — preferences (## STYLE/CONSTRAINTS/CONTEXT), agents[], working_memory[]
  ├── switch_agent() — generates LLM summary → working_memory
  ├── save/load methods — atomic writes via _atomic_write_json/text (.tmp + os.replace)
  └── threading.Lock — per-User lock on all save operations
utils.py ── Markdown parser + invariants formatter (~210 lines)
  ├── parse_preferences_md() / format_preferences_md()
  ├── parse_invariants_md() — bullet or line-by-line fallback
  ├── format_invariants_prompt() — injects invariants into agent system prompts
  ├── format_invariant_check_prompt() — prompt for violation-checking LLM call
  └── generate_summary() — LLM-powered conversation summary
swarm.py ── Swarm orchestrator (~1370 lines)
  ├── SwarmStage — 12 states: IDLE, PLANNING, PLAN_REVIEW, EXECUTING, EXEC_REVIEW,
  │                VALIDATING, VALIDATION_REVIEW, FINISHING, DONE, PAUSED, CANCELLED, FAILED
  ├── SwarmTask — dataclass with invariants[], stage_checks{}, progress tracking
  ├── StageResult — per-stage artifact, status, error, invariant check result
  ├── SwarmOrchestrator — task lifecycle, pause/resume/retry/restart, invariant enforcement
  ├── _ensure_invariants() — reloads invariants from file if task.invariants is empty
  ├── _check_invariants() — separate LLM call to validate artifact against invariants
  └── 5 specialized system prompts (Planner, Executor, Validator, Finisher, InvariantChecker)
static/chat.js ── Vanilla JS SPA (~1980 lines, VS Code IDE UI)
  ├── Activity bar, sidebar (explorer/swarm/settings), tab bar, bottom panel, status bar
  ├── sendMessageStream() — ReadableStream SSE consumer
  ├── Swarm view: stages, progress bar, artifacts viewer, invariant checks display
  └── User/agent CRUD, invariants editor, working memory panel
templates/index.html ── Jinja2 template (~340 lines, CSS in static/style.css ~1730 lines)
test_agent.py ── 19 tests, 6 classes, mock User fixture
test_swarm.py ── 66 tests, 12 classes (including 3 invariant-specific classes)
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

### Swarm + Invariants Data Flow

```
Browser → /api/swarm/create
  → loads invariants from users/{uid}/invariants.md
  → creates SwarmTask with invariants[] frozen in state.json

For each stage (Planning → Execution → Validation → Finishing):
  → _ensure_invariants(task) — reload from file if empty
  → _run_agent(system_prompt, user_msg, invariants=invs)
    → invariants injected into system prompt before LLM call
  → _check_invariants(invs, artifact_text, stage_name)
    → separate LLM call with INVARIANT_CHECKER_SYSTEM_PROMPT
    → if violations found: stage → FAILED, _failed_stage recorded
    → if checker LLM fails: passed=True, checker_error logged (non-blocking)

restart_stage clears the failed stage AND all downstream stages.
retry_stage clears invariant checks for the retried stage and downstream.
```

### Filesystem Layout

```
users/
└── {user_id}/
    ├── preferences.md          # ## STYLE / ## CONSTRAINTS / ## CONTEXT
    ├── invariants.md           # Invariant rules (bullet list or plain text)
    ├── working_memory.json     # {"summaries": ["..."], "updated_at": "..."}
    ├── agents/
    │   └── {agent_id}/
    │       ├── metadata.json   # {"name":"...","created":"..."}
    │       └── history.json    # [{"role":"user/assistant","content":"..."}]
    └── swarms/
        └── {task_id}/
            ├── state.json      # task state, stages, invariants[], stage_checks{}
            ├── planning/plan.md
            ├── execution/execution_report.md
            ├── validation/validation_report.md
            └── done/final_report.md
```

## Web API (28 endpoints)

- `GET /` — render IDE page
- `GET /chat.js` — serve frontend JS
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
- `GET /api/invariants` — read user invariants from `invariants.md`
- `PUT /api/invariants` — update user invariants (atomic write)
- `POST /api/swarm/create` — create swarm task (loads user invariants)
- `GET /api/swarm/tasks` — list swarm tasks (filterable by user_id)
- `GET /api/swarm/tasks/{id}` — get task state with progress, stage_checks
- `POST /api/swarm/tasks/{id}/action` — execute action (see actions below)
- `DELETE /api/swarm/tasks/{id}` — delete task
- `GET /api/swarm/tasks/{id}/artifacts` — list stage artifacts
- `GET /api/swarm/tasks/{id}/artifacts/{stage}/{file}` — read artifact content

**Swarm actions**: `start_planning`, `approve_plan`, `reject_plan`, `start_execution`,
`approve_execution`, `reject_execution`, `start_validation`, `approve_validation`,
`reject_validation`, `finish`, `pause`, `resume`, `retry`, `restart_stage`, `cancel`,
`user_input`, `refine_plan`

## Coding Conventions

- **Python 3.9+**, async/await throughout
- **Error handling**: generic `Exception` with descriptive messages; HTTP errors extract `error.message` from JSON body. Stage LLM failures **do not re-raise** — they save failure state and return the task (200 OK with failed stage).
- **Mocking in tests**: `MagicMock` for sync methods, `AsyncMock` for async generators. Swarm tests mock `orchestrator._run_agent` directly (never mock `httpx.AsyncClient`).
- **Mock signatures**: `_run_agent` takes 3 args: `system_prompt, user_message, invariants=None`. Always include `invariants=None` in mock functions.
- **Atomic writes**: use `_atomic_write_json(path, data)` / `_atomic_write_text(path, content)` from `user.py`. Uses `.tmp + os.replace()`.
- **Naming**: functions `snake_case`, classes `PascalCase`, JS `camelCase`, Russian comments
- **No framework** on frontend — vanilla JS, `escapeHtml` via `textContent`
- **AppState**: global singleton injected via `Depends(get_state)`. Never create a second instance.

## Git Workflow

- Branch: `main` (single-branch)
- Commits: Russian-titled, format `Day N. Description`
- Remote: `https://github.com/EvgenyMetelkin/AIAdventChallengeDay1.git`

## Tips for AI Agents

- **Invariants file format**: `users/{uid}/invariants.md`. Supports bullet lists (`- rule`) or plain text (one rule per line). Parsed by `parse_invariants_md()` with fallback.
- **Invariants are frozen at task creation**: copied to `state.json`. Editing `invariants.md` via UI only affects new tasks. Existing tasks keep their frozen copy unless `_ensure_invariants` reloads (triggers when `task.invariants` is empty).
- **Invariant check is non-blocking for checker failures**: if the checker LLM times out, `_check_invariants` returns `passed: True` with `checker_error` — the pipeline proceeds.
- **`restart_stage` clears downstream stages**: restarting `execution` clears `validation` and `finishing` too. `retry_stage` clears invariant checks for the retried stage and downstream.
- **Stage LLM failures return 200 (not 500)**: exception handlers in stage methods no longer re-raise. Task is returned with `status: "failed"` and `error` field.
- **Swarm tests mock `_run_agent` with 3-arg signature**: `async def fake(sp, um, invariants=None)`. Use `_RunAgentMock` context manager or try/finally pattern. The `_check_invariants` call doubles LLM calls per stage — mock accordingly.
- **`httpx.Response.json()` is sync**, not async. Mock with `MagicMock`.
- **Streaming endpoint**: `/send/stream` returns `text/event-stream`; frontend consumes via `response.body.getReader()`.
- **User switching**: `agent.set_user(user)` mutates shared Agent. `/send` resolves user per-request via `_resolve_user()`.
- **Last user/agent cannot be deleted** — API returns 400.
- **`users/` and `agent_history/` are gitignored**.
- **`.env.example`** uses `deepseek-v4-flash` as default; codebase is OpenAI-API compatible.
- **`.env.example` uses `LLM_` prefix** (`LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_TIMEOUT`, `LLM_VERBOSE`) for CLI env vars. `web.py` reads **unprefixed** names (`TEMPERATURE`, `MAX_TOKENS`, `VERBOSE`) — set both forms when using both entrypoints.
- **Agent has configurable HTTP timeout** (`timeout: float = 30.0` in constructor). CLI maps from `LLM_TIMEOUT` env var.
- **`os.replace()`** is atomic on POSIX but not Windows.
