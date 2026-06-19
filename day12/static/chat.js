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
        userEl.textContent = user ? `👤 ${user.name}` : '👤 unknown';
    }
    
    if (agentEl && currentAgentId && agents[currentAgentId]) {
        agentEl.textContent = `🤖 ${agents[currentAgentId].name}`;
    } else if (agentEl && currentAgentId) {
        agentEl.textContent = `🤖 ${currentAgentId}`;
    }
    
    if (msgEl && openTabs[activeTabIdx]) {
        const count = openTabs[activeTabIdx].history.length;
        msgEl.textContent = `💬 ${count} messages`;
    } else if (msgEl) {
        msgEl.textContent = '💬 0 messages';
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
            info.textContent = 'Failed to load settings';
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
        showToast('Failed to load users', 'error');
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
        showToast('Failed to load agents', 'error');
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
        showToast('Failed to load history', 'error');
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
    html += '<span class="arrow">▾</span> USERS';
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
    html += '<span class="arrow">▾</span> AGENTS';
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
    html += '<span class="arrow">▾</span> MEMORY';
    html += '</div>';
    html += '<div class="tree-section-items" id="explorerMemoryItems">';
    html += '<div class="sidebar-empty" style="padding:8px;font-size:11px;">Click to load</div>';
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
            container.innerHTML = '<div class="sidebar-empty" style="padding:8px;font-size:11px;">Empty</div>';
            return;
        }
        
        container.innerHTML = data.working_memory.map((sum, i) => `
            <div class="tree-item" title="${escapeHtml(sum)}" 
                 onclick="showToast('${escapeHtml(sum.slice(0, 200))}', 'info')">
                <span class="item-icon">📝</span>
                <span class="item-label">Summary #${i + 1}</span>
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
        showToast('Wait for current request to finish', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/users/${userId}/switch`, { method: 'POST' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Switch failed');
        
        const data = await response.json();
        currentUserId = data.user.user_id;
        
        await loadAgents();
        await loadHistory();
        renderExplorer();
        updateStatusBar();
        showToast(`Switched to ${data.user.name}`, 'success');
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function deleteUserById(userId) {
    if (isWaiting) {
        showToast('Wait for current request to finish', 'error');
        return;
    }
    
    const user = usersList.find(u => u.user_id === userId);
    const userName = user ? user.name : userId;
    
    if (!confirm(`Delete user "${userName}"?`)) return;
    
    try {
        const response = await fetch(`/api/users/${userId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Delete failed');
        
        await loadUsers();
        showToast(`User "${userName}" deleted`, 'success');
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function createUser() {
    const nameInput = document.getElementById('userNameInput');
    const name = nameInput ? nameInput.value.trim() : '';
    
    if (!name) { showToast('Enter a user name', 'error'); return; }
    
    const fileInput = document.getElementById('preferencesFileInput');
    const formData = new FormData();
    formData.append('name', name);
    if (fileInput && fileInput.files.length > 0) {
        formData.append('preferences', fileInput.files[0]);
    }
    
    try {
        const response = await fetch('/api/users', { method: 'POST', body: formData });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Create failed');
        
        const data = await response.json();
        closeCreateUserModal();
        await loadUsers();
        showToast(`User "${data.user.name}" created`, 'success');
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
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
        showToast('Wait for current request to finish', 'error');
        return;
    }
    
    const agentName = agents[agentId]?.name || agentId;
    
    if (!confirm(`Switch to agent "${agentName}"? Current history will be summarized into working memory.`)) return;
    
    try {
        const response = await fetch(`/api/agents/${agentId}/switch`, { method: 'POST' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Switch failed');
        
        const data = await response.json();
        currentAgentId = data.current_agent_id;
        
        if (data.summary_generated) {
            showToast('Summary added to working memory', 'success');
        }
        
        await loadAgents();
        await loadHistory();
        renderExplorer();
        updateWorkingMemoryDisplay();
        updateStatusBar();
        
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function deleteAgentById(agentId) {
    if (isWaiting) {
        showToast('Wait for current request to finish', 'error');
        return;
    }
    
    const agentName = agents[agentId]?.name || agentId;
    if (!confirm(`Delete agent "${agentName}"?`)) return;
    
    try {
        const response = await fetch(`/api/agents/${agentId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Delete failed');
        
        // Close tab if open
        closeTab(agentId);
        await loadAgents();
        await loadHistory();
        renderExplorer();
        updateStatusBar();
        showToast(`Agent "${agentName}" deleted`, 'success');
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function createAgent() {
    const nameInput = document.getElementById('agentNameInput');
    const name = nameInput ? nameInput.value.trim() : '';
    
    if (!name) { showToast('Enter an agent name', 'error'); return; }
    
    try {
        const response = await fetch('/api/agents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        if (!response.ok) throw new Error((await response.json().catch(()=>({}))).detail || 'Create failed');
        
        const data = await response.json();
        closeCreateAgentModal();
        await loadAgents();
        await loadHistory();
        renderExplorer();
        showToast(`Agent "${data.name}" created`, 'success');
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
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
        showToast('Please wait for the current response', 'info');
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
    if (streamContent) streamContent.textContent = '...';
    scrollToBottom();
    
    try {
        await sendMessageStream(message);
        await loadAgents();
        updateWorkingMemoryDisplay();
        updateStatusBar();
        renderExplorer();
    } catch (err) {
        if (streamContent) {
            streamContent.innerHTML = `<span style="color:var(--red);">Error: ${escapeHtml(err.message)}</span>`;
        }
        showToast(`Error: ${err.message}`, 'error');
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
        throw new Error(errData.detail || `Server error: ${response.status}`);
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
        throw new Error(errData.detail || `Server error: ${response.status}`);
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
        showToast('Wait for current request to finish', 'info');
        return;
    }
    if (!confirm('Clear current agent history?')) return;
    
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
        showToast('History cleared', 'success');
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
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
        container.innerHTML = '<div class="panel-empty">Working memory is empty</div>';
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
    if (!confirm('Clear all working memory?')) return;
    
    try {
        const response = await fetch('/api/working_memory', { method: 'DELETE' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await response.json();
        
        updateWorkingMemoryDisplay();
        showToast('Working memory cleared', 'success');
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
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
