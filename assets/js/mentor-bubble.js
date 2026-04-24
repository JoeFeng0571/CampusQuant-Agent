/* ════════════════════════════════════════════════════════
   mentor-bubble.js — 财商学长浮动聊天气泡
   在内容/学习页右下角展示一个 FAB，点击展开 mini chat。
   - 后端复用 /api/v1/chat/mentor（登录用户自动走 DB，匿名走 stateless）
   - localStorage key 与 dashboard.html 共用，跨页面对话连续
   - 需要 common.js 提供 window.CQ_API（可选，有 fallback）
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    if (document.getElementById('mentor-bubble-root')) return; // 防重复注入

    const API = window.CQ_API || (
        (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
            ? 'http://127.0.0.1:8000'
            : window.location.origin
    );
    const CHAT_SK = 'cq_chat_history_v2';
    const MENTOR_INTRO = () => ({
        role: 'bot',
        text: '你好！我是财商学长 AI\n\n读到哪里不懂都可以问我，比如"PE 是什么"、"这段资产负债表怎么看"。学长只讲概念和逻辑，不给买卖建议。',
        time: fmtTime(new Date()),
    });

    let _chatHistory   = [];
    let _isOpen        = false;
    let _historyLoaded = false;

    function fmtTime(d) {
        return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    }
    function escHtml(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    // ── 样式 ────────────────────────────────────────────────
    function injectStyles() {
        if (document.getElementById('mentor-bubble-style')) return;
        const s = document.createElement('style');
        s.id = 'mentor-bubble-style';
        s.textContent = `
            .mb-fab {
                position: fixed; bottom: 24px; right: 24px;
                width: 56px; height: 56px; border-radius: 50%;
                background: linear-gradient(135deg, #2dd4bf, #22d3ee);
                border: none; cursor: pointer; color: #fff;
                box-shadow: 0 8px 24px rgba(45,212,191,.35), 0 2px 8px rgba(0,0,0,.25);
                z-index: 1200;
                display: flex; align-items: center; justify-content: center;
                transition: transform .18s ease, box-shadow .18s ease;
            }
            .mb-fab:hover { transform: scale(1.08); box-shadow: 0 12px 32px rgba(45,212,191,.5); }
            .mb-fab svg.close-icon { display: none; }
            .mb-fab.open svg.open-icon  { display: none; }
            .mb-fab.open svg.close-icon { display: block; }

            .mb-fab-badge {
                position: absolute; top: -4px; right: -4px;
                padding: 2px 6px; border-radius: 8px;
                background: #0b1624; color: #5eead4;
                font-size: 10px; font-weight: 800; letter-spacing: .04em;
                border: 1px solid rgba(94,234,212,.4);
                white-space: nowrap; pointer-events: none;
            }
            .mb-fab.open .mb-fab-badge { display: none; }

            .mb-panel {
                position: fixed; bottom: 96px; right: 24px;
                width: 380px; height: 540px;
                max-height: calc(100vh - 120px);
                background: rgba(8,17,31,0.97);
                backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
                border: 1px solid rgba(255,255,255,.1);
                border-radius: 20px;
                display: flex; flex-direction: column;
                box-shadow: 0 24px 60px rgba(0,0,0,.45);
                z-index: 1199;
                opacity: 0; transform: translateY(12px) scale(.98); pointer-events: none;
                transition: opacity .22s, transform .22s;
                overflow: hidden;
            }
            .mb-panel.open { opacity: 1; transform: translateY(0) scale(1); pointer-events: auto; }

            .mb-header {
                padding: 14px 18px;
                display: flex; align-items: center; justify-content: space-between;
                border-bottom: 1px solid rgba(255,255,255,.07);
                flex-shrink: 0;
            }
            .mb-header-title {
                display: flex; align-items: center; gap: 10px;
                color: #fff; font-size: 14px; font-weight: 700;
            }
            .mb-avatar {
                width: 32px; height: 32px; border-radius: 50%;
                background: linear-gradient(135deg, #2dd4bf, #22d3ee);
                display: flex; align-items: center; justify-content: center;
                font-size: 11px; font-weight: 800; color: #06242a;
            }
            .mb-header-sub { font-size: 11px; color: rgba(255,255,255,.45); font-weight: 400; margin-top: 2px; }
            .mb-header-actions { display: flex; gap: 6px; }
            .mb-icon-btn {
                width: 28px; height: 28px; border: none; background: transparent;
                color: rgba(255,255,255,.55); cursor: pointer; border-radius: 6px;
                display: flex; align-items: center; justify-content: center;
                transition: background .15s, color .15s;
            }
            .mb-icon-btn:hover { background: rgba(255,255,255,.06); color: #fff; }

            .mb-messages {
                flex: 1; overflow-y: auto;
                padding: 16px; display: flex; flex-direction: column; gap: 12px;
            }
            .mb-messages::-webkit-scrollbar { width: 4px; }
            .mb-messages::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 2px; }

            .mb-msg { display: flex; gap: 8px; max-width: 100%; }
            .mb-msg.user { flex-direction: row-reverse; }
            .mb-msg-avatar {
                width: 26px; height: 26px; flex-shrink: 0; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                font-size: 10px; font-weight: 800;
            }
            .mb-msg.bot  .mb-msg-avatar { background: linear-gradient(135deg, #2dd4bf, #22d3ee); color: #06242a; }
            .mb-msg.user .mb-msg-avatar { background: rgba(255,255,255,.1); color: rgba(255,255,255,.8); }

            .mb-bubble {
                padding: 9px 13px; border-radius: 12px;
                font-size: 13.5px; line-height: 1.55; color: rgba(255,255,255,.92);
                word-wrap: break-word; word-break: break-word; max-width: 85%;
            }
            .mb-msg.bot  .mb-bubble { background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.08); }
            .mb-msg.user .mb-bubble { background: rgba(45,212,191,.15); border: 1px solid rgba(45,212,191,.25); }

            .mb-input-row {
                padding: 12px; border-top: 1px solid rgba(255,255,255,.07);
                display: flex; gap: 8px; flex-shrink: 0;
            }
            .mb-input {
                flex: 1; padding: 10px 12px; border-radius: 10px;
                background: rgba(255,255,255,.05);
                border: 1px solid rgba(255,255,255,.1);
                color: #fff; font-size: 13.5px; outline: none;
            }
            .mb-input:focus { border-color: rgba(45,212,191,.5); }
            .mb-send {
                width: 38px; height: 38px; border: none; border-radius: 10px;
                background: linear-gradient(135deg, #2dd4bf, #22d3ee);
                cursor: pointer; color: #fff;
                display: flex; align-items: center; justify-content: center;
            }
            .mb-send:disabled { opacity: .4; cursor: default; }

            .mb-typing-dot {
                display: inline-block; width: 5px; height: 5px;
                margin: 0 2px; border-radius: 50%;
                background: rgba(255,255,255,.55);
                animation: mb-typ 1.2s infinite;
            }
            .mb-typing-dot:nth-child(2) { animation-delay: .15s; }
            .mb-typing-dot:nth-child(3) { animation-delay: .30s; }
            @keyframes mb-typ {
                0%, 60%, 100% { opacity: .3; transform: translateY(0); }
                30%           { opacity: 1;  transform: translateY(-3px); }
            }

            @media (max-width: 600px) {
                .mb-fab   { bottom: 16px; right: 16px; width: 52px; height: 52px; }
                .mb-panel { bottom: 80px; right: 12px; left: 12px; width: auto; height: 70vh; }
            }
        `;
        document.head.appendChild(s);
    }

    // ── DOM ─────────────────────────────────────────────────
    function injectDOM() {
        const root = document.createElement('div');
        root.id = 'mentor-bubble-root';
        root.innerHTML = `
            <button class="mb-fab" id="mb-fab" aria-label="打开财商学长 AI">
                <svg class="open-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
                <svg class="close-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
                <span class="mb-fab-badge">问学长</span>
            </button>
            <div class="mb-panel" id="mb-panel" role="dialog" aria-label="财商学长 AI">
                <div class="mb-header">
                    <div class="mb-header-title">
                        <div class="mb-avatar">AI</div>
                        <div>
                            财商学长
                            <div class="mb-header-sub">边学边问，不构成投资建议</div>
                        </div>
                    </div>
                    <div class="mb-header-actions">
                        <button class="mb-icon-btn" id="mb-clear" title="清空对话">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="3 6 5 6 21 6"/>
                                <path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/>
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="mb-messages" id="mb-messages"></div>
                <div class="mb-input-row">
                    <input type="text" class="mb-input" id="mb-input" placeholder="问学长任何财商问题…" maxlength="300"/>
                    <button class="mb-send" id="mb-send" title="发送">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="22" y1="2" x2="11" y2="13"/>
                            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                        </svg>
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(root);
    }

    // ── 渲染 ────────────────────────────────────────────────
    function renderMessages() {
        const container = document.getElementById('mb-messages');
        if (!container) return;
        container.innerHTML = _chatHistory.map(m => {
            const cls = m.role === 'user' ? 'user' : 'bot';
            const avatar = m.role === 'user'
                ? ((localStorage.getItem('cq_username') || 'U')[0] || 'U').toUpperCase()
                : 'AI';
            const text = escHtml(m.text || '').replace(/\n/g, '<br>');
            return `<div class="mb-msg ${cls}">
                <div class="mb-msg-avatar">${avatar}</div>
                <div class="mb-bubble">${text}</div>
            </div>`;
        }).join('');
        container.scrollTop = container.scrollHeight;
    }

    function appendMsg(msg) {
        _chatHistory.push(msg);
        renderMessages();
        saveLocalHistory();
    }

    function saveLocalHistory() {
        try { localStorage.setItem(CHAT_SK, JSON.stringify(_chatHistory.slice(-40))); } catch (_) {}
    }

    async function loadHistory() {
        if (_historyLoaded) return;
        _historyLoaded = true;
        const tok = localStorage.getItem('cq_token');
        if (tok) {
            try {
                const r = await fetch(`${API}/api/v1/chat/mentor/history?limit=20`, {
                    headers: { 'Authorization': 'Bearer ' + tok },
                });
                if (r.ok) {
                    const data = await r.json();
                    const msgs = (data.messages || []).map(m => ({
                        role: m.role === 'user' ? 'user' : 'bot',
                        text: m.content,
                        time: m.created_at ? fmtTime(new Date(m.created_at)) : '',
                    }));
                    _chatHistory = msgs.length ? msgs : [MENTOR_INTRO()];
                    try { localStorage.setItem(CHAT_SK, JSON.stringify(_chatHistory.slice(-40))); } catch (_) {}
                    renderMessages();
                    return;
                }
            } catch (e) {
                console.warn('[mentor-bubble] 服务端历史拉取失败，回退 localStorage:', e);
            }
        }
        try {
            const saved = localStorage.getItem(CHAT_SK);
            _chatHistory = saved ? JSON.parse(saved) : [MENTOR_INTRO()];
        } catch (_) {
            _chatHistory = [MENTOR_INTRO()];
        }
        renderMessages();
    }

    function showTyping() {
        const container = document.getElementById('mb-messages');
        if (!container) return;
        const el = document.createElement('div');
        el.id = 'mb-typing'; el.className = 'mb-msg bot';
        el.innerHTML = `<div class="mb-msg-avatar">AI</div>
            <div class="mb-bubble">
                <span class="mb-typing-dot"></span>
                <span class="mb-typing-dot"></span>
                <span class="mb-typing-dot"></span>
            </div>`;
        container.appendChild(el);
        container.scrollTop = container.scrollHeight;
    }
    function hideTyping() {
        const el = document.getElementById('mb-typing');
        if (el) el.remove();
    }

    async function sendChat() {
        const input = document.getElementById('mb-input');
        const text  = input.value.trim();
        if (!text) return;
        input.value = '';
        const btn = document.getElementById('mb-send');
        btn.disabled = true;

        appendMsg({ role: 'user', text, time: fmtTime(new Date()) });
        showTyping();

        try {
            const tok = localStorage.getItem('cq_token');
            const headers = { 'Content-Type': 'application/json; charset=utf-8' };
            if (tok) headers['Authorization'] = 'Bearer ' + tok;

            const body = {
                message: text,
                history: _chatHistory.slice(-10).map(m => ({
                    role: m.role === 'user' ? 'user' : 'assistant',
                    content: m.text,
                })),
            };

            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), 12000);
            const r = await fetch(`${API}/api/v1/chat/mentor`, {
                method: 'POST', headers, body: JSON.stringify(body), signal: ctrl.signal,
            });
            clearTimeout(timer);
            hideTyping();
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();
            appendMsg({ role: 'bot', text: data.reply || '学长暂时无法回答，请稍后再试', time: fmtTime(new Date()) });
        } catch (e) {
            hideTyping();
            appendMsg({
                role: 'bot',
                text: '学长暂时离线，请稍后再试。你可以先看看本页的相关模块，或去「学习资源库」继续学习。',
                time: fmtTime(new Date()),
            });
        } finally {
            btn.disabled = false;
            input.focus();
        }
    }

    async function clearChat() {
        const ok = window.cqConfirm
            ? await cqConfirm('清空全部对话历史？此操作无法撤销', '清空对话')
            : confirm('清空全部对话历史？');
        if (!ok) return;

        const tok = localStorage.getItem('cq_token');
        if (tok) {
            try {
                await fetch(`${API}/api/v1/chat/mentor/history`, {
                    method: 'DELETE',
                    headers: { 'Authorization': 'Bearer ' + tok },
                });
            } catch (_) {}
        }
        _chatHistory = [MENTOR_INTRO()];
        saveLocalHistory();
        renderMessages();
        if (window.cqToast) cqToast({ message: '对话已清空' }, 'success', 1800);
    }

    function toggle() {
        _isOpen = !_isOpen;
        document.getElementById('mb-fab').classList.toggle('open', _isOpen);
        document.getElementById('mb-panel').classList.toggle('open', _isOpen);
        if (_isOpen) {
            loadHistory();
            setTimeout(() => {
                const el = document.getElementById('mb-input');
                if (el) el.focus();
            }, 220);
        }
    }

    function init() {
        injectStyles();
        injectDOM();
        document.getElementById('mb-fab').addEventListener('click', toggle);
        document.getElementById('mb-clear').addEventListener('click', clearChat);
        document.getElementById('mb-send').addEventListener('click', sendChat);
        document.getElementById('mb-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && _isOpen) toggle();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
