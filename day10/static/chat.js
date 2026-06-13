// ======================== Глобальные переменные ========================
let isWaiting = false;
let selectedFiles = [];
let typingElement = null;
let currentStrategy = "summary";

// ======================== Вспомогательные функции ========================
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    if (typeof str !== 'string') str = String(str);
    return str.replace(/[&<>]/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
}

function formatFileSize(bytes) {
    if (!bytes || bytes < 0) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
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

// ======================== Статистика токенов ========================
function updateTokenStats(stats) {
    if (!stats) return;
    document.getElementById('prompt-tokens').textContent = stats.last_prompt_tokens || 0;
    document.getElementById('completion-tokens').textContent = stats.last_completion_tokens || 0;
    document.getElementById('last-total').textContent = stats.last_total_tokens || 0;
    document.getElementById('session-tokens').textContent = stats.session_total_tokens || 0;
    const miniSpan = document.getElementById('session-tokens-mini');
    if (miniSpan) miniSpan.textContent = stats.session_total_tokens || 0;
}

async function loadTokenStats() {
    try {
        const response = await fetch('/stats');
        if (response.ok) {
            const stats = await response.json();
            updateTokenStats(stats);
        }
    } catch (err) {
        console.warn('Could not load token stats:', err);
    }
}

// ======================== Статистика контекста ========================
async function loadContextStats() {
    try {
        const response = await fetch('/context-stats');
        if (response.ok) {
            const stats = await response.json();
            updateContextStats(stats);
        }
    } catch (err) {
        console.warn('Could not load context stats:', err);
    }
}

function updateContextStats(stats) {
    if (!stats) return;
    
    const summaryIndicator = document.getElementById('summaryIndicator');
    const summaryCountSpan = document.getElementById('summaryCount');
    const strategyInfoSpan = document.getElementById('strategyInfo');
    
    if (summaryCountSpan) {
        if (stats.strategy === 'summary') {
            summaryCountSpan.textContent = `${stats.num_summaries} суммар. (посл. ${stats.recent_messages}/${stats.keep_last_n})`;
            summaryCountSpan.parentElement.style.background = stats.num_summaries > 0 ? 'rgba(255,215,0,0.3)' : 'rgba(255,255,255,0.15)';
        } else if (stats.strategy === 'sliding_window') {
            summaryCountSpan.textContent = `Окно: ${stats.current_window_size}/${stats.max_window_size}`;
            summaryCountSpan.parentElement.style.background = 'rgba(100,200,255,0.3)';
        } else if (stats.strategy === 'sticky_facts') {
            summaryCountSpan.textContent = `Фактов: ${stats.num_facts}`;
            summaryCountSpan.parentElement.style.background = 'rgba(100,255,100,0.3)';
        } else if (stats.strategy === 'branching') {
            summaryCountSpan.textContent = `Ветка: ${stats.current_branch} (${stats.total_branches} всего)`;
            summaryCountSpan.parentElement.style.background = 'rgba(255,200,100,0.3)';
        }
    }
    
    if (strategyInfoSpan) {
        let infoText = `Стратегия: ${stats.strategy}`;
        if (stats.strategy === 'sticky_facts' && stats.facts && Object.keys(stats.facts).length > 0) {
            infoText += ` | Факты: ${JSON.stringify(stats.facts).substring(0, 100)}`;
        }
        strategyInfoSpan.textContent = infoText;
    }
    
    // Обновляем UI для веток, если стратегия branching
    if (stats.strategy === 'branching') {
        updateBranchUI(stats.branches, stats.current_branch);
    }
}

// ======================== Управление стратегией ========================
async function loadCurrentStrategy() {
    try {
        const response = await fetch('/context-strategy');
        if (response.ok) {
            const data = await response.json();
            currentStrategy = data.current_strategy;
            const strategySelect = document.getElementById('strategySelect');
            if (strategySelect) {
                strategySelect.value = currentStrategy;
            }
            updateUIForStrategy(currentStrategy);
        }
    } catch (err) {
        console.warn('Could not load current strategy:', err);
    }
}

async function changeStrategy(strategy) {
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        return false;
    }
    
    try {
        const response = await fetch('/context-strategy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategy: strategy })
        });
        
        if (response.ok) {
            currentStrategy = strategy;
            showError(`Стратегия изменена на: ${strategy}`, 'success');
            updateUIForStrategy(strategy);
            await loadContextStats();
            await loadHistory();
            return true;
        } else {
            const error = await response.json();
            showError(`Ошибка: ${error.detail}`);
            return false;
        }
    } catch (err) {
        showError(`Ошибка: ${err.message}`);
        return false;
    }
}

