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
      var toolsUsed = [];

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
                var cd = assistantMsgEl.querySelector(".message-content");
                cd.classList.remove("streaming-cursor");
                if (assistantMsgEl._streamSpan) {
                  delete assistantMsgEl._streamSpan;
                }
                return;
              }
              if (data.tool_call) {
                var displayName = data.tool_call.name;
                var sepIdx = displayName.indexOf("__");
                if (sepIdx >= 0) {
                  displayName = displayName.substring(0, sepIdx) + " \u2192 " + displayName.substring(sepIdx + 2);
                }
                toolsUsed.push(displayName);
                var cd = assistantMsgEl.querySelector(".message-content");
                if (cd.classList.contains("loading")) {
                  cd.classList.remove("loading");
                }
                cd.textContent = "MCP \u00B7 " + toolsUsed.join(", ");
                continue;
              }
              if (data.tool_result) {
                continue;
              }
              if (data.token) {
                var contentDiv = assistantMsgEl.querySelector(".message-content");
                if (toolsUsed.length > 0 && !contentDiv.querySelector(".mcp-badge")) {
                  contentDiv.classList.remove("loading");
                  contentDiv.textContent = "";
                  var badge = document.createElement("div");
                  badge.className = "mcp-badge";
                  badge.textContent = "MCP \u00B7 " + toolsUsed.join(", ");
                  contentDiv.appendChild(badge);
                  assistantMsgEl._streamSpan = document.createElement("span");
                  assistantMsgEl._streamSpan.textContent = data.token;
                  contentDiv.appendChild(assistantMsgEl._streamSpan);
                  contentDiv.classList.add("streaming-cursor");
                  toolsUsed = [];
                } else if (assistantMsgEl._streamSpan) {
                  assistantMsgEl._streamSpan.textContent += data.token;
                } else {
                  if (contentDiv.classList.contains("loading")) {
                    contentDiv.classList.remove("loading");
                    contentDiv.classList.add("streaming-cursor");
                    contentDiv.textContent = "";
                  }
                  contentDiv.textContent += data.token;
                }
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
    var welcomeEl = messagesContainer.querySelector(".welcome");
    if (welcomeEl) welcomeEl.remove();

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

  function scrollToBottom() {
    if (messagesContainer) {
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
  }

  if (messagesContainer && !messagesContainer.querySelector(".welcome")) {
    scrollToBottom();
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
