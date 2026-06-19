// chat.js - полный исправленный код

let isWaiting = false;
let currentUserId = null;
let currentAgentId = null;
let agents = {};

// ============================================================
// ЗАГРУЗКА ПОЛЬЗОВАТЕЛЕЙ И АГЕНТОВ
// ============================================================

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
            const agentCount = user.agent_count || 0;
            option.textContent = `${user.name} (${agentCount} агентов)`;
            if (user.user_id === data.current_user_id) {
                option.selected = true;
                currentUserId = user.user_id;
            }
            select.appendChild(option);
        });
        
        // Загружаем агентов и историю для текущего пользователя
        if (currentUserId) {
            await loadAgents();
            await loadHistory();
            updateWorkingMemoryDisplay();
        }
        
        // Обновляем информацию об агенте
        updateAgentInfo();
        
    } catch (err) {
        console.error('Ошибка загрузки пользователей:', err);
        showError('Не удалось загрузить список пользователей');
    }
}

async function loadAgents() {
    try {
        const response = await fetch('/api/agents');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        
        agents = {};
        const select = document.getElementById('agentSelect');
        select.innerHTML = '';
        
        if (!data.agents || data.agents.length === 0) {
            // Если агентов нет, создаём дефолтного
            await createDefaultAgent();
            return loadAgents();
        }
        
        data.agents.forEach(agent => {
            agents[agent.agent_id] = agent;
            const option = document.createElement('option');
            option.value = agent.agent_id;
            option.textContent = `${agent.name} (${agent.history_length})`;
            if (agent.is_current) {
                option.selected = true;
                currentAgentId = agent.agent_id;
            }
            select.appendChild(option);
        });
        
        // Обновляем отображение текущего агента
        updateCurrentAgentDisplay();
        
    } catch (err) {
        console.error('Ошибка загрузки агентов:', err);
        showError('Не удалось загрузить список агентов');
    }
}

async function createDefaultAgent() {
    try {
        const response = await fetch('/api/agents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: 'default' })
        });
        if (!response.ok) throw new Error('Failed to create default agent');
        await response.json();
    } catch (err) {
        console.error('Error creating default agent:', err);
    }
}

// ============================================================
// ЗАГРУЗКА ИСТОРИИ
// ============================================================

async function loadHistory() {
    try {
        const response = await fetch('/history');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderMessages(data.history);
        if (data.agent_id) {
            currentAgentId = data.agent_id;
        }
        updateCurrentAgentDisplay();
    } catch (err) {
        console.error('Ошибка загрузки истории:', err);
        showError('Не удалось загрузить историю чата');
    }
}

// ============================================================
// УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ
// ============================================================

function showCreateUserModal() {
    const modal = document.getElementById('createUserModal');
    if (modal) {
        modal.style.display = 'flex';
        const input = document.getElementById('userNameInput');
        if (input) {
            input.value = '';
            input.focus();
        }
        const fileInput = document.getElementById('preferencesFileInput');
        if (fileInput) {
            fileInput.value = '';
        }
    }
}

