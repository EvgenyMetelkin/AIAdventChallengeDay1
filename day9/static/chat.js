// ======================== Глобальные переменные ========================
let isWaiting = false;
let selectedFiles = [];
let typingElement = null;

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
    // Полная статистика
    document.getElementById('prompt-tokens').textContent = stats.last_prompt_tokens || 0;
    document.getElementById('completion-tokens').textContent = stats.last_completion_tokens || 0;
    document.getElementById('last-total').textContent = stats.last_total_tokens || 0;
    document.getElementById('session-tokens').textContent = stats.session_total_tokens || 0;
    // Мини-версия
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

// ======================== Статистика контекста (суммаризации) ========================
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
    
    if (summaryCountSpan) {
        const summaryText = `${stats.num_summaries} суммар. (посл. ${stats.recent_messages}/${stats.keep_last_n})`;
        summaryCountSpan.textContent = summaryText;
        
        // Меняем стиль в зависимости от наличия суммаризаций
        if (stats.num_summaries > 0) {
            summaryCountSpan.parentElement.style.background = 'rgba(255,215,0,0.3)';
            summaryCountSpan.parentElement.title = `Суммаризировано ${stats.num_summaries} блоков истории. Всего сообщений: ${stats.total_messages}. Интервал суммаризации: ${stats.summary_interval}`;
        } else {
            summaryCountSpan.parentElement.style.background = 'rgba(255,255,255,0.15)';
            summaryCountSpan.parentElement.title = 'Пока нет суммаризированных блоков. Старые сообщения будут автоматически суммаризироваться.';
        }
    }
    
    if (summaryIndicator) {
        // Обновляем тайтл с детальной информацией
        summaryIndicator.title = `📊 Статистика контекста:\n` +
            `• Всего сообщений: ${stats.total_messages}\n` +
            `• Суммаризаций: ${stats.num_summaries}\n` +
            `• Храним последних: ${stats.keep_last_n}\n` +
            `• Интервал суммаризации: ${stats.summary_interval}\n` +
            `• Актуальных сообщений: ${stats.recent_messages}\n` +
            `• Суммаризировано сообщений: ${stats.summarized_messages}`;
    }
}

