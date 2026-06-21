// ============================================================
// LLM Agent IDE — chat.js
// VS Code-like interface with activity bar, sidebar, tabs,
// bottom panel, status bar, and streaming chat.
// ============================================================

// ============================================================
// GLOBAL STATE
// ============================================================
let isWaiting = false;
let currentUserId = null;
let currentAgentId = null;
let agents = {};           // { agentId: { name, history_length, ... } }
let usersList = [];        // [{ user_id, name, agent_count, ... }]
let openTabs = [];         // [{ agentId, name, history }]
let activeTabIdx = -1;

// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    initActivityBar();
    initPanelTabs();
    initTextarea();
    initModals();
    loadUsers();
});

// ============================================================
// ACTIVITY BAR
// ============================================================

function initActivityBar() {
    const icons = document.querySelectorAll('.activity-icon');
    icons.forEach(icon => {
        icon.addEventListener('click', () => {
            const panel = icon.dataset.panel;
            switchSidebarPanel(panel);
        });
    });
}

function switchSidebarPanel(panel) {
    // Update activity bar
    document.querySelectorAll('.activity-icon').forEach(i => {
        i.classList.toggle('active', i.dataset.panel === panel);
    });
    // Update sidebar panels
    document.querySelectorAll('.sidebar-panel').forEach(p => {
        p.classList.toggle('active', p.id === `panel-${panel}`);
    });
    // Ensure sidebar is visible
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.add('open');
    
    if (panel === 'settings') {
        updateSettingsPanel();
    }
}

// Toggle sidebar (click active icon again)
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.toggle('open');
}

// ============================================================
// BOTTOM PANEL
// ============================================================

function initPanelTabs() {
    const tabs = document.querySelectorAll('.panel-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const pane = tab.dataset.panel;
            switchPanelPane(pane);
        });
    });
}

function switchPanelPane(pane) {
    document.querySelectorAll('.panel-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.panel === pane);
    });
    document.querySelectorAll('.panel-pane').forEach(p => {
        p.classList.toggle('active', p.id === `pane-${pane}`);
    });
}

function toggleBottomPanel() {
    const panel = document.getElementById('bottomPanel');
    if (!panel) return;
    if (panel.style.display === 'none' || !panel.style.display) {
        panel.style.display = 'flex';
        updateWorkingMemoryDisplay();
        switchPanelPane('problems');
    } else {
        panel.style.display = 'none';
    }
}

// ============================================================
// MODALS
// ============================================================

function initModals() {
    // Close modals on backdrop click
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', function(e) {
            if (e.target === this) {
                this.style.display = 'none';
            }
        });
    });
}

function showCreateUserModal() {
    const modal = document.getElementById('createUserModal');
    if (modal) {
        modal.style.display = 'flex';
        const input = document.getElementById('userNameInput');
        if (input) { input.value = ''; input.focus(); }
        const fileInput = document.getElementById('preferencesFileInput');
        if (fileInput) fileInput.value = '';
    }
}

function closeCreateUserModal() {
    const modal = document.getElementById('createUserModal');
    if (modal) modal.style.display = 'none';
}

function showCreateAgentModal() {
    const modal = document.getElementById('createAgentModal');
    if (modal) {
        modal.style.display = 'flex';
        const input = document.getElementById('agentNameInput');
        if (input) { input.value = ''; input.focus(); }
    }
}

function closeCreateAgentModal() {
    const modal = document.getElementById('createAgentModal');
    if (modal) modal.style.display = 'none';
}

// ============================================================
// TEXTAREA AUTO-RESIZE
// ============================================================

function initTextarea() {
    const textarea = document.getElementById('messageInput');
    if (textarea) {
        textarea.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 150) + 'px';
        });
    }
}

// ============================================================
// TOAST NOTIFICATIONS
// ============================================================

function showToast(msg, type = 'info') {
    const old = document.querySelectorAll('.toast');
    old.forEach(t => t.remove());
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        if (toast.parentNode) toast.remove();
    }, 4000);
}

// deprecated alias for compatibility
function showError(msg, type) {
    showToast(msg, type === 'success' ? 'success' : 'error');
}

// ============================================================
// STATUS BAR
// ============================================================

function updateStatusBar() {
    const userEl = document.getElementById('statusUser');
    const agentEl = document.getElementById('statusAgent');
    const msgEl = document.getElementById('statusMessages');
    const modelEl = document.getElementById('statusModel');
    
    if (userEl && currentUserId) {
        const user = usersList.find(u => u.user_id === currentUserId);
        userEl.textContent = user ? `👤 ${user.name}` : '👤 неизвестно';
    }
    
    if (agentEl && currentAgentId && agents[currentAgentId]) {
        agentEl.textContent = `🤖 ${agents[currentAgentId].name}`;
    } else if (agentEl && currentAgentId) {
        agentEl.textContent = `🤖 ${currentAgentId}`;
    }
    
    if (msgEl && openTabs[activeTabIdx]) {
        const count = openTabs[activeTabIdx].history.length;
        msgEl.textContent = `💬 ${count} сообщ.`;
    } else if (msgEl) {
        msgEl.textContent = '💬 0 сообщ.';
    }
}

function updateSettingsPanel() {
    const info = document.getElementById('settingsInfo');
    if (info) {
        fetch('/info').then(r => r.json()).then(data => {
            info.innerHTML = `
                <p><strong>Model:</strong> ${data.model || 'N/A'}</p>
                <p><strong>Agent ID:</strong> ${data.agent_id || 'N/A'}</p>
                ${data.user ? `<p><strong>User:</strong> ${data.user.name}</p>` : ''}
            `;
        }).catch(() => {
            info.textContent = 'Не удалось загрузить настройки';
        });
    }
}

// ============================================================
// API: LOAD USERS
// ============================================================

