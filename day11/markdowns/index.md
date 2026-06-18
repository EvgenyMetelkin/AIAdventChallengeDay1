# Overview
Minimal Flask + SSE chat server with session persistence and streaming LLM responses.

## Imports
- `flask`
- `flask_cors`
- `requests`

## API

### `POST /api/chat/stream`
Streaming chat endpoint.

**Request:** `{"message": str, "agent_id": str, "session_id": str}`  
**Response:** Server-Sent Events with `data: {"token": str, "done": bool, "error": str}`

### `GET /api/agent/<agent_id>/status`
Returns agent availability.

**Response:** `{"available": bool, "agent_id": str}`

### `DELETE /api/session/<session_id>`
Clears session context.

## Usage
```python
# Run server
python app.py

# Client example (streaming)
import requests
import sseclient

with requests.post('http://localhost:5000/api/chat/stream',
                   json={'message': 'Hello', 'agent_id': 'default', 'session_id': '123'},
                   stream=True) as r:
    client = sseclient.SSEClient(r)
    for event in client.events():
        print(event.data)
```

## Notes
- Sessions stored in memory; reset on restart.
- Agent expects `http://localhost:8000/generate` endpoint.
- No authentication or rate limiting.
- Streams token-by-token; may buffer on slow agents.
- Default agent: `default`, fallback to `gpt-4` if unavailable.