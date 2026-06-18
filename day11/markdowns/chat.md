# Chat History & Agent UI

## Overview
Client-side chat UI with history management, message streaming indicators, and agent info display.

## Imports (non-standard)
None (vanilla JS, browser APIs)

## API

### `loadHistory()`
Fetches `/history` and `/info`, renders messages and agent ID.

### `renderMessages(history)`
Renders array of `{role, content}` messages to DOM.

### `appendMessageToDOM(role, content, scroll)`
Appends single message bubble with timestamp.

### `showTypingIndicator()` / `hideTypingIndicator()`
Shows/hides animated "typing..." indicator.

### `sendMessage()`
POST `/send` with `{message}` payload, renders response history.

### `resetChat()`
POST `/reset`, clears history and shows confirmation.

### `escapeHtml(str)`
Sanitizes strings for DOM insertion (basic HTML escaping).

### `scrollToBottom()`
Scrolls chat container to bottom.

### `showError(msg, type)`
Shows toast notification (error/success).

## Usage

```html
<!-- Required DOM elements -->
<div id="chatMessages"></div>
<textarea id="messageInput"></textarea>
<button id="sendBtn" onclick="sendMessage()">Send</button>
<button id="resetBtn" onclick="resetChat()">Reset</button>
<span id="agentIdLabel"></span>

<!-- Load script -->
<script src="chat.js"></script>
```

## Notes
- **State:** `isWaiting` prevents concurrent requests.
- **Pessimistic UI:** User message appears immediately, typing indicator shown while waiting.
- **Error handling:** On failure, error message bubble is appended; user's message remains.
- **History sync:** `sendMessage()` re-renders full history from server response, not incremental.
- **Textarea auto-resize:** Grows to 150px max height.
- **Edge case:** If `/send` fails after user message posted, user sees their message with no assistant response plus an error bubble.
- **Toast timeout:** 4s auto-dismiss.