# chat.js - Frontend Chat Client

## Overview
Browser-based chat interface with multi-user support, history management, and real-time messaging.

## Dependencies
- None (vanilla JS, uses Fetch API)

## API Functions

| Function | Description |
|----------|-------------|
| `loadUsers()` | Fetches and populates user dropdown from `/api/users` |
| `loadHistory()` | GET `/history` → renders message history |
| `renderMessages(history)` | Renders array of `{role, content}` messages to DOM |
| `appendMessageToDOM(role, content, scroll)` | Adds single message bubble to chat container |
| `sendMessage()` | POST `/send` with `{message}` → appends user msg, shows typing, renders response |
| `resetChat()` | POST `/reset` → clears history after confirmation |
| `switchUser(userId)` | POST `/api/users/{userId}/switch` → reloads history |
| `createUser()` | POST `/api/users` with FormData `{name, preferences(file)}` |
| `deleteCurrentUser()` | DELETE `/api/users/{currentUserId}` |
| `updateAgentInfo()` | GET `/info` → updates agent ID label |

## Usage
```html
<select id="userSelect"></select>
<div id="chatMessages"></div>
<textarea id="messageInput"></textarea>
<button id="sendBtn" onclick="sendMessage()">Send</button>
```

## Notes
- Global `isWaiting` prevents concurrent requests
- Typing indicator shown during `/send` latency
- Auto-scrolls to bottom on new messages
- Toast notifications for errors/success (auto-dismiss 4s)
- Textarea auto-expands up to 150px
- Agent info refreshes every 30s via `setInterval`
- EscapeHtml prevents XSS in message content
- Modal closes on backdrop click