# AGENTS.md

Don't use skills.

## Repo structure

Each `dayN/` is a **self-contained project** — no shared code between days. Always work inside one day directory.

Days 1–5: single Python scripts (`dayN/dayN.py`), no web server.
Days 6+: FastAPI + uvicorn web apps (entrypoint varies by day).

## Language & stack

- Python 3.9+, `async`/`await` throughout
- FastAPI + uvicorn for web apps (days 6+)
- `httpx.AsyncClient` for outbound HTTP
- `python-dotenv` for env loading (`.env` per day)
- Comments and commit messages in **Russian**

## Setup any day

```bash
cd dayN
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Each day needs its own `.env` with API keys. Root `.gitignore` covers `.env` and `**/venv/` (nested `.env` files like `day17/mcp_news_server/.env` are also gitignored).

## Running (web days)

Entrypoints vary by day — always check before running:
- Days 7–15: `uvicorn web:app --reload --host 0.0.0.0 --port 8000`
- Day 16: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`
- Day 17: `cd day17/mcp_news_server && pip install -r requirements.txt && uvicorn server:app --reload --host 0.0.0.0 --port 9000` (MCP server, requires `NEWS_API_KEY` in `.env`)

## Testing

No linter, typechecker, or formatter is configured at the repo level.

Days 6–15 have `pytest` test suites (`test_agent.py`, some also have `test_swarm.py`):
```bash
python -m pytest test_agent.py -v
```

Days 1–5 and 16–17 have no tests. Days 12–15 have per-day `AGENTS.md` with exact test commands.

## Git

- Single branch `main`
- Remote: `https://github.com/EvgenyMetelkin/AIAdventChallengeDay1.git`
- Commit format: `Day N. Description` (Russian)
- `.env` and `**/venv/` are gitignored — verify before staging

## Per-day AGENTS.md

Days 12–16 have their own `AGENTS.md` with day-specific quirks, endpoint lists, and gotchas. Consult them when working in those days.