function closeCreateUserModal() {
    const modal = document.getElementById('createUserModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

async function createUser() {
    const nameInput = document.getElementById('userNameInput');
    const name = nameInput ? nameInput.value.trim() : '';
    
    if (!name) {
        showError('Введите имя пользователя');
        return;
    }
    
    const fileInput = document.getElementById('preferencesFileInput');
    const formData = new FormData();
    formData.append('name', name);
    
    if (fileInput && fileInput.files.length > 0) {
        formData.append('preferences', fileInput.files[0]);
    }
    
    try {
        const response = await fetch('/api/users', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            let errorMessage = `Create failed: ${response.status}`;
            try {
                const errData = await response.json();
                if (errData.detail) {
                    errorMessage = errData.detail;
                }
            } catch (e) {
                // ignore
            }
            throw new Error(errorMessage);
        }
        
        const data = await response.json();
        closeCreateUserModal();
        await loadUsers();
        showError(`Пользователь "${data.user.name}" создан`, 'success');
    } catch (err) {
        showError(`Ошибка создания: ${err.message}`);
    }
}

async function deleteCurrentUser() {
    if (!currentUserId) {
        showError('Нет активного пользователя');
        return;
    }
    
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        return;
    }
    
    // Получаем имя пользователя для подтверждения
    const select = document.getElementById('userSelect');
    const selectedOption = select ? select.options[select.selectedIndex] : null;
    const userName = selectedOption ? selectedOption.text : currentUserId;
    
    if (!confirm(`Вы уверены, что хотите удалить пользователя "${userName}"?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/users/${currentUserId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            let errorMessage = `Delete failed: ${response.status}`;
            try {
                const errData = await response.json();
                if (errData.detail) {
                    errorMessage = errData.detail;
                }
            } catch (e) {
                // ignore
            }
            throw new Error(errorMessage);
        }
        
        const data = await response.json();
        await loadUsers();
        showError('Пользователь удален', 'success');
    } catch (err) {
        showError(`Ошибка удаления: ${err.message}`);
    }
}

// ============================================================
// УПРАВЛЕНИЕ АГЕНТАМИ
// ============================================================

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
        await loadAgents();
        await loadHistory();
        updateAgentInfo();
        updateWorkingMemoryDisplay();
        showError(`Переключились на ${data.user.name}`, 'success');
    } catch (err) {
        showError(`Ошибка переключения: ${err.message}`);
        document.getElementById('userSelect').value = currentUserId;
    }
}

async function switchAgent(agentId) {
    if (agentId === currentAgentId) return;
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        document.getElementById('agentSelect').value = currentAgentId;
        return;
    }
    
    const agentName = agents[agentId]?.name || agentId;
    if (!confirm(`Переключиться на агента "${agentName}"? Текущая история будет суммирована в рабочую память.`)) {
        document.getElementById('agentSelect').value = currentAgentId;
        return;
    }
    
    try {
        const response = await fetch(`/api/agents/${agentId}/switch`, {
            method: 'POST'
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Switch failed: ${response.status}`);
        }
        const data = await response.json();
        currentAgentId = data.current_agent_id;
        
        if (data.summary_generated) {
            showError('✨ Сводка добавлена в рабочую память', 'success');
            if (data.summary_preview) {
                console.log('Summary preview:', data.summary_preview);
            }
        }
        
        // Обновляем интерфейс
        await loadAgents();
        await loadHistory();
        updateAgentInfo();
        updateWorkingMemoryDisplay();
        
    } catch (err) {
        showError(`Ошибка переключения: ${err.message}`);
        document.getElementById('agentSelect').value = currentAgentId;
    }
}

function showCreateAgentModal() {
    const modal = document.getElementById('createAgentModal');
    if (modal) {
        modal.style.display = 'flex';
        const input = document.getElementById('agentNameInput');
        if (input) {
            input.value = '';
            input.focus();
        }
    }
}