async function loadUsers() {
    try {
        const response = await fetch('/api/users');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        
        usersList = data.users;
        currentUserId = data.current_user_id;
        
        if (currentUserId) {
            await loadAgents();
            await loadHistory();
            updateWorkingMemoryDisplay();
        }
        
        renderExplorer();
        updateStatusBar();
        
    } catch (err) {
        console.error('Error loading users:', err);
        showToast('Не удалось загрузить пользователей', 'error');
    }
}

// ============================================================
// API: LOAD AGENTS
// ============================================================

async function loadAgents() {
    try {
        const response = await fetch('/api/agents');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        
        agents = {};
        if (data.agents) {
            data.agents.forEach(agent => {
                agents[agent.agent_id] = agent;
                if (agent.is_current) {
                    currentAgentId = agent.agent_id;
                }
            });
        }
        
        if (!currentAgentId && data.agents && data.agents.length > 0) {
            currentAgentId = data.agents[0].agent_id;
        }
        
        renderExplorer();
        updateStatusBar();
        
    } catch (err) {
        console.error('Error loading agents:', err);
        showToast('Не удалось загрузить агентов', 'error');
    }
}

// ============================================================
// API: LOAD HISTORY
// ============================================================

async function loadHistory() {
    try {
        const response = await fetch('/history');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        
        if (data.agent_id) {
            currentAgentId = data.agent_id;
        }
        
        // Open tab for current agent
        openTabForAgent(currentAgentId, data.agent_name || 'Agent', data.history || []);
        
        renderMessages(data.history || []);
        updateStatusBar();
        
    } catch (err) {
        console.error('Error loading history:', err);
        showToast('Не удалось загрузить историю', 'error');
    }
}

// ============================================================
// SIDEBAR EXPLORER TREE
// ============================================================

function renderExplorer() {
    const tree = document.getElementById('explorerTree');
    if (!tree) return;
    
    let html = '';
    
    // USERS section
    html += '<div class="tree-section">';
    html += '<div class="tree-section-header" onclick="toggleTreeSection(this)">';
    html += '<span class="arrow">▾</span> ПОЛЬЗОВАТЕЛИ';
    html += '</div>';
    html += '<div class="tree-section-items">';
    
    usersList.forEach(user => {
        const isActive = user.user_id === currentUserId;
        const agentCount = user.agent_count || 0;
        html += `<div class="tree-item ${isActive ? 'active' : ''}" 
            onclick="switchUserById('${user.user_id}')"
            title="${user.name} — ${agentCount} agents">`;
        html += `<span class="item-icon">${isActive ? '●' : '○'}</span>`;
        html += `<span class="item-label">${escapeHtml(user.name)}</span>`;
        html += `<span style="color:var(--text-muted);font-size:11px;">${agentCount}</span>`;
        html += '<div class="item-actions">';
        html += `<button onclick="event.stopPropagation();deleteUserById('${user.user_id}')" class="danger" title="Delete user">✕</button>`;
        html += '</div></div>';
    });
    
    html += '</div></div>';
    
    // AGENTS section
    html += '<div class="tree-section">';
    html += '<div class="tree-section-header" onclick="toggleTreeSection(this)">';
    html += '<span class="arrow">▾</span> АГЕНТЫ';
    html += '</div>';
    html += '<div class="tree-section-items">';
    
    Object.entries(agents).forEach(([id, agent]) => {
        const isActive = id === currentAgentId;
        const tabOpen = openTabs.some(t => t.agentId === id);
        html += `<div class="tree-item ${isActive ? 'active' : ''}" 
            onclick="switchAgentById('${id}')"
            title="${agent.name} — ${agent.history_length || 0} messages">`;
        html += `<span class="item-icon">${isActive ? '💬' : '📄'}</span>`;
        html += `<span class="item-label">${escapeHtml(agent.name)}</span>`;
        if (tabOpen && !isActive) {
            html += `<span style="color:var(--accent);font-size:10px;">●</span>`;
        }
        html += '<div class="item-actions">';
        html += `<button onclick="event.stopPropagation();deleteAgentById('${id}')" class="danger" title="Delete agent">✕</button>`;
        html += '</div></div>';
    });
    
    html += '</div></div>';
    
    // MEMORY section
    html += '<div class="tree-section">';
    html += '<div class="tree-section-header" onclick="toggleTreeSection(this)">';
    html += '<span class="arrow">▾</span> ПАМЯТЬ';
    html += '</div>';
    html += '<div class="tree-section-items" id="explorerMemoryItems">';
    html += '<div class="sidebar-empty" style="padding:8px;font-size:11px;">Нажмите для загрузки</div>';
    html += '</div></div>';
    
    tree.innerHTML = html;
}

async function toggleTreeSection(header) {
    header.classList.toggle('collapsed');
    // Load memory items when expanding
    if (!header.classList.contains('collapsed') && 
        header.textContent.includes('MEMORY')) {
        await loadMemoryForExplorer();
    }
}