// ======================== Сворачиваемый блок статистики ========================
function initCollapsibleStats() {
    const container = document.getElementById('statsCollapsible');
    const toggleBtn = document.getElementById('statsToggle');
    if (!container || !toggleBtn) return;
    
    // Восстановление состояния из localStorage
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

// ======================== Отображение сообщений ========================
function appendMessageToDOM(role, content, scroll = true, attachments = null, tokens = null, isSummarized = false) {
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
    
    let summarizedBadge = '';
    if (isSummarized) {
        summarizedBadge = `<span class="summarized-badge" title="Это сообщение было суммаризировано и заменено кратким изложением">📋 Суммаризировано</span>`;
    }
    
    const safeContent = escapeHtml(content);
    messageDiv.innerHTML = `
        <div class="message-bubble">${safeContent || ''}</div>
        ${attachmentsHtml}
        ${tokenInfoHtml}
        <div class="message-meta">
            ${role === 'user' ? '👤 Вы' : '🤖 Ассистент'} · ${new Date().toLocaleTimeString()}
            ${summarizedBadge}
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

// Отображение баннера с информацией о суммаризации
function showSummarizationBanner(numSummaries, totalMessagesSummarized) {
    const container = document.getElementById('chatMessages');
    const banner = document.createElement('div');
    banner.className = 'message system-summary';
    banner.style.margin = '8px 0';
    banner.style.textAlign = 'center';
    banner.innerHTML = `
        <div style="background: #e8f4f8; border-radius: 16px; padding: 8px 16px; font-size: 0.8rem; color: #2c3e66; display: inline-block; max-width: 90%;">
            📋 <strong>Управление контекстом</strong>: ${numSummaries} блок(ов) истории суммаризировано (${totalMessagesSummarized} сообщений). 
            Последние сообщения сохранены полностью.
        </div>
    `;
    container.appendChild(banner);
    scrollToBottom();
    
    // Автоматически скрываем через 5 секунд
    setTimeout(() => {
        if (banner.parentNode) banner.remove();
    }, 5000);
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

// ======================== Загрузка истории и информации об агенте ========================
async function loadHistory() {
    try {
        const response = await fetch('/history');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderMessages(data.history);
        
        // Проверяем наличие суммаризаций
        if (data.summaries && data.summaries.length > 0) {
            // Показываем баннер при загрузке, если есть суммаризации
            const totalMessages = data.history?.length || 0;
            // Примерное количество суммаризированных сообщений (может быть неточно, но для индикации)
            const approxSummarized = data.summaries.length * 10; // приблизительно
            showSummarizationBanner(data.summaries.length, approxSummarized);
        }
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
                let contextInfo = '';
                if (info.context_stats) {
                    contextInfo = ` | контекст: ${info.context_stats.keep_last_n} посл., ${info.context_stats.num_summaries} суммар.`;
                }
                agentIdSpan.textContent = `ID: ${info.agent_id} ${visionSupport}${contextInfo}`;
            }
            if (info.token_stats) {
                updateTokenStats(info.token_stats);
            }
        }
    } catch(e) { console.warn(e); }
    
    await loadTokenStats();
    await loadContextStats();
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
        
        // Обновляем статистику контекста после отправки
        await loadContextStats();
        
        // Проверяем, не произошла ли суммаризация
        const contextStats = await fetch('/context-stats').then(r => r.json()).catch(() => null);
        if (contextStats && contextStats.num_summaries > 0) {
            // Показываем уведомление о суммаризации, но не спамим
            const lastSummaryTime = localStorage.getItem('lastSummaryNotification');
            const now = Date.now();
            if (!lastSummaryTime || now - parseInt(lastSummaryTime) > 30000) { // не чаще раза в 30 секунд
                localStorage.setItem('lastSummaryNotification', now);
                if (contextStats.num_summaries > 0) {
                    showError(`📋 Управление контекстом: ${contextStats.num_summaries} блок(ов) истории суммаризировано`, 'info');
                }
            }
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
    if (!confirm('Вы уверены, что хотите очистить всю историю диалога? Статистика токенов будет обнулена, все суммаризации будут удалены.')) return;
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
        
        // Обновляем индикатор суммаризаций
        const summaryCountSpan = document.getElementById('summaryCount');
        if (summaryCountSpan) {
            summaryCountSpan.textContent = '0 суммар. (посл. 0/0)';
            summaryCountSpan.parentElement.style.background = 'rgba(255,255,255,0.15)';
        }
        
        showError('История успешно очищена и статистика обнулена', 'success');
    } catch (err) {
        showError(`Ошибка очистки: ${err.message}`);
    }
}

// ======================== Периодическое обновление статистики ========================
let refreshInterval = null;

function startPeriodicRefresh() {
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => {
        if (document.hasFocus()) {
            loadContextStats();
            loadTokenStats();
        }
    }, 15000); // Обновляем каждые 15 секунд
}

function stopPeriodicRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
}

// ======================== Инициализация ========================
function init() {
    // Элементы DOM
    const sendBtn = document.getElementById('sendBtn');
    const resetBtn = document.getElementById('resetBtn');
    const fileBtn = document.getElementById('fileBtn');
    const fileInput = document.getElementById('fileInput');
    const messageInput = document.getElementById('messageInput');
    
    // Обработчики
    sendBtn.addEventListener('click', sendMessage);
    resetBtn.addEventListener('click', resetChat);
    fileBtn.addEventListener('click', () => fileInput.click());
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
    
    // Авто-расширение textarea
    messageInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 150) + 'px';
    });
    
    // Отправка по Enter (без Shift)
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // Инициализация сворачиваемой статистики
    initCollapsibleStats();
    
    // Загрузка данных
    loadHistory();
    
    // Запуск периодического обновления
    startPeriodicRefresh();
}

// Очистка интервала при выгрузке страницы
window.addEventListener('beforeunload', () => {
    stopPeriodicRefresh();
});

// Запуск при загрузке страницы
document.addEventListener('DOMContentLoaded', init);