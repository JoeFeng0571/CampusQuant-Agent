/* ════════════════════════════════════════════════════════
   keyboard-shortcuts.js — 按 ? 弹出键盘快捷键面板
   - Linear / GitHub / Notion 同款
   - 不与输入框冲突
   - 自动注入 CSS
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (window.cqKeyShortcuts) return;

    const SHORTCUTS = [
        { group: '导航', items: [
            { keys: ['⌘', 'K'], label: '打开命令面板' },
            { keys: ['G', 'D'], label: '跳转到控制台', href: 'dashboard.html' },
            { keys: ['G', 'T'], label: '跳转到模拟交易', href: 'trade.html' },
            { keys: ['G', 'M'], label: '跳转到市场快讯', href: 'market.html' },
            { keys: ['G', 'A'], label: '跳转到个股分析', href: 'analysis.html' },
            { keys: ['G', 'C'], label: '跳转到投教社区', href: 'community.html' },
            { keys: ['G', 'L'], label: '跳转到学习中心', href: 'home.html' },
        ]},
        { group: '操作', items: [
            { keys: ['?'],         label: '显示快捷键' },
            { keys: ['Esc'],       label: '关闭弹窗' },
            { keys: ['/'],         label: '聚焦搜索（如有）' },
        ]},
        { group: '阅读', items: [
            { keys: ['↑', '↓'],    label: '滚动' },
            { keys: ['PgUp/PgDn'], label: '翻页' },
            { keys: ['Home/End'],  label: '回到顶部 / 底部' },
        ]},
    ];

    const STYLE = `
        .cq-kbd-backdrop {
            position: fixed; inset: 0; z-index: 9994;
            background: rgba(5,8,16,.75);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            display: flex; align-items: center; justify-content: center;
            padding: 24px;
            opacity: 0;
            pointer-events: none;
            transition: opacity .3s ease;
        }
        .cq-kbd-backdrop.show {
            opacity: 1;
            pointer-events: auto;
        }
        .cq-kbd-panel {
            background: linear-gradient(180deg, rgba(20,25,40,.96), rgba(15,20,35,.96));
            border: 1px solid rgba(255,255,255,.1);
            border-radius: 20px;
            backdrop-filter: blur(28px) saturate(150%);
            -webkit-backdrop-filter: blur(28px) saturate(150%);
            box-shadow:
                0 1px 0 rgba(255,255,255,.08) inset,
                0 24px 56px rgba(0,0,0,.5),
                0 48px 96px rgba(0,0,0,.4);
            max-width: 600px;
            width: 100%;
            max-height: 80vh;
            overflow-y: auto;
            padding: 32px;
            transform: scale(.94) translateY(8px);
            opacity: 0;
            transition: transform .35s cubic-bezier(.16,1,.3,1), opacity .3s;
        }
        .cq-kbd-backdrop.show .cq-kbd-panel { transform: scale(1) translateY(0); opacity: 1; }
        .cq-kbd-header {
            display: flex; justify-content: space-between; align-items: flex-start;
            margin-bottom: 24px;
        }
        .cq-kbd-title {
            font-family: var(--font-display, inherit);
            font-size: 20px;
            font-weight: 700;
            color: #fff;
            letter-spacing: -0.015em;
            margin-bottom: 4px;
        }
        .cq-kbd-sub {
            font-size: 12px;
            color: var(--text-2, rgba(255,255,255,.65));
            font-family: var(--font-mono, monospace);
        }
        .cq-kbd-close {
            background: rgba(255,255,255,.06);
            border: 1px solid rgba(255,255,255,.08);
            color: var(--text-2, rgba(255,255,255,.65));
            width: 32px; height: 32px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 18px;
            line-height: 1;
            display: flex; align-items: center; justify-content: center;
        }
        .cq-kbd-close:hover { background: rgba(255,255,255,.1); color: #fff; }
        .cq-kbd-group {
            margin-bottom: 22px;
        }
        .cq-kbd-group:last-child { margin-bottom: 0; }
        .cq-kbd-group-title {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-3, rgba(255,255,255,.45));
            font-weight: 700;
            margin-bottom: 12px;
            font-family: var(--font-mono, monospace);
        }
        .cq-kbd-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,.04);
        }
        .cq-kbd-row:last-child { border-bottom: none; }
        .cq-kbd-label {
            font-size: 13px;
            color: var(--text-1, rgba(255,255,255,.87));
        }
        .cq-kbd-keys {
            display: flex; gap: 4px; align-items: center;
        }
        .cq-kbd-keys kbd {
            font-family: var(--font-mono, monospace);
            font-size: 11px;
            min-width: 22px;
            padding: 4px 8px;
            border-radius: 6px;
            background: rgba(255,255,255,.06);
            border: 1px solid rgba(255,255,255,.1);
            color: var(--text-1, rgba(255,255,255,.85));
            text-align: center;
            box-shadow: 0 1px 0 rgba(255,255,255,.04) inset;
        }
        .cq-kbd-plus {
            color: var(--text-3, rgba(255,255,255,.4));
            font-size: 11px;
        }
    `;

    function injectStyle() {
        if (document.getElementById('cq-kbd-style')) return;
        const s = document.createElement('style');
        s.id = 'cq-kbd-style';
        s.textContent = STYLE;
        document.head.appendChild(s);
    }

    let backdrop = null;
    let isOpen = false;

    function build() {
        injectStyle();
        backdrop = document.createElement('div');
        backdrop.className = 'cq-kbd-backdrop';

        let inner = `
            <div class="cq-kbd-panel" role="dialog" aria-modal="true">
                <div class="cq-kbd-header">
                    <div>
                        <div class="cq-kbd-title">键盘快捷键</div>
                        <div class="cq-kbd-sub">按 ? 唤起 · ESC 关闭</div>
                    </div>
                    <button class="cq-kbd-close" aria-label="关闭">×</button>
                </div>
        `;
        SHORTCUTS.forEach(g => {
            inner += `<div class="cq-kbd-group"><div class="cq-kbd-group-title">${g.group}</div>`;
            g.items.forEach(it => {
                const keys = it.keys.map(k => `<kbd>${k}</kbd>`).join(' ');
                inner += `<div class="cq-kbd-row">
                    <span class="cq-kbd-label">${it.label}</span>
                    <span class="cq-kbd-keys">${keys}</span>
                </div>`;
            });
            inner += `</div>`;
        });
        inner += `</div>`;
        backdrop.innerHTML = inner;
        document.body.appendChild(backdrop);

        backdrop.querySelector('.cq-kbd-close').addEventListener('click', close);
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) close();
        });
    }

    function open() {
        if (isOpen) return;
        if (!backdrop) build();
        isOpen = true;
        requestAnimationFrame(() => backdrop.classList.add('show'));
    }
    function close() {
        if (!isOpen || !backdrop) return;
        isOpen = false;
        backdrop.classList.remove('show');
    }
    function toggle() { isOpen ? close() : open(); }

    // 全局快捷键
    document.addEventListener('keydown', (e) => {
        // 输入框内不响应
        const target = e.target;
        if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
            if (e.key === 'Escape' && isOpen) { close(); }
            return;
        }
        if (e.key === '?' || (e.shiftKey && e.key === '/')) {
            e.preventDefault();
            toggle();
        } else if (e.key === 'Escape') {
            close();
        }
    });

    window.cqKeyShortcuts = { open, close, toggle };
})();