function updateUIForStrategy(strategy) {
    const branchControls = document.getElementById('branchControls');
    const factsInfo = document.getElementById('factsInfo');
    
    if (branchControls) {
        branchControls.style.display = strategy === 'branching' ? 'flex' : 'none';
    }
    
    if (factsInfo) {
        factsInfo.style.display = strategy === 'sticky_facts' ? 'block' : 'none';
    }
}

// ======================== Управление ветками ========================
async function saveBranch() {
    const branchName = document.getElementById('newBranchName').value.trim();
    if (!branchName) {
        showError('Введите имя ветки');
        return;
    }
    
    try {
        const response = await fetch('/branch/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: branchName })
        });
        
        if (response.ok) {
            showError(`Ветка "${branchName}" сохранена`, 'success');
            document.getElementById('newBranchName').value = '';
            await loadBranches();
        } else {
            const error = await response.json();
            showError(`Ошибка: ${error.detail}`);
        }
    } catch (err) {
        showError(`Ошибка: ${err.message}`);
    }
}

async function switchBranch(branchName) {
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        return;
    }
    
    try {
        const response = await fetch('/branch/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: branchName })
        });
        
        if (response.ok) {
            showError(`Переключено на ветку "${branchName}"`, 'success');
            await loadHistory();
            await loadContextStats();
            await loadTokenStats();
        } else {
            const error = await response.json();
            showError(`Ошибка: ${error.detail}`);
        }
    } catch (err) {
        showError(`Ошибка: ${err.message}`);
    }
}

