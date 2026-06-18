# Agent: LLM Chat Agent (OpenAI-compatible)

## Overview
Async OpenAI-compatible chat agent with persistent JSON history, agent IDs, and history file management.

## Imports
- `httpx` (async HTTP client)

## API
### `class Agent(api_key, base_url="https://api.openai.com/v1", model="gpt-3.5-turbo", temperature=0.7, max_tokens=500, timeout=30.0, verbose=False, agent_id=None, history_dir="agent_history")`
Persistent chat agent with auto-saved history.

**Methods**:
- `reset_conversation()` – Clear history and delete JSON file.
- `async send_message(user_message: str) -> str` – Send user message, return assistant reply, auto-save.
- `save_history(filepath: str)` – Save current history to JSON.
- `load_history(filepath: str)` – Load history from JSON (overwrites current).
- `get_agent_info() -> Dict` – Return id, model, history path, history length.
- `change_agent_id(new_agent_id: str)` – Rename history file and update agent ID.

### `static list_all_agents(history_dir="agent_history") -> List[Dict]`
Scan directory and return info for all agent history files.

## Usage
```python
import asyncio
agent = Agent(api_key="sk-...", verbose=True)
reply = asyncio.run(agent.send_message("Hello!"))
print(reply)
```

## Notes
- History auto-saved to `agent_history/history_{agent_id}_{model}.json`
- Filename sanitization replaces `<>:"/\|?*` with `_`
- `load_history()` overwrites current history and triggers auto-save
- `change_agent_id()` renames existing history file if present
- `reset_conversation()` clears both memory and JSON file
- Agent ID generation uses first 8 hex chars of `uuid.uuid4()` if not provided
- Timeout default 30s; raises Exception on timeout/HTTP/network errors