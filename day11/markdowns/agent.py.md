# Agent API Overview

LLM chat agent with per-user conversation history and OpenAI-compatible API.

## Imports

- `httpx` (async HTTP client)

## API

### `class Agent(api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-3.5-turbo", temperature: float = 0.7, max_tokens: int = 500, timeout: float = 30.0, verbose: bool = False, agent_id: Optional[str] = None, history_dir: str = "agent_history", user: Optional[User] = None)`

Main agent class.

- `set_user(user: User) -> None` – Switch active user.
- `reset_conversation() -> None` – Clear current user's history.
- `send_message(user_message: str) -> str` – Send prompt, get assistant reply (async).
- `get_agent_info() -> Dict` – Return agent metadata.

## Usage

```python
import asyncio
from user import User
from agent import Agent

async def main():
    user = User(user_id="u1", name="Alice", system_prompt="You are a helpful assistant.")
    agent = Agent(api_key="your-key", user=user, verbose=True)
    reply = await agent.send_message("What is 2+2?")
    print(reply)

asyncio.run(main())
```

## Notes

- Requires `User` class from `user` module.
- History persists via `user.save_history()`.
- `verbose=True` logs request payload; otherwise only prints request to stdout.
- `agent_id` auto-generated if not provided.
- No user selected → `send_message()` raises `Exception`.
- Timeout, HTTP, and network errors are wrapped as `Exception`.