async function deleteBranch(branchName) {
    if (branchName === currentBranch) {
        showError('Нельзя удалить текущую ветку');
        return;
    }
    
    if (!confirm(`Удалить ветку "${branchName}"?`)) return;
    
    try {
        const response = await fetch(`/branch/${encodeURIComponent(branchName)}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showError(`Ветка "${branchName}" удалена`, 'success');
            await loadBranches();
        } else {
            const error = await response.json();
            showError(`Ошибка: ${error.detail}`);
        }
    } catch (err) {
        showError(`Ошибка: ${err.message}`);
    }
}

async function loadBranches() {
    try {
        const response = await fetch('/branch/list');
        if (response.ok) {
            const data = await response.json();
            currentBranch = data.current_branch;
            updateBranchSelect(data.branches, data.current_branch);
        }
    } catch (err) {
        console.warn('Could not load branches:', err);
    }
}

function updateBranchSelect(branches, currentBranchName) {
    const select = document.getElementById('branchSelect');
    if (!select) return;
    
    select.innerHTML = '<option value="">Выбрать ветку...</option>';
    for (const branch of branches) {
        const option = document.createElement('option');
        option.value = branch;
        option.textContent = branch + (branch === currentBranchName ? ' (текущая)' : '');
        if (branch === currentBranchName) option.selected = true;
        select.appendChild(option);
    }
}

function updateBranchUI(branches, currentBranchName) {
    const branchList = document.getElementById('branchList');
    if (!branchList) return;
    
    branchList.innerHTML = '';
    for (const branch of branches) {
        const item = document.createElement('div');
        item.style.padding = '4px';
        item.style.margin = '2px 0';
        item.style.display = 'flex';
        item.style.justifyContent = 'space-between';
        item.style.alignItems = 'center';
        
        const nameSpan = document.createElement('span');
        nameSpan.textContent = branch + (branch === currentBranchName ? ' ✓' : '');
        nameSpan.style.fontWeight = branch === currentBranchName ? 'bold' : 'normal';
        
        const deleteBtn = document.createElement('button');
        deleteBtn.textContent = '✖';
        deleteBtn.style.background = '#dc3545';
        deleteBtn.style.padding = '2px 8px';
        deleteBtn.style.fontSize = '12px';
        deleteBtn.onclick = () => deleteBranch(branch);
        
        if (branch !== currentBranchName) {
            const switchBtn = document.createElement('button');
            switchBtn.textContent = 'Переключить';
            switchBtn.style.background = '#2c3e66';
            switchBtn.style.padding = '2px 8px';
            switchBtn.style.fontSize = '12px';
            switchBtn.style.marginRight = '5px';
            switchBtn.onclick = () => switchBranch(branch);
            item.appendChild(switchBtn);
        }
        
        item.appendChild(nameSpan);
        item.appendChild(deleteBtn);
        branchList.appendChild(item);
    }
}

// ======================== Отображение сообщений ========================
function appendMessageToDOM(role, content, scroll = true, attachments = null, tokens = null) {
    const container = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    let attachmentsHtml = '';
    if (attachments && attachments.length > 0) {
        attachmentsHtml = '<div class="attachments">';
        for (const att of attachments) {
            if (att.is_image && att.preview_url) {
                attachmentsHtml += `<div class="attachment">
                    <img src="${escapeHtml(att.preview_url)}" alt="${escapeHtml(att.filename)}" onclick="window.open('${escapeHtml(att.url)}', '_blank')">
                    <div class="file-info">
                        <div class="filename">${escapeHtml(att.filename)}</div>
                        <div class="file-size">${formatFileSize(att.size_bytes)}</div>
                    </div>
                </div>`;
            } else if (att.url) {
                attachmentsHtml += `<div class="attachment">
                    <div class="file-icon">📄</div>
                    <div class="file-info">
                        <div class="filename"><a href="${escapeHtml(att.url)}" target="_blank">${escapeHtml(att.filename)}</a></div>
                        <div class="file-size">${formatFileSize(att.size_bytes)}</div>
                    </div>
                </div>`;
            }
        }
        attachmentsHtml += '</div>';
    }
    
    let tokenInfoHtml = '';
    if (role === 'assistant' && tokens && tokens.total_tokens) {
        tokenInfoHtml = `<div class="token-info">📊 Токены: prompt: ${tokens.prompt_tokens || 0} | completion: ${tokens.completion_tokens || 0} | total: ${tokens.total_tokens || 0}</div>`;
    }
    
    const safeContent = escapeHtml(content);
    messageDiv.innerHTML = `
        <div class="message-bubble">${safeContent || ''}</div>
        ${attachmentsHtml}
        ${tokenInfoHtml}
        <div class="message-meta">
            ${role === 'user' ? '👤 Вы' : '🤖 Ассистент'} · ${new Date().toLocaleTimeString()}
        </div>
    `;
    container.appendChild(messageDiv);
    if (scroll) scrollToBottom();
}

function renderMessages(history) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    container.innerHTML = '';
    
    if (!history || history.length === 0) {
        container.innerHTML = `<div class="message assistant"><div class="message-bubble">История пуста. Напишите что-нибудь или прикрепите файл!</div><div class="message-meta">🤖 Ассистент · ${new Date().toLocaleTimeString()}</div></div>`;
        return;
    }
    
    for (const msg of history) {
        if (msg.role === 'user') {
            appendMessageToDOM('user', msg.content || '', false, msg.attachments);
        } else if (msg.role === 'assistant') {
            appendMessageToDOM('assistant', msg.content || '', false, null, msg.tokens);
        }
    }
    scrollToBottom();
}

// ======================== Работа с файлами ========================
function updateFilePreview() {
    const previewArea = document.getElementById('filePreviewArea');
    if (selectedFiles.length === 0) {
        previewArea.style.display = 'none';
        previewArea.innerHTML = '';
        return;
    }
    
    previewArea.style.display = 'flex';
    previewArea.innerHTML = '';
    
    for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        const previewItem = document.createElement('div');
        previewItem.className = 'file-preview-item';
        
        if (file.type.startsWith('image/')) {
            const reader = new FileReader();
            reader.onload = function(e) {
                const img = document.createElement('img');
                img.src = e.target.result;
                previewItem.insertBefore(img, previewItem.firstChild);
            };
            reader.readAsDataURL(file);
        } else {
            const icon = document.createElement('div');
            icon.textContent = '📄';
            icon.style.fontSize = '32px';
            previewItem.appendChild(icon);
        }
        
        const info = document.createElement('div');
        info.innerHTML = `<div class="filename">${escapeHtml(file.name)}</div>
                         <div class="file-size">${formatFileSize(file.size)}</div>`;
        previewItem.appendChild(info);
        
        const removeBtn = document.createElement('div');
        removeBtn.className = 'remove-file';
        removeBtn.textContent = '×';
        removeBtn.onclick = () => removeFile(i);
        previewItem.appendChild(removeBtn);
        
        previewArea.appendChild(previewItem);
    }
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    const fileInput = document.getElementById('fileInput');
    fileInput.value = '';
    updateFilePreview();
}

// ======================== Индикатор печати ========================
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

// ======================== Загрузка истории ========================
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
    
    try {
        const infoRes = await fetch('/info');
        if (infoRes.ok) {
            const info = await infoRes.json();
            const agentIdSpan = document.getElementById('agentIdLabel');
            if (agentIdSpan) {
                const visionSupport = info.supports_vision ? '🔮' : '📝';
                agentIdSpan.textContent = `ID: ${info.agent_id} ${visionSupport}`;
            }
            if (info.token_stats) {
                updateTokenStats(info.token_stats);
            }
        }
    } catch(e) { console.warn(e); }
    
    await loadTokenStats();
    await loadContextStats();
    await loadCurrentStrategy();
    await loadBranches();
}

// ======================== Отправка сообщения ========================
async function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    
    if (!message && selectedFiles.length === 0) {
        showError('Введите сообщение или прикрепите файл');
        return;
    }
    
    if (isWaiting) {
        showError('Подождите, ответ уже загружается');
        return;
    }

    isWaiting = true;
    const sendBtn = document.getElementById('sendBtn');
    const resetBtn = document.getElementById('resetBtn');
    const fileBtn = document.getElementById('fileBtn');
    sendBtn.disabled = true;
    resetBtn.disabled = true;
    fileBtn.disabled = true;
    input.disabled = true;

    if (message) {
        appendMessageToDOM('user', message, true);
    }
    input.value = '';
    input.style.height = 'auto';
    
    showTypingIndicator();

    try {
        const formData = new FormData();
        if (message) {
            formData.append('message', message);
        }
        for (const file of selectedFiles) {
            formData.append('files', file);
        }
        
        const response = await fetch('/send', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Server error: ${response.status}`);
        }
        
        const data = await response.json();
        hideTypingIndicator();
        
        if (data.token_stats) {
            updateTokenStats(data.token_stats);
        }
        
        selectedFiles = [];
        updateFilePreview();
        document.getElementById('fileInput').value = '';
        
        renderMessages(data.history);
        
        if (data.context_stats) {
            updateContextStats(data.context_stats);
        }
        
    } catch (err) {
        hideTypingIndicator();
        showError(`Ошибка: ${err.message}`);
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
        fileBtn.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

// ======================== Очистка чата ========================
async function resetChat() {
    if (isWaiting) {
        showError('Дождитесь завершения текущего запроса');
        return;
    }
    if (!confirm('Вы уверены, что хотите очистить всю историю диалога?')) return;
    try {
        const response = await fetch('/reset', { method: 'POST' });
        if (!response.ok) throw new Error(`Reset failed: ${response.status}`);
        const container = document.getElementById('chatMessages');
        container.innerHTML = `<div class="message assistant"><div class="message-bubble">История очищена. Начните новый диалог.</div><div class="message-meta">🤖 Ассистент · ${new Date().toLocaleTimeString()}</div></div>`;
        selectedFiles = [];
        updateFilePreview();
        document.getElementById('fileInput').value = '';
        
        updateTokenStats({
            session_total_tokens: 0,
            last_prompt_tokens: 0,
            last_completion_tokens: 0,
            last_total_tokens: 0
        });
        
        await loadContextStats();
        await loadBranches();
        
        showError('История успешно очищена', 'success');
    } catch (err) {
        showError(`Ошибка очистки: ${err.message}`);
    }
}

// ======================== Периодическое обновление ========================
let refreshInterval = null;

function startPeriodicRefresh() {
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => {
        if (document.hasFocus()) {
            loadContextStats();
            loadTokenStats();
            if (currentStrategy === 'branching') {
                loadBranches();
            }
        }
    }, 15000);
}

function stopPeriodicRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
}

// ======================== Сворачиваемая статистика ========================
function initCollapsibleStats() {
    const container = document.getElementById('statsCollapsible');
    const toggleBtn = document.getElementById('statsToggle');
    if (!container || !toggleBtn) return;
    
    const isCollapsed = localStorage.getItem('statsCollapsed') === 'true';
    if (isCollapsed) {
        container.classList.add('collapsed');
        toggleBtn.textContent = '📈';
    } else {
        container.classList.remove('collapsed');
        toggleBtn.textContent = '📊';
    }
    
    toggleBtn.addEventListener('click', () => {
        const nowCollapsed = container.classList.toggle('collapsed');
        localStorage.setItem('statsCollapsed', nowCollapsed);
        toggleBtn.textContent = nowCollapsed ? '📈' : '📊';
    });
}

// ======================== Инициализация ========================
function init() {
    // Элементы DOM
    const sendBtn = document.getElementById('sendBtn');
    const resetBtn = document.getElementById('resetBtn');
    const fileBtn = document.getElementById('fileBtn');
    const fileInput = document.getElementById('fileInput');
    const messageInput = document.getElementById('messageInput');
    const strategySelect = document.getElementById('strategySelect');
    const saveBranchBtn = document.getElementById('saveBranchBtn');
    const branchSelect = document.getElementById('branchSelect');
    
    if (sendBtn) sendBtn.addEventListener('click', sendMessage);
    if (resetBtn) resetBtn.addEventListener('click', resetChat);
    if (fileBtn) fileBtn.addEventListener('click', () => fileInput.click());
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            const maxSizeMB = 10;
            for (const file of files) {
                if (file.size > maxSizeMB * 1024 * 1024) {
                    showError(`Файл ${file.name} превышает ${maxSizeMB}MB`);
                    continue;
                }
                selectedFiles.push(file);
            }
            updateFilePreview();
        });
    }
    
    if (messageInput) {
        messageInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 150) + 'px';
        });
        
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }
    
    if (strategySelect) {
        strategySelect.addEventListener('change', (e) => {
            changeStrategy(e.target.value);
        });
    }
    
    if (saveBranchBtn) {
        saveBranchBtn.addEventListener('click', saveBranch);
    }
    
    if (branchSelect) {
        branchSelect.addEventListener('change', (e) => {
            if (e.target.value) {
                switchBranch(e.target.value);
                branchSelect.value = '';
            }
        });
    }
    
    initCollapsibleStats();
    loadHistory();
    startPeriodicRefresh();
}

window.addEventListener('beforeunload', () => {
    stopPeriodicRefresh();
});

document.addEventListener('DOMContentLoaded', init);