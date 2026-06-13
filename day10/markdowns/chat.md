# LLM Agent Chat Frontend Client

## Overview
Browser-based chat client with file attachment support, token statistics display, and smart context summarization visualization.

## Imports
- None (vanilla JavaScript, runs in browser)

## API (Frontend Functions)

### `sendMessage() -> Promise<void>`
Sends message + files to `/send` endpoint, displays response, updates token stats.

### `loadHistory() -> Promise<void>`
Fetches chat history from `/history` and renders messages.

### `loadTokenStats() -> Promise<void>`
GET `/stats` - updates token counters in UI.

### `loadContextStats() -> Promise<void>`
GET `/context-stats` - updates summarization badges and tooltips.

### `resetChat() -> Promise<void>`
POST `/reset` - clears history, resets all counters and summaries.

### `appendMessageToDOM(role, content, scroll, attachments, tokens, isSummarized) -> void`
Renders a single message bubble with optional file attachments and token info.

### `updateFilePreview() -> void`
Shows preview thumbnails for selected files before sending.

## Usage

```javascript
// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    init();  // Sets up event listeners, loads history, starts refresh
});

// Manual send
await sendMessage();

// Reset conversation
await resetChat();
```

## Notes
- Max file size: 10MB per file (frontend validation)
- Supported preview: images only (shows thumbnail); other files show icon
- Auto-refreshes stats every 15 seconds when tab is focused
- Summarization banner appears when context stats change (throttled to 30s)
- Collapsible stats panel state saved to localStorage
- Enter sends message (Shift+Enter for newline)
- Typing indicator shows during LLM response
- No external dependencies - runs in any modern browser