async function loadMemoryForExplorer() {
    const container = document.getElementById('explorerMemoryItems');
    if (!container) return;
    
    try {
        const response = await fetch('/api/working_memory');
        if (!response.ok) return;
        const data = await response.json();
        
        if (!data.working_memory || data.working_memory.length === 0) {
            container.innerHTML = '<div class="sidebar-empty" style="padding:8px;font-size:11px;">Пусто</div>';
            return;
        }
        
        container.innerHTML = data.working_memory.map((sum, i) => `
            <div class="tree-item" title="${escapeHtml(sum)}" 
                 onclick="showToast('${escapeHtml(sum.slice(0, 200))}', 'info')">
                <span class="item-icon">📝</span>
                <span class="item-label">Сводка №${i + 1}</span>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<div class="sidebar-empty" style="padding:8px;font-size:11px;">Error</div>';
    }
}

// ============================================================
// USER MANAGEMENT
// ============================================================

async function switchUserById(userId) {
    if (userId === currentUserId) return;
    if (isWaiting) {
        showToast('Дождитесь завершения текущего запроса', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/users/${userId}/switch`, { method: 'POST' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Ошибка переключения');
        
        const data = await response.json();
        currentUserId = data.user.user_id;
        
        await loadAgents();
        await loadHistory();
        renderExplorer();
        updateStatusBar();
        showToast(`Switched to ${data.user.name}`, 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

async function deleteUserById(userId) {
    if (isWaiting) {
        showToast('Дождитесь завершения текущего запроса', 'error');
        return;
    }
    
    const user = usersList.find(u => u.user_id === userId);
    const userName = user ? user.name : userId;
    
    if (!confirm(`Удалить пользователя «${userName}»?`)) return;
    
    try {
        const response = await fetch(`/api/users/${userId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Ошибка удаления');
        
        await loadUsers();
        showToast(`User "${userName}" deleted`, 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

async function createUser() {
    const nameInput = document.getElementById('userNameInput');
    const name = nameInput ? nameInput.value.trim() : '';
    
    if (!name) { showToast('Введите имя пользователя', 'error'); return; }
    
    const fileInput = document.getElementById('preferencesFileInput');
    const formData = new FormData();
    formData.append('name', name);
    if (fileInput && fileInput.files.length > 0) {
        formData.append('preferences', fileInput.files[0]);
    }
    
    try {
        const response = await fetch('/api/users', { method: 'POST', body: formData });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Ошибка создания');
        
        const data = await response.json();
        closeCreateUserModal();
        await loadUsers();
        showToast(`User "${data.user.name}" created`, 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

// Compatibility: called from HTML onchange
function switchUser(userId) {
    switchUserById(userId);
}

// Compatibility: called from HTML
function deleteCurrentUser() {
    if (currentUserId) deleteUserById(currentUserId);
}

// ============================================================
// AGENT MANAGEMENT
// ============================================================

async function switchAgentById(agentId) {
    if (agentId === currentAgentId) return;
    if (isWaiting) {
        showToast('Дождитесь завершения текущего запроса', 'error');
        return;
    }
    
    const agentName = agents[agentId]?.name || agentId;
    
    if (!confirm(`Переключиться на агента «${agentName}»? Текущая история будет сохранена в рабочую память.`)) return;
    
    try {
        const response = await fetch(`/api/agents/${agentId}/switch`, { method: 'POST' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Ошибка переключения');
        
        const data = await response.json();
        currentAgentId = data.current_agent_id;
        
        if (data.summary_generated) {
            showToast('Сводка добавлена в рабочую память', 'success');
        }
        
        await loadAgents();
        await loadHistory();
        renderExplorer();
        updateWorkingMemoryDisplay();
        updateStatusBar();
        
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

async function deleteAgentById(agentId) {
    if (isWaiting) {
        showToast('Дождитесь завершения текущего запроса', 'error');
        return;
    }
    
    const agentName = agents[agentId]?.name || agentId;
    if (!confirm(`Удалить агента «${agentName}»?`)) return;
    
    try {
        const response = await fetch(`/api/agents/${agentId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Ошибка удаления');
        
        // Close tab if open
        closeTab(agentId);
        await loadAgents();
        await loadHistory();
        renderExplorer();
        updateStatusBar();
        showToast(`Agent "${agentName}" deleted`, 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

async function createAgent() {
    const nameInput = document.getElementById('agentNameInput');
    const name = nameInput ? nameInput.value.trim() : '';
    
    if (!name) { showToast('Введите имя агента', 'error'); return; }
    
    try {
        const response = await fetch('/api/agents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Ошибка создания');
        
        const data = await response.json();
        closeCreateAgentModal();
        await loadAgents();
        await loadHistory();
        renderExplorer();
        showToast(`Agent "${data.name}" created`, 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

// Compatibility
function switchAgent(agentId) {
    switchAgentById(agentId);
}

function deleteCurrentAgent() {
    if (currentAgentId) deleteAgentById(currentAgentId);
}

// ============================================================
// TAB MANAGEMENT
// ============================================================

function openTabForAgent(agentId, name, history) {
    // Check if tab already exists
    const existingIdx = openTabs.findIndex(t => t.agentId === agentId);
    if (existingIdx >= 0) {
        activeTabIdx = existingIdx;
        // Refresh history
        openTabs[existingIdx].history = history;
    } else {
        openTabs.push({ agentId, name, history });
        activeTabIdx = openTabs.length - 1;
    }
    renderTabs();
    hideWelcome();
}

function closeTab(agentId) {
    const idx = openTabs.findIndex(t => t.agentId === agentId);
    if (idx < 0) return;
    
    openTabs.splice(idx, 1);
    
    if (openTabs.length === 0) {
        activeTabIdx = -1;
        showWelcome();
    } else if (activeTabIdx >= openTabs.length) {
        activeTabIdx = openTabs.length - 1;
        const tab = openTabs[activeTabIdx];
        renderMessages(tab.history);
    } else if (idx <= activeTabIdx) {
        activeTabIdx = Math.max(0, activeTabIdx - 1);
        const tab = openTabs[activeTabIdx];
        renderMessages(tab.history);
    }
    
    renderTabs();
}

function activateTab(idx) {
    if (idx < 0 || idx >= openTabs.length) return;
    activeTabIdx = idx;
    const tab = openTabs[idx];
    currentAgentId = tab.agentId;
    renderMessages(tab.history);
    renderTabs();
    updateStatusBar();
}

function renderTabs() {
    const bar = document.getElementById('tabBar');
    if (!bar) return;
    
    bar.innerHTML = openTabs.map((tab, i) => `
        <div class="tab ${i === activeTabIdx ? 'active' : ''}" onclick="activateTab(${i})">
            <span class="tab-icon">💬</span>
            <span>${escapeHtml(tab.name)}</span>
            <button class="tab-close" onclick="event.stopPropagation();closeTab('${tab.agentId}')">×</button>
        </div>
    `).join('');
}

function showWelcome() {
    const welcome = document.getElementById('welcomeScreen');
    const messages = document.getElementById('chatMessages');
    if (welcome) welcome.style.display = 'flex';
    if (messages) messages.style.display = 'none';
}

function hideWelcome() {
    const welcome = document.getElementById('welcomeScreen');
    const messages = document.getElementById('chatMessages');
    if (welcome) welcome.style.display = 'none';
    if (messages) messages.style.display = 'flex';
}

// ============================================================
// RENDER MESSAGES
// ============================================================

function renderMessages(history) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    container.innerHTML = '';
    
    if (!history || history.length === 0) {
        container.innerHTML = `<div class="message assistant"><div class="message-bubble">Start a conversation by typing below.</div></div>`;
        return;
    }
    
    history.forEach(msg => {
        if (msg.role === 'user' || msg.role === 'assistant') {
            appendMessageToDOM(msg.role, msg.content, false);
        }
    });
    
    scrollToBottom();
}

function appendMessageToDOM(role, content, scroll = true) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    msgDiv.innerHTML = `
        <div class="message-header">
            <span class="message-role">${role === 'user' ? 'You' : 'Assistant'}</span>
            <span class="message-time">${new Date().toLocaleTimeString()}</span>
        </div>
        <div class="message-bubble">${escapeHtml(content)}</div>
    `;
    container.appendChild(msgDiv);
    if (scroll) scrollToBottom();
}

function scrollToBottom() {
    const editor = document.getElementById('editorContent');
    if (editor) {
        editor.scrollTop = editor.scrollHeight;
    }
}

// ============================================================
// SEND MESSAGE (with streaming)
// ============================================================

async function sendMessage() {
    const input = document.getElementById('messageInput');
    if (!input) return;
    
    const message = input.value.trim();
    if (!message) return;
    if (isWaiting) {
        showToast('Дождитесь ответа на текущий запрос', 'info');
        return;
    }
    
    hideWelcome();
    
    isWaiting = true;
    const sendBtn = document.getElementById('sendBtn');
    const resetBtn = document.getElementById('resetBtn');
    if (sendBtn) sendBtn.disabled = true;
    if (resetBtn) resetBtn.disabled = true;
    input.disabled = true;
    
    appendMessageToDOM('user', message, true);
    input.value = '';
    input.style.height = 'auto';
    
    // Show stream indicator
    const streamBubble = document.getElementById('streamBubble');
    const streamContent = document.getElementById('streamContent');
    if (streamBubble) streamBubble.style.display = 'block';
    if (streamContent) streamContent.textContent = '…';
    scrollToBottom();
    
    try {
        await sendMessageStream(message);
        await loadAgents();
        updateWorkingMemoryDisplay();
        updateStatusBar();
        renderExplorer();
    } catch (err) {
        if (streamContent) {
            streamContent.innerHTML = `<span style="color:var(--red);">Ошибка: ${escapeHtml(err.message)}</span>`;
        }
        showToast(`Ошибка: ${err.message}`, 'error');
    } finally {
        if (streamBubble) streamBubble.style.display = 'none';
        isWaiting = false;
        if (sendBtn) sendBtn.disabled = false;
        if (resetBtn) resetBtn.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

async function sendMessageStream(message) {
    const response = await fetch('/send/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, user_id: currentUserId })
    });
    
    if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Ошибка сервера: ${response.status}`);
    }
    
    const streamContent = document.getElementById('streamContent');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullContent = '';
    
    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.token) {
                            fullContent += data.token;
                            if (streamContent) streamContent.textContent = fullContent;
                            scrollToBottom();
                        }
                        if (data.error) {
                            if (streamContent) {
                                streamContent.innerHTML = `<span style="color:var(--red);">Error: ${escapeHtml(data.error)}</span>`;
                            }
                        }
                        if (data.done) {
                            // Add to DOM
                            if (streamContent) streamContent.textContent = '';
                            appendMessageToDOM('assistant', fullContent, true);
                            // Update tab history
                            if (activeTabIdx >= 0 && activeTabIdx < openTabs.length) {
                                openTabs[activeTabIdx].history.push(
                                    { role: 'user', content: message },
                                    { role: 'assistant', content: fullContent }
                                );
                            }
                        }
                    } catch (e) { /* skip malformed */ }
                }
            }
        }
    } catch (err) {
        if (streamContent) {
            streamContent.innerHTML = `<span style="color:var(--red);">Stream error: ${escapeHtml(err.message)}</span>`;
        }
    }
}

// Legacy regular send (non-streaming)
async function sendMessageRegular(message) {
    const response = await fetch('/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, user_id: currentUserId })
    });
    if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Ошибка сервера: ${response.status}`);
    }
    const data = await response.json();
    document.getElementById('streamBubble').style.display = 'none';
    renderMessages(data.history);
}

// ============================================================
// RESET CHAT
// ============================================================

async function resetChat() {
    if (isWaiting) {
        showToast('Дождитесь завершения текущего запроса', 'info');
        return;
    }
    if (!confirm('Очистить историю текущего агента?')) return;
    
    try {
        const response = await fetch('/reset', { method: 'POST' });
        if (!response.ok) throw new Error(`Reset failed: ${response.status}`);
        await response.json();
        
        const container = document.getElementById('chatMessages');
        if (container) {
            container.innerHTML = `<div class="message assistant"><div class="message-bubble">🗑 History cleared. Start a new conversation.</div></div>`;
        }
        
        if (activeTabIdx >= 0 && activeTabIdx < openTabs.length) {
            openTabs[activeTabIdx].history = [];
        }
        
        await loadAgents();
        renderExplorer();
        updateStatusBar();
        showToast('История очищена', 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

// ============================================================
// WORKING MEMORY
// ============================================================

async function updateWorkingMemoryDisplay() {
    try {
        const response = await fetch('/api/working_memory');
        if (!response.ok) return;
        const data = await response.json();
        
        const badge = document.getElementById('memoryBadge');
        if (badge) badge.textContent = data.count || 0;
        
        // Update memory pane if panel is open
        const memoryList = document.getElementById('memoryList');
        if (memoryList && document.getElementById('bottomPanel')?.style.display !== 'none') {
            renderMemoryItems(data.working_memory || []);
        }
    } catch (err) {
        console.error('Error updating working memory:', err);
    }
}

function renderMemoryItems(summaries) {
    const container = document.getElementById('memoryList');
    if (!container) return;
    
    if (!summaries || summaries.length === 0) {
        container.innerHTML = '    <div class="panel-empty">Рабочая память пуста</div>';
        return;
    }
    
    container.innerHTML = summaries.map((sum, i) => `
        <div class="memory-item">
            <div class="memory-number">#${i + 1}</div>
            <div class="memory-text">${escapeHtml(sum)}</div>
        </div>
    `).join('');
}

async function clearWorkingMemory() {
    if (!confirm('Очистить всю рабочую память?')) return;
    
    try {
        const response = await fetch('/api/working_memory', { method: 'DELETE' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await response.json();
        
        updateWorkingMemoryDisplay();
        showToast('Рабочая память очищена', 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

function toggleWorkingMemory() {
    toggleBottomPanel();
    switchPanelPane('memory');
    updateWorkingMemoryDisplay();
}

// ============================================================
// UTILITIES
// ============================================================

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============================================================
// PERIODIC REFRESH
// ============================================================

setInterval(() => {
    if (!isWaiting) {
        updateStatusBar();
    }
}, 30000);

// ============================================================
// SWARM MODE
// ============================================================

let swarmTaskId = null;
let swarmTaskData = null;
let swarmStageLabels = {};
let swarmStageDescs = {};
let swarmTasks = [];
let userInvariants = [];
let userInvariantsContent = '';

// ---- Modal ----

function showCreateSwarmModal() {
    const modal = document.getElementById('createSwarmModal');
    if (modal) {
        modal.style.display = 'flex';
        const textarea = document.getElementById('swarmTaskInput');
        if (textarea) { textarea.value = ''; textarea.focus(); }
    }
}

function closeCreateSwarmModal() {
    const modal = document.getElementById('createSwarmModal');
    if (modal) modal.style.display = 'none';
}

async function createSwarmTask() {
    const textarea = document.getElementById('swarmTaskInput');
    const description = textarea ? textarea.value.trim() : '';
    if (!description) { showToast('Введите описание задачи', 'error'); return; }

    try {
        const response = await fetch('/api/swarm/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ description, user_id: currentUserId })
        });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Ошибка создания');

        const data = await response.json();
        closeCreateSwarmModal();
        await loadSwarmTasks();
        openSwarmTask(data.task.task_id);
        showToast('Задача роя создана', 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

// ---- Task List ----

async function loadSwarmTasks() {
    try {
        const response = await fetch(`/api/swarm/tasks?user_id=${currentUserId || ''}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        swarmTasks = data.tasks || [];
        swarmStageLabels = data.stage_labels || {};
        swarmStageDescs = data.stage_descriptions || {};
        renderSwarmTasks();
    } catch (err) {
        console.error('Error loading swarm tasks:', err);
    }
}

async function loadInvariants() {
    try {
        const response = await fetch(`/api/invariants?user_id=${currentUserId || ''}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        userInvariants = data.invariants || [];
        userInvariantsContent = data.content || '';
    } catch (err) {
        console.error('Error loading invariants:', err);
    }
}

function renderSwarmTasks() {
    const container = document.getElementById('swarmTaskList');
    const empty = document.getElementById('swarmEmpty');
    if (!container) return;

    if (swarmTasks.length === 0) {
        if (empty) empty.style.display = 'block';
        container.innerHTML = '';
        container.appendChild(empty);
        return;
    }

    let html = '';
    swarmTasks.forEach(task => {
        const stage = task.current_stage;
        const label = swarmStageLabels[stage] || stage;
        const isActive = task.task_id === swarmTaskId;
        const isDone = stage === 'done';
        const isCancelled = stage === 'cancelled';
        const desc = (task.description || '').slice(0, 60);

        html += `<div class="tree-item ${isActive ? 'active' : ''}" onclick="openSwarmTask('${task.task_id}')" title="${escapeHtml(task.description)}">
            <span class="item-icon">${isDone ? '✅' : isCancelled ? '❌' : '🔄'}</span>
            <span class="item-label">${escapeHtml(desc)}${desc.length >= 60 ? '...' : ''}</span>
            <span class="stage-badge ${isActive ? 'active' : ''}">${label}</span>
            <div class="item-actions">
                <button onclick="event.stopPropagation();deleteSwarmTask('${task.task_id}')" class="danger" title="Delete task">✕</button>
            </div>
        </div>`;
    });

    container.innerHTML = html;
    if (empty) empty.style.display = swarmTasks.length === 0 ? 'block' : 'none';
}

// ---- Task View ----

async function openSwarmTask(taskId) {
    swarmTaskId = taskId;
    
    // Show swarm view, hide chat
    const swarmView = document.getElementById('swarmView');
    const welcome = document.getElementById('welcomeScreen');
    const chatMsgs = document.getElementById('chatMessages');
    const tabBar = document.getElementById('tabBar');
    
    if (swarmView) swarmView.style.display = 'flex';
    if (welcome) welcome.style.display = 'none';
    if (chatMsgs) chatMsgs.style.display = 'none';
    if (tabBar) tabBar.innerHTML = '';

    // Load task data and invariants
    await Promise.all([refreshSwarmTask(), loadInvariants()]);
    renderSwarmTasks();
    
    // Update sidebar
    switchSidebarPanel('swarm');
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.add('open');
}

function closeSwarmView() {
    const swarmView = document.getElementById('swarmView');
    const welcome = document.getElementById('welcomeScreen');
    const chatMsgs = document.getElementById('chatMessages');
    
    if (swarmView) swarmView.style.display = 'none';
    if (welcome) welcome.style.display = 'flex';
    if (chatMsgs) chatMsgs.style.display = 'none';
    
    swarmTaskId = null;
    swarmTaskData = null;
    
    // Switch back to explorer
    switchSidebarPanel('explorer');
}

async function refreshSwarmTask() {
    if (!swarmTaskId) return;

    try {
        const response = await fetch(`/api/swarm/tasks/${swarmTaskId}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        swarmTaskData = data.task;
        swarmStageLabels = data.stage_labels || swarmStageLabels;
        swarmStageDescs = data.stage_descriptions || swarmStageDescs;
        
        renderSwarmView(data);
    } catch (err) {
        showToast(`Ошибка загрузки задачи: ${err.message}`, 'error');
        closeSwarmView();
    }
}

function renderSwarmView(data) {
    const task = data.task;
    const stage = task.current_stage;
    const progress = data.progress_pct || 0;

    // Header
    const titleEl = document.getElementById('swarmTaskTitle');
    const idEl = document.getElementById('swarmTaskId');
    if (titleEl) titleEl.textContent = (task.description || 'Задача роя').slice(0, 80);
    if (idEl) idEl.textContent = '#' + task.task_id;

    // Progress bar
    const fill = document.getElementById('swarmProgressFill');
    if (fill) fill.style.width = progress + '%';

    // Stage indicators
    updateSwarmStages(stage);

    // Current stage info
    const iconEl = document.getElementById('swarmStageIcon');
    const labelEl = document.getElementById('swarmStageLabel');
    const descEl = document.getElementById('swarmStageDesc');
    
    const stageIcons = {
        idle: '⏳', planning: '📋', plan_review: '👀', executing: '⚡',
        exec_review: '👀', validating: '🔍', validation_review: '👀',
        finishing: '📝', done: '✅', paused: '⏸', cancelled: '❌', failed: '❌'
    };
    const label = swarmStageLabels[stage] || stage;
    const desc = swarmStageDescs[stage] || '';

    if (iconEl) iconEl.textContent = stageIcons[stage] || '🔄';
    if (labelEl) labelEl.textContent = label;
    if (descEl) descEl.textContent = desc;

    // Summary content
    updateSwarmSummary(task);

    // Invariants panel
    updateSwarmInvariants(task);

    // Invariant check results
    updateSwarmChecks(task);

    // Controls
    updateSwarmControls(stage);
}

function updateSwarmStages(currentStage) {
    const stageMap = {
        'idle': 'idle', 'planning': 'planning', 'plan_review': 'planning',
        'executing': 'executing', 'exec_review': 'executing',
        'validating': 'validating', 'validation_review': 'validating',
        'finishing': 'done', 'done': 'done'
    };
    const currentGroup = stageMap[currentStage] || 'idle';
    const groups = ['idle', 'planning', 'executing', 'validating', 'done'];
    const groupOrder = { idle: 0, planning: 1, executing: 2, validating: 3, done: 4 };
    const currentIdx = groupOrder[currentGroup] || 0;

    document.querySelectorAll('#swarmStages .swarm-stage').forEach(el => {
        const group = el.dataset.stage;
        const idx = groupOrder[group] || 0;
        el.classList.remove('active', 'completed', 'failed');
        if (idx < currentIdx) el.classList.add('completed');
        else if (idx === currentIdx) el.classList.add('active');
    });

    // Handle cancelled/failed
    if (currentStage === 'cancelled') {
        document.querySelectorAll('#swarmStages .swarm-stage').forEach(el => {
            el.classList.add('failed');
            el.classList.remove('active', 'completed');
        });
    }
}

function updateSwarmSummary(task) {
    const summaryTitle = document.getElementById('swarmSummaryTitle');
    const summaryContent = document.getElementById('swarmSummaryContent');
    const fullOutput = document.getElementById('swarmFullOutput');
    const fullBtn = document.getElementById('swarmFullBtn');

    // Find the most recent completed stage
    const stageOrder = ['planning', 'execution', 'validation', 'finishing'];
    let activeStage = null;
    for (const s of stageOrder) {
        if (task.stages[s] && task.stages[s].status === 'completed') {
            activeStage = task.stages[s];
        }
    }

    if (activeStage) {
        if (summaryTitle) summaryTitle.textContent = `${swarmStageLabels[activeStage.stage] || activeStage.stage} — Summary`;
        if (summaryContent) summaryContent.textContent = activeStage.summary || activeStage.full_output?.slice(0, 500) || '';
        if (fullOutput) {
            fullOutput.textContent = activeStage.full_output || '';
            fullOutput.style.display = 'none';
        }
        if (fullBtn) fullBtn.style.display = activeStage.full_output ? 'inline-block' : 'none';
    } else {
        if (summaryTitle) summaryTitle.textContent = 'Описание задачи';
        if (summaryContent) summaryContent.textContent = task.description || '';
        if (fullOutput) fullOutput.style.display = 'none';
        if (fullBtn) fullBtn.style.display = 'none';
    }
}

function updateSwarmControls(stage) {
    // Hide all action buttons first
    const allBtns = [
        'swarmBtnConfirm', 'swarmBtnStartPlanning', 'swarmBtnStartExecution',
        'swarmBtnStartValidation', 'swarmBtnFinish', 'swarmBtnRetry',
        'swarmBtnRestartStage', 'swarmBtnPause', 'swarmBtnResume'
    ];
    allBtns.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    const show = (id) => { const el = document.getElementById(id); if (el) el.style.display = 'inline-block'; };

    // Dynamic controls based on stage
    switch (stage) {
        case 'idle':
            show('swarmBtnStartPlanning');
            break;
        case 'plan_review':
            show('swarmBtnConfirm');  // approve
            show('swarmBtnRetry');    // reject (re-plan)
            show('swarmBtnPause');
            break;
        case 'exec_review':
            show('swarmBtnConfirm');   // approve → start validation
            show('swarmBtnRetry');     // reject (re-execute)
            show('swarmBtnPause');
            break;
        case 'validation_review':
            show('swarmBtnConfirm');   // approve → finish
            show('swarmBtnRetry');     // reject (re-execute)
            show('swarmBtnPause');
            break;
        case 'done':
        case 'cancelled':
            // No action buttons
            break;
        case 'failed':
            show('swarmBtnRestartStage');  // restart after fixing invariants
            show('swarmBtnPause');
            break;
        case 'paused':
            show('swarmBtnResume');
            break;
        default:
            // During active stages (planning, executing, validating, finishing)
            show('swarmBtnPause');
            break;
    }
}

function updateSwarmInvariants(task) {
    const panel = document.getElementById('swarmInvariants');
    const countEl = document.getElementById('swarmInvariantsCount');
    const listEl = document.getElementById('swarmInvariantsList');

    const invariants = task.invariants || [];
    if (!panel || !listEl) return;

    if (invariants.length === 0) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';
    if (countEl) countEl.textContent = invariants.length + ' шт.';

    let html = '';
    invariants.forEach(inv => {
        html += `<li>${escapeHtml(inv)}</li>`;
    });
    listEl.innerHTML = html;
}

function updateSwarmChecks(task) {
    const panel = document.getElementById('swarmChecks');
    const statusEl = document.getElementById('swarmChecksStatus');
    const listEl = document.getElementById('swarmChecksList');

    if (!panel || !listEl) return;

    const stageChecks = task.stage_checks || {};
    // Filter out internal keys like _failed_stage
    const stageNames = ['planning', 'execution', 'validation', 'finishing'];
    const checks = stageNames.filter(s => stageChecks[s]);

    if (checks.length === 0) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';

    // Determine overall status
    let hasFailures = false;
    let hasPending = false;
    checks.forEach(s => {
        if (!stageChecks[s].passed) hasFailures = true;
    });

    if (hasFailures) {
        if (statusEl) { statusEl.textContent = '❌ НАРУШЕНИЯ'; statusEl.className = 'swarm-checks-status failed'; }
    } else {
        if (statusEl) { statusEl.textContent = '✅ ПРОЙДЕНО'; statusEl.className = 'swarm-checks-status passed'; }
    }

    let html = '';
    checks.forEach(stageName => {
        const check = stageChecks[stageName];
        const stageLabel = swarmStageLabels[stageName] || stageName;
        const violations = check.violations || [];

        if (!check.passed) {
            html += `<div class="swarm-check-item violation">
                <div class="swarm-check-stage-name">❌ ${stageLabel}</div>`;
            violations.forEach(v => {
                html += `<div><strong>Нарушение:</strong> ${escapeHtml(v.invariant || '')}</div>
                <div class="swarm-check-reason">${escapeHtml(v.reason || '')}</div>`;
            });
            html += `</div>`;
        } else {
            html += `<div class="swarm-check-item no-violations">
                <div class="swarm-check-stage-name">✅ ${stageLabel}</div>
                Нарушений не обнаружено
            </div>`;
        }
    });

    listEl.innerHTML = html;
}

function toggleSwarmFullOutput() {
    const fullOutput = document.getElementById('swarmFullOutput');
    const btn = document.getElementById('swarmFullBtn');
    if (!fullOutput) return;
    if (fullOutput.style.display === 'none') {
        fullOutput.style.display = 'block';
        if (btn) btn.textContent = '📄 Скрыть вывод';
    } else {
        fullOutput.style.display = 'none';
        if (btn) btn.textContent = '📄 Весь вывод';
    }
}

// ---- Actions ----

async function swarmAction(action) {
    if (!swarmTaskId) return;
    if (isWaiting) { showToast('Подождите...', 'info'); return; }

    // Confirmation for destructive actions
    if (action === 'cancel') {
        if (!confirm('Отменить эту задачу роя? Действие необратимо.')) return;
    }

    isWaiting = true;
    disableSwarmControls();

    // Show loading state
    const descEl = document.getElementById('swarmStageDesc');
    const origDesc = descEl ? descEl.textContent : '';
    if (descEl) descEl.innerHTML = '<span class="swarm-loading"></span> Обработка...';

    try {
        const response = await fetch(`/api/swarm/tasks/${swarmTaskId}/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action })
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Ошибка действия (${response.status})`);
        }

        await refreshSwarmTask();
        await loadSwarmTasks();
        
        const actionLabels = {
            start_planning: 'Планирование запущено',
            approve_plan: 'План утверждён',
            reject_plan: 'План отклонён',
            start_execution: 'Выполнение запущено',
            approve_execution: 'Выполнение одобрено',
            reject_execution: 'Выполнение отклонено',
            start_validation: 'Валидация запущена',
            approve_validation: 'Валидация одобрена',
            reject_validation: 'Валидация отклонена',
            finish: 'Задача завершена',
            pause: 'Пауза',
            resume: 'Продолжено',
            retry: 'Этап перезапущен',
            restart_stage: 'Этап перезапущен (после инвариантов)',
            cancel: 'Задача отменена'
        };
        showToast(actionLabels[action] || action, action === 'cancel' ? 'error' : 'success');
    } catch (err) {
        if (descEl) descEl.textContent = origDesc;
        showToast(`Ошибка: ${err.message}`, 'error');
    } finally {
        isWaiting = false;
        enableSwarmControls();
    }
}

async function swarmConfirm() {
    if (!swarmTaskId || !swarmTaskData) return;
    
    const stage = swarmTaskData.current_stage;
    let approveAction, nextAction;
    if (stage === 'plan_review') {
        approveAction = 'approve_plan';
        nextAction = 'start_execution';
    } else if (stage === 'exec_review') {
        approveAction = 'approve_execution';
        nextAction = 'start_validation';
    } else if (stage === 'validation_review') {
        approveAction = 'approve_validation';
        nextAction = 'finish';
    } else {
        showToast('На этом этапе нечего подтверждать', 'info');
        return;
    }
    
    await swarmAction(approveAction);
    await swarmAction(nextAction);
}

async function cancelSwarmTask() {
    if (!swarmTaskId) return;
    await swarmAction('cancel');
}

async function deleteSwarmTask(taskId) {
    if (!confirm('Удалить задачу роя и все её файлы?')) return;
    
    try {
        const response = await fetch(`/api/swarm/tasks/${taskId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Ошибка удаления');
        
        if (swarmTaskId === taskId) closeSwarmView();
        await loadSwarmTasks();
        showToast('Задача удалена', 'success');
    } catch (err) {
        showToast(`Ошибка: ${err.message}`, 'error');
    }
}

function disableSwarmControls() {
    document.querySelectorAll('.swarm-btn').forEach(b => b.disabled = true);
}

function enableSwarmControls() {
    document.querySelectorAll('.swarm-btn').forEach(b => b.disabled = false);
}

// ---- Artifacts ----

async function viewSwarmArtifacts() {
    if (!swarmTaskId) return;
    
    const view = document.getElementById('swarmArtifactsView');
    const tree = document.getElementById('swarmArtifactsTree');
    const content = document.getElementById('swarmArtifactContent');
    
    if (!view || !tree) return;
    
    // Toggle
    if (view.style.display === 'flex') {
        view.style.display = 'none';
        return;
    }
    
    view.style.display = 'flex';
    tree.innerHTML = '<span class="swarm-loading"></span> Загрузка...';
    if (content) content.innerHTML = '<div class="panel-empty">Выберите файл для просмотра</div>';
    
    try {
        const response = await fetch(`/api/swarm/tasks/${swarmTaskId}/artifacts`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        
        let html = '';
        const stages = ['planning', 'execution', 'validation', 'done'];
        stages.forEach(stage => {
            if (data.artifacts[stage]) {
                html += `<div style="font-size:11px;color:var(--text-muted);width:100%;margin-top:6px;">${stage.toUpperCase()}</div>`;
                data.artifacts[stage].forEach(file => {
                    html += `<div class="swarm-artifact-file" onclick="viewSwarmArtifact('${stage}', '${escapeHtml(file.name)}')" title="${escapeHtml(file.name)} (${file.size} bytes)">📄 ${escapeHtml(file.name)}</div>`;
                });
            }
        });
        
        tree.innerHTML = html || '<div class="panel-empty">Артефактов пока нет</div>';
    } catch (err) {
        tree.innerHTML = `<div class="panel-empty">Ошибка: ${escapeHtml(err.message)}</div>`;
    }
}

function closeSwarmArtifacts() {
    const view = document.getElementById('swarmArtifactsView');
    if (view) view.style.display = 'none';
}

async function viewSwarmArtifact(stage, filename) {
    if (!swarmTaskId) return;
    
    const content = document.getElementById('swarmArtifactContent');
    if (!content) return;
    
    content.innerHTML = '<span class="swarm-loading"></span> Загрузка...';
    
    try {
        const response = await fetch(`/api/swarm/tasks/${swarmTaskId}/artifacts/${stage}/${encodeURIComponent(filename)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        
        content.innerHTML = `<div style="color:var(--text-muted);margin-bottom:8px;font-size:11px;">${escapeHtml(filename)}</div><pre style="white-space:pre-wrap;font-family:monospace;font-size:12px;">${escapeHtml(data.content)}</pre>`;
    } catch (err) {
        content.innerHTML = `<div class="panel-empty">Ошибка: ${escapeHtml(err.message)}</div>`;
    }
}

// ---- Init (call after DOMContentLoaded) ----
// loadSwarmTasks is called from the main init after loadUsers completes.
// Hook into the existing loadUsers flow.

const _origLoadUsers = loadUsers;
loadUsers = async function() {
    await _origLoadUsers();
    await loadSwarmTasks();
};

// ============================================================
// KEYBOARD SHORTCUTS
// ============================================================

document.addEventListener('keydown', function(e) {
    // Ctrl+Shift+E: toggle sidebar
    if (e.ctrlKey && e.shiftKey && e.key === 'E') {
        e.preventDefault();
        switchSidebarPanel('explorer');
    }
    // Ctrl+J: toggle bottom panel
    if (e.ctrlKey && e.key === 'j') {
        e.preventDefault();
        toggleBottomPanel();
    }
    // Ctrl+B: toggle sidebar
    if (e.ctrlKey && e.key === 'b') {
        e.preventDefault();
        toggleSidebar();
    }
});

// ============================================================
// CLOSE MODALS ON ESCAPE
// ============================================================

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal').forEach(m => {
            if (m.style.display === 'flex') m.style.display = 'none';
        });
    }
});
