# Overview
Agent class for LLM interaction via OpenAI-compatible API with file upload support and conversation history.

## Imports
- `httpx`

## API
### `class Agent(api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-3.5-turbo", temperature: float = 0.7, max_tokens: int = 500, timeout: float = 30.0, verbose: bool = False, agent_id: Optional[str] = None, history_dir: str = "agent_history", files_dir: str = "agent_files", max_file_size_mb: int = 10)`
  Initialize agent with API credentials and persistence settings.

### `reset_conversation(self) -> None`
  Clear conversation history and delete agent's file directory.

### `async send_message(self, user_message: str = "", files: Optional[List[Dict]] = None) -> str`
  Send message with optional file attachments, return assistant response.

### `save_history(self, filepath: str) -> None`
  Save conversation history to JSON file.

### `load_history(self, filepath: str) -> None`
  Load conversation history from JSON file.

### `get_agent_info(self) -> Dict`
  Return agent metadata (id, model, history length, etc.).

### `list_all_agents(history_dir: str = "agent_history") -> List[Dict]` (static)
  Scan history directory and return info for all agents.

### `change_agent_id(self, new_agent_id: str) -> None`
  Rename agent ID and update associated files.

## Usage
```python
import asyncio
from agent import Agent

async def main():
    agent = Agent(api_key="your-key", model="gpt-3.5-turbo", verbose=True)
    response = await agent.send_message("Hello, world!")
    print(response)

asyncio.run(main())