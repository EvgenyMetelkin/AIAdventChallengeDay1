---
name: frontend-vanilla-js
description: Use ONLY when working with frontend code in static/chat.js, static/style.css, or templates/index.html. Covers vanilla JS SPA patterns, SSE streaming, DOM structure, conventions.
---

# Frontend Development (Vanilla JS SPA)

## Architecture

Single-page application with VS Code-like IDE layout. No framework — vanilla JS. Files:
- `templates/index.html` — Jinja2 template (~340 lines), structure + initial data
- `static/chat.js` — all client logic (~1980 lines), single JS file
- `static/style.css` — all styles (~1730 lines), CSS custom properties theme

## DOM Structure

```
.activity-bar (left edge, vertical icons)
  .activity-icon[data-panel="explorer|swarm|settings"]
.sidebar (collapsible left panel)
  .sidebar-panel#panel-explorer — user/agent tree
  .sidebar-panel#panel-swarm — swarm task list
  .sidebar-panel#panel-settings — user preferences + invariants editor
.main-area (center)
  .tab-bar — open agent tabs
  .tab-content
    #chatMessages — rendered messages
    #streamBubble — active SSE streaming bubble
    .input-container — textarea + send button
.status-bar (bottom)
  .status-item — user count, agent name, model, stage
.bottom-panel (collapsible)
  .panel-tab[data-panel="problems|output|working_memory"]
  .panel-pane#pane-problems
  .panel-pane#pane-output
  .panel-pane#pane-working_memory
.modal (overlay)
  #createUserModal, #createAgentModal
```

## Global State (chat.js:10-16)

```javascript
let isWaiting = false;
let currentUserId = null;
let currentAgentId = null;
let agents = {};           // { agentId: { name, history_length, ... } }
let usersList = [];        // [{ user_id, name, agent_count, ... }]
let openTabs = [];         // [{ agentId, name, history }]
let activeTabIdx = -1;
```

## SSE Streaming (chat.js:845-905)

Primary streaming function: `sendMessageStream(message)`.

```javascript
const response = await fetch('/send/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_id: currentUserId })
});
const reader = response.body.getReader();  // ReadableStream
const decoder = new TextDecoder();
```

SSE frame format (line-delimited JSON after `data: `):
```json
{"token": "word"}           // content token to append
{"done": true}              // stream complete
{"error": "error message"}  // error occurred
```

When `done: true`: append full content to DOM via `appendMessageToDOM('assistant', fullContent, true)`, update tab history.

Non-streaming fallback: `sendMessageRegular(message)` at chat.js:908 — uses `fetch('/send', ...)`, reads full JSON response.

## Key Functions

| Function | Line | Purpose |
|----------|------|---------|
| `initActivityBar()` | 34 | Binds activity icon clicks |
| `switchSidebarPanel(panel)` | 44 | Toggles sidebar content |
| `initPanelTabs()` | 72 | Binds bottom panel tabs |
| `sendMessage()` | 782 | Entry point — dispatches to stream or regular |
| `sendMessageStream(msg)` | 845 | SSE streaming consumer |
| `sendMessageRegular(msg)` | 908 | Non-streaming send |
| `appendMessageToDOM(role, content, scroll)` | 754 | Renders a message bubble |
| `resetChat()` | 927 | Clears current agent history |
| `renderMessages(history)` | — | Re-renders all messages from history array |
| `renderExplorer()` | — | Rebuilds user/agent tree in sidebar |
| `showToast(msg, type)` | 166 | Toast notification (types: info, success, error) |
| `updateStatusBar()` | — | Refreshes bottom status bar |
| `updateWorkingMemoryDisplay()` | 961 | Fetches and renders working memory panel |
| `loadUsers()` | — | Fetches /api/users, populates usersList |
| `loadAgents()` | — | Fetches /api/agents for current user |

## Conventions

- **Naming**: `camelCase` for all JS identifiers
- **Comments**: Russian throughout
- **escapeHtml**: Uses `textContent` assignment — never innerHTML for user content:
  ```javascript
  const div = document.createElement('div');
  div.textContent = untrustedString;  // safe
  ```
- **Modal close**: Click on backdrop (`.modal`) closes — `e.target === this` check
- **No state management library**: All state is module-level globals in `chat.js`
- **No bundler**: Script loaded directly via `<script src="/chat.js">`

## API Endpoints Called from Frontend

| Endpoint | Used for |
|----------|----------|
| `GET /api/users` | Load user list, get current_user_id |
| `POST /api/users` | Create user (FormData: name, preferences file) |
| `POST /api/users/{id}/switch` | Switch active user |
| `POST /api/users/{id}/reset` | Reset user history |
| `DELETE /api/users/{id}` | Delete user |
| `GET /api/agents` | Load agent list with history lengths |
| `POST /api/agents` | Create agent (JSON: {name}) |
| `POST /api/agents/{id}/switch` | Switch active agent |
| `DELETE /api/agents/{id}` | Delete agent |
| `GET /api/working_memory` | Read working memory |
| `DELETE /api/working_memory` | Clear working memory |
| `GET /history` | Get current agent history |
| `POST /send` | Non-streaming message |
| `POST /send/stream` | SSE streaming message |
| `POST /reset` | Clear conversation |
| `GET /api/status` | Status bar data |
| `GET /api/invariants` | Read user invariants |
| `PUT /api/invariants` | Update user invariants |
| `GET /info` | Agent info |
| `POST /api/swarm/create` | Create swarm task |
| `GET /api/swarm/tasks` | List swarm tasks |
| `GET /api/swarm/tasks/{id}` | Get task state |
| `POST /api/swarm/tasks/{id}/action` | Execute swarm action |
| `DELETE /api/swarm/tasks/{id}` | Delete swarm task |
| `GET /api/swarm/tasks/{id}/artifacts` | List artifacts |
| `GET /api/swarm/tasks/{id}/artifacts/{stage}/{file}` | Read artifact |

## Swarm View in Sidebar

The swarm panel (`#panel-swarm`) renders:
- Create task button + description input
- Task list with stage label, progress bar
- Stage details: invariant check results, artifacts viewer
- Action buttons for each available transition

## CSS Theme

VS Code-like theme with CSS custom properties on `:root`. Key variables:
- `--bg-primary`, `--bg-secondary`, `--bg-tertiary`
- `--text-primary`, `--text-secondary`
- `--accent`, `--accent-hover`
- `--green`, `--red`, `--yellow`, `--blue`
- `--border`, `--hover-bg`
