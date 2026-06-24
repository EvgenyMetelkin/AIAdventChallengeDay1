document.addEventListener("DOMContentLoaded", () => {

  function getById(id) { return document.getElementById(id); }

  const chatForm = getById("chat-form");
  const msgInput = getById("msg-input");
  const sendBtn = getById("send-btn");
  const messagesContainer = getById("chat-messages");
  const userSelect = getById("user-select");
  const agentSelect = getById("agent-select");
  const settingsForm = getById("settings-form");

  const modelInput = getById("setting-model");
  const tempInput = getById("setting-temperature");
  const maxTokInput = getById("setting-max-tokens");

  if (msgInput) {
    msgInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event("submit"));
      }
    });
    msgInput.addEventListener("input", () => {
      msgInput.style.height = "auto";
      msgInput.style.height = Math.min(msgInput.scrollHeight, 200) + "px";
    });
  }

  if (userSelect) {
    userSelect.addEventListener("change", async () => {
      const userId = userSelect.value;
      const resp = await fetch("/api/switch", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "user_id=" + encodeURIComponent(userId),
      });
      if (resp.redirected || resp.ok) {
        window.location.reload();
      }
    });
  }

  if (agentSelect) {
    agentSelect.addEventListener("change", async () => {
      const agentId = agentSelect.value;
      const resp = await fetch("/api/switch", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "agent_id=" + encodeURIComponent(agentId),
      });
      if (resp.redirected || resp.ok) {
        window.location.reload();
      }
    });
  }

  if (settingsForm) {
    settingsForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = new URLSearchParams();
      body.append("model", modelInput.value);
      body.append("temperature", tempInput.value);
      body.append("max_tokens", maxTokInput.value);
      await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });
      showToast("Settings saved", "success");
    });
  }

  if (chatForm) {
    chatForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const message = msgInput.value.trim();
      if (!message || sendBtn.disabled) return;

      sendBtn.disabled = true;
      msgInput.value = "";
      msgInput.style.height = "auto";

      appendMessage("user", message);

      const assistantMsgEl = appendMessage("assistant", "", true);

      try {
        const formData = new FormData();
        formData.append("message", message);

        const response = await fetch("/api/chat/stream", {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const jsonStr = line.slice(6);
            try {
              const data = JSON.parse(jsonStr);
              if (data.error) {
                const cd = assistantMsgEl.querySelector(".message-content");
                cd.classList.remove("loading", "streaming-cursor");
                cd.textContent = "Error: " + data.error;
                return;
              }
              if (data.done) {
                assistantMsgEl.querySelector(".message-content").classList.remove("streaming-cursor");
                return;
              }
              if (data.tool_call) {
                appendToolBlock(assistantMsgEl, data.tool_call);
                continue;
              }
              if (data.tool_result) {
                updateToolResult(assistantMsgEl, data.tool_result);
                continue;
              }
              if (data.token) {
                const contentDiv = assistantMsgEl.querySelector(".message-content");
                if (contentDiv.classList.contains("loading")) {
                  contentDiv.classList.remove("loading");
                  contentDiv.classList.add("streaming-cursor");
                  contentDiv.textContent = "";
                }
                contentDiv.textContent += data.token;
                scrollToBottom();
              }
            } catch (_) {}
          }
        }
      } catch (err) {
        const cd = assistantMsgEl.querySelector(".message-content");
        cd.classList.remove("loading", "streaming-cursor");
        cd.textContent = "Error: " + err.message;
      } finally {
        sendBtn.disabled = false;
        msgInput.focus();
      }
    });
  }

  function appendMessage(role, content, streaming) {
    const div = document.createElement("div");
    div.className = "message " + role;

    const icon = document.createElement("div");
    icon.className = "message-icon";
    icon.textContent = role === "user" ? "U" : "A";

    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";
    if (streaming) {
      contentDiv.classList.add("loading");
      contentDiv.textContent = "...";
    } else {
      contentDiv.textContent = content;
    }

    div.appendChild(icon);
    div.appendChild(contentDiv);

    if (messagesContainer) {
      messagesContainer.appendChild(div);
      scrollToBottom();
    }
    return div;
  }

  function appendToolBlock(msgEl, toolCall) {
    const contentDiv = msgEl.querySelector(".message-content");
    if (contentDiv.classList.contains("loading")) {
      contentDiv.classList.remove("loading");
      contentDiv.textContent = "";
    }

    const block = document.createElement("div");
    block.className = "tool-block";
    block.setAttribute("data-tool-id", toolCall.id);

    const header = document.createElement("div");
    header.className = "tool-block-header";
    header.textContent = toolCall.name;
    if (toolCall.arguments && Object.keys(toolCall.arguments).length) {
      header.textContent += "(" + JSON.stringify(toolCall.arguments) + ")";
    }
    header.textContent += " ...";

    const result = document.createElement("div");
    result.className = "tool-block-result";
    result.textContent = "";

    block.appendChild(header);
    block.appendChild(result);
    contentDiv.appendChild(block);
    scrollToBottom();
  }

  function updateToolResult(msgEl, toolResult) {
    const block = msgEl.querySelector('.tool-block[data-tool-id="' + toolResult.id + '"]');
    if (!block) return;

    const header = block.querySelector(".tool-block-header");
    if (toolResult.result && toolResult.result.error) {
      header.textContent = toolResult.name + ": error";
      const result = block.querySelector(".tool-block-result");
      result.textContent = toolResult.result.error;
      result.classList.add("error");
    } else {
      if (toolResult.result && toolResult.result.arguments) {
        header.textContent = toolResult.name + "("
          + JSON.stringify(toolResult.result.arguments) + "): done";
      } else {
        header.textContent = toolResult.name + ": done";
      }
      const result = block.querySelector(".tool-block-result");
      if (toolResult.result && toolResult.result.content) {
        const texts = toolResult.result.content
          .filter(function(c) { return c.type === "text"; })
          .map(function(c) { return c.text; });
        result.textContent = texts.join("\n") || "ok";
      } else {
        result.textContent = JSON.stringify(toolResult.result, null, 2);
      }
    }
    scrollToBottom();
  }

  function scrollToBottom() {
    if (messagesContainer) {
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
  }

  function showToast(msg, type) {
    let toast = document.querySelector(".toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "toast";
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.className = "toast " + type + " show";
    setTimeout(() => { toast.classList.remove("show"); }, 2500);
  }
});