function closeCreateAgentModal() {
    const modal = document.getElementById('createAgentModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

async function createAgent() {
    const nameInput = document.getElementById('agentNameInput');
    const name = nameInput ? nameInput.value.trim() : '';
    
    if (!name) {
        showError('Введите имя агента');
        return;
    }
    
    try {
        const response = await fetch('/api/agents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Create failed: ${response.status}`);
        }
        const data = await response.json();
        closeCreateAgentModal();
        await loadAgents();
        await loadHistory();
        showError(`Агент "${data.name}" создан`, 'success');
    } catch (err) {
        showError(`Ошибка создания: ${err.message}`);
    }
}

async function deleteCurrentAgent() {
    if (!currentAgentId) {
        showError('Нет активного агента');
        return;
    }
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        return;
    }
    
    const agentName = agents[currentAgentId]?.name || currentAgentId;
    if (!confirm(`Удалить агента "${agentName}"?`)) return;
    
    try {
        const response = await fetch(`/api/agents/${currentAgentId}`, {
            method: 'DELETE'
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Delete failed: ${response.status}`);
        }
        const data = await response.json();
        await loadAgents();
        await loadHistory();
        updateAgentInfo();
        showError(`Агент "${agentName}" удален`, 'success');
    } catch (err) {
        showError(`Ошибка удаления: ${err.message}`);
    }
}

// ============================================================
// РАБОЧАЯ ПАМЯТЬ
// ============================================================

async function loadWorkingMemory() {
    try {
        const response = await fetch('/api/working_memory');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderWorkingMemory(data.working_memory);
    } catch (err) {
        console.error('Ошибка загрузки рабочей памяти:', err);
        const container = document.getElementById('workingMemoryContent');
        if (container) {
            container.innerHTML = '<div class="empty-memory">❌ Ошибка загрузки памяти</div>';
        }
    }
}

function renderWorkingMemory(summaries) {
    const container = document.getElementById('workingMemoryContent');
    if (!container) return;
    
    if (!summaries || summaries.length === 0) {
        container.innerHTML = '<div class="empty-memory">📭 Рабочая память пуста</div>';
        return;
    }
    
    container.innerHTML = summaries.map((summary, index) => `
        <div class="memory-item">
            <div class="memory-number">#${index + 1}</div>
            <div class="memory-text">${escapeHtml(summary)}</div>
        </div>
    `).join('');
}

function toggleWorkingMemory() {
    const panel = document.getElementById('workingMemoryPanel');
    if (!panel) return;
    
    if (panel.style.display === 'none' || !panel.style.display) {
        panel.style.display = 'block';
        loadWorkingMemory();
        // Обновляем текст кнопки
        const btn = document.querySelector('.memory-btn');
        if (btn) {
            btn.innerHTML = '🧠 Скрыть память <span class="badge" id="workingMemoryBadge">0</span>';
        }
    } else {
        panel.style.display = 'none';
        const btn = document.querySelector('.memory-btn');
        if (btn) {
            btn.innerHTML = '🧠 Память <span class="badge" id="workingMemoryBadge">0</span>';
        }
    }
}

async function clearWorkingMemory() {
    if (!confirm('Очистить всю рабочую память?')) return;
    
    try {
        const response = await fetch('/api/working_memory', {
            method: 'DELETE'
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await response.json();
        await loadWorkingMemory();
        updateWorkingMemoryDisplay();
        showError('Рабочая память очищена', 'success');
    } catch (err) {
        showError(`Ошибка очистки: ${err.message}`);
    }
}

// ============================================================
// ОБНОВЛЕНИЕ ИНТЕРФЕЙСА
// ============================================================

function updateCurrentAgentDisplay() {
    const display = document.getElementById('currentAgentDisplay');
    if (display && currentAgentId && agents[currentAgentId]) {
        display.textContent = `🤖 ${agents[currentAgentId].name}`;
    } else if (display) {
        display.textContent = '🤖 нет агента';
    }
}

async function updateWorkingMemoryDisplay() {
    try {
        const response = await fetch('/api/working_memory');
        if (!response.ok) return;
        const data = await response.json();
        
        const badge = document.getElementById('workingMemoryBadge');
        if (badge) {
            badge.textContent = data.count || 0;
            badge.title = `${data.count || 0} сводок в рабочей памяти`;
        }
    } catch (err) {
        console.error('Error updating working memory display:', err);
    }
}

function updateAgentInfo() {
    const agentIdSpan = document.getElementById('agentIdLabel');
    if (!agentIdSpan) return;
    
    let info = '';
    if (currentUserId) {
        const select = document.getElementById('userSelect');
        const selectedOption = select?.options[select.selectedIndex];
        const userName = selectedOption ? selectedOption.text.split(' (')[0] : 'Unknown';
        info = `${userName}`;
    }
    
    if (currentAgentId && agents[currentAgentId]) {
        info += ` → ${agents[currentAgentId].name}`;
    } else if (currentAgentId) {
        info += ` → ${currentAgentId}`;
    }
    
    if (info) {
        agentIdSpan.textContent = info;
    } else {
        agentIdSpan.textContent = 'загрузка...';
    }
}

// ============================================================
// ОТПРАВКА СООБЩЕНИЙ
// ============================================================

function renderMessages(history) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    container.innerHTML = '';
    if (!history || history.length === 0) {
        container.innerHTML = `<div class="message assistant"><div class="message-bubble">💬 Начните диалог с агентом!</div></div>`;
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

function appendMessageToDOM(role, content, scroll = true) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    messageDiv.innerHTML = `
        <div class="message-bubble">${escapeHtml(content)}</div>
        <div class="message-meta">${role === 'user' ? '👤 Вы' : '🤖 Ассистент'} · ${new Date().toLocaleTimeString()}</div>
    `;
    container.appendChild(messageDiv);
    if (scroll) scrollToBottom();
}

let typingElement = null;
function showTypingIndicator() {
    hideTypingIndicator();
    const container = document.getElementById('chatMessages');
    if (!container) return;
    
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

async function sendMessage() {
    const input = document.getElementById('messageInput');
    if (!input) return;
    
    const message = input.value.trim();
    if (!message) return;
    if (isWaiting) {
        showError('Подождите, ответ уже загружается');
        return;
    }

    isWaiting = true;
    const sendBtn = document.getElementById('sendBtn');
    const resetBtn = document.getElementById('resetBtn');
    if (sendBtn) sendBtn.disabled = true;
    if (resetBtn) resetBtn.disabled = true;
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
        // Обновляем информацию об агенте (количество сообщений)
        await loadAgents();
        updateWorkingMemoryDisplay();
    } catch (err) {
        hideTypingIndicator();
        const container = document.getElementById('chatMessages');
        if (container) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'message assistant';
            errorDiv.innerHTML = `<div class="message-bubble" style="background:#f8d7da; color:#721c24;">❌ Не удалось получить ответ: ${escapeHtml(err.message)}</div>`;
            container.appendChild(errorDiv);
            scrollToBottom();
        }
        showError(`Ошибка: ${err.message}`);
    } finally {
        isWaiting = false;
        if (sendBtn) sendBtn.disabled = false;
        if (resetBtn) resetBtn.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

async function resetChat() {
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        return;
    }
    if (!confirm('Очистить историю текущего агента?')) return;
    try {
        const response = await fetch('/reset', { method: 'POST' });
        if (!response.ok) throw new Error(`Reset failed: ${response.status}`);
        await response.json();
        const container = document.getElementById('chatMessages');
        if (container) {
            container.innerHTML = `<div class="message assistant"><div class="message-bubble">🗑️ История очищена. Начните новый диалог.</div></div>`;
        }
        await loadAgents();
        showError('История успешно очищена', 'success');
    } catch (err) {
        showError(`Ошибка очистки: ${err.message}`);
    }
}

// ============================================================
// УТИЛИТЫ
// ============================================================

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function scrollToBottom() {
    const container = document.getElementById('chatMessages');
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

function showError(msg, type = 'error') {
    // Удаляем предыдущие тосты
    const oldToasts = document.querySelectorAll('.error-toast');
    oldToasts.forEach(toast => toast.remove());
    
    const toast = document.createElement('div');
    toast.className = `error-toast ${type}`;
    toast.innerText = msg;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        if (toast.parentNode) {
            toast.remove();
        }
    }, 4000);
}

// ============================================================
// ИНИЦИАЛИЗАЦИЯ
// ============================================================

// Автоматическое расширение textarea
const textarea = document.getElementById('messageInput');
if (textarea) {
    textarea.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 150) + 'px';
    });
}

// Закрытие модальных окон по клику вне их
document.addEventListener('DOMContentLoaded', function() {
    const userModal = document.getElementById('createUserModal');
    if (userModal) {
        userModal.addEventListener('click', function(e) {
            if (e.target === this) {
                closeCreateUserModal();
            }
        });
    }
    
    const agentModal = document.getElementById('createAgentModal');
    if (agentModal) {
        agentModal.addEventListener('click', function(e) {
            if (e.target === this) {
                closeCreateAgentModal();
            }
        });
    }
});

// Клавиша Enter для создания агента
document.getElementById('agentNameInput')?.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        createAgent();
    }
});

// Клавиша Enter для создания пользователя
document.getElementById('userNameInput')?.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        createUser();
    }
});

// Загружаем данные при старте
document.addEventListener('DOMContentLoaded', function() {
    loadUsers();
});

// Периодическое обновление (каждые 30 секунд)
setInterval(() => {
    updateAgentInfo();
    updateWorkingMemoryDisplay();
}, 30000);