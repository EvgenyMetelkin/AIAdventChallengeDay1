Overview
Async OpenAI-compatible LLM agent with file handling, conversation summarization, and token-aware context management.

Imports
httpx

API
class Agent(api_key, base_url, model, temperature, max_tokens, timeout, verbose, agent_id, history_dir, files_dir, max_file_size_mb, keep_last_n_messages, summary_interval)
Main agent class.

async send_message(user_message="", files=None) -> Tuple[str, Dict[str, int]]
Send message, return (response, token_stats).

reset_conversation() -> None
Clear history, summaries, token stats, and agent files.

save_history(filepath) -> None
Save conversation + summaries + token stats to JSON.

load_history(filepath) -> None
Load conversation from JSON.

get_token_stats() -> Dict[str, int]
Return token usage: session_total_tokens, last_prompt_tokens, last_completion_tokens, last_total_tokens.

get_context_stats() -> Dict[str, Any]
Return context management stats.

get_agent_info() -> Dict
Return agent metadata.

change_agent_id(new_agent_id) -> None
Rename agent and migrate files.

list_all_agents(history_dir="agent_history") -> List[Dict]
Static method: scan for all agent history files.

Usage
python
import asyncio
from agent import Agent

async def main():
    agent = Agent(api_key="your-key", model="gpt-3.5-turbo", verbose=True)
    response, stats = await agent.send_message("Hello!")
    print(response, stats)

asyncio.run(main())
Notes
Automatically summarizes old messages when exceeding keep_last_n_messages

Summaries trigger every summary_interval messages

Vision support auto-detected from model name

Files saved to agent_files/{agent_id}/

Token stats persisted across sessions

Summarization may fail silently (no message deletion on failure)

reset_conversation() deletes all agent files permanently