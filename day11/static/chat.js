let isWaiting = false;
let currentUserId = null;

// Загружаем список пользователей
async function loadUsers() {
    try {
        const response = await fetch('/api/users');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        
        const select = document.getElementById('userSelect');
        select.innerHTML = '';
        
        data.users.forEach(user => {
            const option = document.createElement('option');
            option.value = user.user_id;
            option.textContent = `${user.name} (${user.history_length})`;
            if (user.user_id === data.current_user_id) {
                option.selected = true;
                currentUserId = user.user_id;
            }
            select.appendChild(option);
        });
        
        // Загружаем историю для текущего пользователя
        if (currentUserId) {
            loadHistory();
        }
        
        // Обновляем ID агента
        updateAgentInfo();
        
    } catch (err) {
        console.error('Ошибка загрузки пользователей:', err);
        showError('Не удалось загрузить список пользователей');
    }
}

// Загружаем историю текущего пользователя
async function loadHistory() {
    try {
        const response = await fetch('/history');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderMessages(data.history);
    } catch (err) {
        console.error('Ошибка загрузки истории:', err);
        showError('Не удалось загрузить историю чата');
    }
}

// Отрисовка истории (массив сообщений с role и content)
function renderMessages(history) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
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

// Вспомогательная функция: добавить одно сообщение в DOM
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

// Индикатор печати
let typingElement = null;
function showTypingIndicator() {
    hideTypingIndicator();
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

    isWaiting = true;
    const sendBtn = document.getElementById('sendBtn');
    const resetBtn = document.getElementById('resetBtn');
    sendBtn.disabled = true;
    resetBtn.disabled = true;
    input.disabled = true;

    appendMessageToDOM('user', message, true);
    input.value = '';
    input.style.height = 'auto';
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
        hideTypingIndicator();
        renderMessages(data.history);
    } catch (err) {
        hideTypingIndicator();
        const container = document.getElementById('chatMessages');
        const errorDiv = document.createElement('div');
        errorDiv.className = 'message assistant';
        errorDiv.innerHTML = `<div class="message-bubble" style="background:#f8d7da; color:#721c24;">❌ Не удалось получить ответ: ${escapeHtml(err.message)}</div>`;
        container.appendChild(errorDiv);
        scrollToBottom();
        showError(`Ошибка: ${err.message}`);
    } finally {
        isWaiting = false;
        sendBtn.disabled = false;
        resetBtn.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

// Сброс истории
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
        const container = document.getElementById('chatMessages');
        container.innerHTML = `<div class="message assistant"><div class="message-bubble">История очищена. Начните новый диалог.</div></div>`;
        showError('История успешно очищена', 'success');
    } catch (err) {
        showError(`Ошибка очистки: ${err.message}`);
    }
}

// Переключение пользователя
async function switchUser(userId) {
    if (userId === currentUserId) return;
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        document.getElementById('userSelect').value = currentUserId;
        return;
    }
    
    try {
        const response = await fetch(`/api/users/${userId}/switch`, {
            method: 'POST'
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Switch failed: ${response.status}`);
        }
        const data = await response.json();
        currentUserId = data.user.user_id;
        
        // Обновляем интерфейс
        await loadHistory();
        updateAgentInfo();
        showError(`Переключились на ${data.user.name}`, 'success');
    } catch (err) {
        showError(`Ошибка переключения: ${err.message}`);
        // Возвращаем выбор обратно
        document.getElementById('userSelect').value = currentUserId;
    }
}

// Создание пользователя
function showCreateUserModal() {
    document.getElementById('createUserModal').style.display = 'flex';
    document.getElementById('userNameInput').value = '';
    document.getElementById('preferencesFileInput').value = '';
    document.getElementById('userNameInput').focus();
}

function closeCreateUserModal() {
    document.getElementById('createUserModal').style.display = 'none';
}

async function createUser() {
    const name = document.getElementById('userNameInput').value.trim();
    if (!name) {
        showError('Введите имя пользователя');
        return;
    }
    
    const fileInput = document.getElementById('preferencesFileInput');
    const formData = new FormData();
    formData.append('name', name);
    if (fileInput.files.length > 0) {
        formData.append('preferences', fileInput.files[0]);
    }
    
    try {
        const response = await fetch('/api/users', {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Create failed: ${response.status}`);
        }
        const data = await response.json();
        closeCreateUserModal();
        await loadUsers();
        showError(`Пользователь ${data.user.name} создан`, 'success');
    } catch (err) {
        showError(`Ошибка создания: ${err.message}`);
    }
}

// Удаление текущего пользователя
async function deleteCurrentUser() {
    if (!currentUserId) return;
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        return;
    }
    if (!confirm('Вы уверены, что хотите удалить текущего пользователя?')) return;
    
    try {
        const response = await fetch(`/api/users/${currentUserId}`, {
            method: 'DELETE'
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Delete failed: ${response.status}`);
        }
        const data = await response.json();
        await loadUsers();
        showError('Пользователь удален', 'success');
    } catch (err) {
        showError(`Ошибка удаления: ${err.message}`);
    }
}

// Обновление информации об агенте
async function updateAgentInfo() {
    try {
        const infoRes = await fetch('/info');
        if (infoRes.ok) {
            const info = await infoRes.json();
            const agentIdSpan = document.getElementById('agentIdLabel');
            if (agentIdSpan) {
                const userName = info.user ? info.user.name : 'Нет пользователя';
                agentIdSpan.textContent = `${userName} | ID: ${info.agent_id}`;
            }
        }
    } catch(e) { console.warn(e); }
}

// Утилиты
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
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

// Закрытие модального окна по клику вне его
document.getElementById('createUserModal').addEventListener('click', function(e) {
    if (e.target === this) {
        closeCreateUserModal();
    }
});

// Загружаем данные при старте
loadUsers();

// Периодическое обновление информации об агенте (каждые 30 секунд)
setInterval(updateAgentInfo, 30000);