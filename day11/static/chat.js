let isWaiting = false;  // блокировка отправки во время ожидания ответа

// Загружаем историю при старте и информацию об агенте
async function loadHistory() {
    try {
        const response = await fetch('/history');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        // отображаем историю (data.history)
        renderMessages(data.history);
    } catch (err) {
        console.error('Ошибка загрузки истории:', err);
        showError('Не удалось загрузить историю чата');
    }
    // также загрузим информацию об агенте для отображения ID
    try {
        const infoRes = await fetch('/info');
        if (infoRes.ok) {
            const info = await infoRes.json();
            const agentIdSpan = document.getElementById('agentIdLabel');
            if (agentIdSpan) agentIdSpan.textContent = `ID: ${info.agent_id}`;
        }
    } catch(e) { console.warn(e); }
}

// Отрисовка истории (массив сообщений с role и content)
function renderMessages(history) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    // Очищаем контейнер, но оставляем приветственное сообщение, если истории нет
    container.innerHTML = '';
    if (!history || history.length === 0) {
        container.innerHTML = `<div class="message assistant"><div class="message-bubble">История пуста. Напишите что-нибудь!</div></div>`;
        return;
    }
    for (const msg of history) {
        if (msg.role === 'user') {
            appendMessageToDOM('user', msg.content, false);
        } else if (msg.role === 'assistant') {
            appendMessageToDOM('assistant', msg.content, false);
        }
    }
    scrollToBottom();
}

// Вспомогательная функция: добавить одно сообщение в DOM (без анимации печати)
function appendMessageToDOM(role, content, scroll = true) {
    const container = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.innerHTML = `
        <div class="message-bubble">${escapeHtml(content)}</div>
        <div class="message-meta">${role === 'user' ? 'Вы' : 'Ассистент'} · ${new Date().toLocaleTimeString()}</div>
    `;
    container.appendChild(messageDiv);
    if (scroll) scrollToBottom();
}

// Функция для показа индикатора печати (ассистент печатает)
let typingElement = null;
function showTypingIndicator() {
    hideTypingIndicator(); // убираем старый, если есть
    const container = document.getElementById('chatMessages');
    typingElement = document.createElement('div');
    typingElement.className = 'message assistant';
    typingElement.id = 'typing-indicator';
    typingElement.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span> Печатает...</div>`;
    container.appendChild(typingElement);
    scrollToBottom();
}
function hideTypingIndicator() {
    if (typingElement && typingElement.parentNode) {
        typingElement.parentNode.removeChild(typingElement);
        typingElement = null;
    }
}

// Отправка сообщения
async function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    if (!message) return;
    if (isWaiting) {
        showError('Подождите, ответ уже загружается');
        return;
    }

    // Блокируем интерфейс
    isWaiting = true;
    const sendBtn = document.getElementById('sendBtn');
    const resetBtn = document.getElementById('resetBtn');
    sendBtn.disabled = true;
    resetBtn.disabled = true;
    input.disabled = true;

    // Оптимистично показываем сообщение пользователя
    appendMessageToDOM('user', message, true);
    input.value = '';
    input.style.height = 'auto';

    // Показываем индикатор печати
    showTypingIndicator();

    try {
        const response = await fetch('/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Server error: ${response.status}`);
        }
        const data = await response.json();
        // Убираем индикатор печати
        hideTypingIndicator();
        // Обновляем всю историю (чтобы синхронизировать с сервером)
        renderMessages(data.history);
    } catch (err) {
        hideTypingIndicator();
        // Если ошибка, убираем "печатает" и показываем ошибку. Сообщение пользователя уже есть,
        // но ответа не будет. Можно добавить сообщение об ошибке.
        showError(`Ошибка: ${err.message}`);
        // Удаляем последнее сообщение пользователя? Не будем, но можем добавить системное сообщение об ошибке
        const container = document.getElementById('chatMessages');
        const errorDiv = document.createElement('div');
        errorDiv.className = 'message assistant';
        errorDiv.innerHTML = `<div class="message-bubble" style="background:#f8d7da; color:#721c24;">❌ Не удалось получить ответ: ${escapeHtml(err.message)}</div>`;
        container.appendChild(errorDiv);
        scrollToBottom();
    } finally {
        isWaiting = false;
        sendBtn.disabled = false;
        resetBtn.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

// Очистка истории
async function resetChat() {
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        return;
    }
    if (!confirm('Вы уверены, что хотите очистить всю историю диалога?')) return;
    try {
        const response = await fetch('/reset', { method: 'POST' });
        if (!response.ok) throw new Error(`Reset failed: ${response.status}`);
        const result = await response.json();
        // Очищаем DOM и показываем пустое состояние
        const container = document.getElementById('chatMessages');
        container.innerHTML = `<div class="message assistant"><div class="message-bubble">История очищена. Начните новый диалог.</div></div>`;
        showError('История успешно очищена', 'success');
    } catch (err) {
        showError(`Ошибка очистки: ${err.message}`);
    }
}

// Утилиты
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    }).replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, function(c) {
        return c;
    });
}

function scrollToBottom() {
    const container = document.getElementById('chatMessages');
    if (container) container.scrollTop = container.scrollHeight;
}

function showError(msg, type = 'error') {
    const toast = document.createElement('div');
    toast.className = 'error-toast';
    toast.style.background = type === 'success' ? '#d4edda' : '#f8d7da';
    toast.style.color = type === 'success' ? '#155724' : '#721c24';
    toast.style.borderLeftColor = type === 'success' ? '#28a745' : '#d9534f';
    toast.innerText = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// Автоматическое расширение textarea
const textarea = document.getElementById('messageInput');
if (textarea) {
    textarea.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 150) + 'px';
    });
}

// Загружаем историю при старте
loadHistory();