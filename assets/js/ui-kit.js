/* ════════════════════════════════════════════════════════
   ui-kit.js — 基础 UI 组件库
   - cqToast(message, type, duration)  顶部 toast 提示
   - cqDialog({title, content, actions}) 模态对话框
   - cqConfirm(message)                   确认框（Promise）
   - cqAlert(message)                     警告框（Promise）
   零依赖，自动注入 CSS
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (window.cqToast) return; // 防重复

    // ── 注入 CSS
    const style = document.createElement('style');
    style.id = 'cq-ui-kit-style';
    style.textContent = `
        /* TOAST */
        .cq-toast-stack {
            position: fixed;
            top: 80px;
            right: 24px;
            z-index: 9990;
            display: flex;
            flex-direction: column;
            gap: 12px;
            pointer-events: none;
        }
        .cq-toast {
            min-width: 280px;
            max-width: 380px;
            padding: 14px 18px 14px 16px;
            border-radius: 14px;
            background: rgba(15, 20, 35, 0.92);
            backdrop-filter: blur(20px) saturate(140%);
            -webkit-backdrop-filter: blur(20px) saturate(140%);
            border: 1px solid rgba(255,255,255,0.08);
            box-shadow:
                0 1px 0 rgba(255,255,255,0.06) inset,
                0 12px 32px rgba(0,0,0,0.3),
                0 24px 48px rgba(0,0,0,0.22);
            color: var(--text-1, #fff);
            font-size: 13px;
            line-height: 1.55;
            display: flex;
            align-items: flex-start;
            gap: 12px;
            pointer-events: auto;
            transform: translateX(120%);
            opacity: 0;
            transition: transform .4s cubic-bezier(.16,1,.3,1), opacity .35s;
        }
        .cq-toast.show { transform: translateX(0); opacity: 1; }
        .cq-toast.leave { transform: translateX(120%); opacity: 0; }
        .cq-toast-icon {
            width: 18px; height: 18px; flex-shrink: 0; margin-top: 1px;
        }
        .cq-toast-body { flex: 1; }
        .cq-toast-title { font-weight: 600; margin-bottom: 2px; color: #fff; }
        .cq-toast.success { border-left: 3px solid #5eead4; }
        .cq-toast.success .cq-toast-icon { color: #5eead4; }
        .cq-toast.error   { border-left: 3px solid #ff6b9d; }
        .cq-toast.error .cq-toast-icon { color: #ff6b9d; }
        .cq-toast.warn    { border-left: 3px solid #ffd86b; }
        .cq-toast.warn .cq-toast-icon { color: #ffd86b; }
        .cq-toast.info    { border-left: 3px solid #4facfe; }
        .cq-toast.info .cq-toast-icon { color: #4facfe; }

        /* DIALOG */
        .cq-dialog-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(5, 8, 16, 0.7);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 9995;
            opacity: 0;
            transition: opacity .35s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }
        .cq-dialog-backdrop.show { opacity: 1; }
        .cq-dialog {
            background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 22px;
            backdrop-filter: blur(28px) saturate(150%);
            -webkit-backdrop-filter: blur(28px) saturate(150%);
            box-shadow:
                0 1px 0 rgba(255,255,255,0.08) inset,
                0 1px 2px rgba(0,0,0,0.2),
                0 24px 56px rgba(0,0,0,0.4),
                0 48px 96px rgba(0,0,0,0.3);
            max-width: 460px;
            width: 100%;
            padding: 28px;
            transform: scale(0.94) translateY(8px);
            opacity: 0;
            transition: transform .4s cubic-bezier(.16,1,.3,1), opacity .35s;
        }
        .cq-dialog-backdrop.show .cq-dialog {
            transform: scale(1) translateY(0);
            opacity: 1;
        }
        .cq-dialog-title {
            font-size: 18px;
            font-weight: 700;
            color: #fff;
            margin-bottom: 8px;
            font-family: var(--font-display, inherit);
            letter-spacing: -0.015em;
        }
        .cq-dialog-content {
            color: var(--text-1, rgba(255,255,255,0.87));
            font-size: 14px;
            line-height: 1.65;
            margin-bottom: 22px;
        }
        .cq-dialog-actions {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
        }
        .cq-dialog-btn {
            padding: 9px 20px;
            border-radius: 10px;
            border: none;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all .2s cubic-bezier(.16,1,.3,1);
            font-family: inherit;
        }
        .cq-dialog-btn.primary {
            background: linear-gradient(135deg, #4facfe, #00f2fe);
            color: #0a0d17;
            box-shadow: 0 4px 16px rgba(79,172,254,0.3);
        }
        .cq-dialog-btn.primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 20px rgba(79,172,254,0.45);
        }
        .cq-dialog-btn.ghost {
            background: rgba(255,255,255,0.06);
            color: var(--text-1, rgba(255,255,255,0.87));
            border: 1px solid rgba(255,255,255,0.08);
        }
        .cq-dialog-btn.ghost:hover {
            background: rgba(255,255,255,0.1);
        }
        .cq-dialog-btn.danger {
            background: linear-gradient(135deg, #ff6b9d, #fd79a8);
            color: #fff;
        }
        .cq-dialog-btn:active { transform: scale(.97); }
    `;
    document.head.appendChild(style);

    // ── TOAST 容器
    let toastStack = null;
    function getStack() {
        if (toastStack) return toastStack;
        toastStack = document.createElement('div');
        toastStack.className = 'cq-toast-stack';
        document.body.appendChild(toastStack);
        return toastStack;
    }

    // SVG 图标
    const ICONS = {
        success: '<svg class="cq-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
        error:   '<svg class="cq-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        warn:    '<svg class="cq-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        info:    '<svg class="cq-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };

    // ── TOAST API
    window.cqToast = function (msg, type, duration) {
        type = type || 'info';
        duration = duration || 3500;
        const stack = getStack();

        const el = document.createElement('div');
        el.className = 'cq-toast ' + type;

        const isObj = typeof msg === 'object' && msg !== null;
        const title = isObj ? (msg.title || '') : '';
        const body  = isObj ? msg.message : msg;

        el.innerHTML = `
            ${ICONS[type] || ICONS.info}
            <div class="cq-toast-body">
                ${title ? `<div class="cq-toast-title">${escHtml(title)}</div>` : ''}
                <div>${escHtml(body)}</div>
            </div>
        `;
        stack.appendChild(el);
        requestAnimationFrame(() => el.classList.add('show'));

        const dismiss = () => {
            el.classList.remove('show');
            el.classList.add('leave');
            setTimeout(() => el.remove(), 450);
        };
        el.addEventListener('click', dismiss);
        setTimeout(dismiss, duration);
        return { dismiss };
    };

    function escHtml(s) {
        if (s == null) return '';
        const d = document.createElement('div');
        d.textContent = String(s);
        return d.innerHTML;
    }

    // ── DIALOG API
    window.cqDialog = function (opts) {
        opts = opts || {};
        return new Promise((resolve) => {
            const backdrop = document.createElement('div');
            backdrop.className = 'cq-dialog-backdrop';

            const dialog = document.createElement('div');
            dialog.className = 'cq-dialog';
            dialog.setAttribute('role', 'dialog');
            dialog.setAttribute('aria-modal', 'true');

            const actions = (opts.actions || [
                { label: '取消', value: false, type: 'ghost' },
                { label: '确定', value: true,  type: 'primary' },
            ]).map((a, i) => `<button class="cq-dialog-btn ${a.type || 'ghost'}" data-i="${i}">${escHtml(a.label)}</button>`).join('');

            dialog.innerHTML = `
                ${opts.title ? `<div class="cq-dialog-title">${escHtml(opts.title)}</div>` : ''}
                <div class="cq-dialog-content">${opts.content || ''}</div>
                <div class="cq-dialog-actions">${actions}</div>
            `;
            backdrop.appendChild(dialog);
            document.body.appendChild(backdrop);

            requestAnimationFrame(() => backdrop.classList.add('show'));

            const close = (val) => {
                backdrop.classList.remove('show');
                setTimeout(() => {
                    backdrop.remove();
                    resolve(val);
                }, 350);
            };

            // 按钮事件
            dialog.querySelectorAll('.cq-dialog-btn').forEach((btn, i) => {
                btn.addEventListener('click', () => {
                    const a = (opts.actions || [{ value: false }, { value: true }])[i];
                    close(a ? a.value : false);
                });
            });

            // 背景点击关闭
            backdrop.addEventListener('click', (e) => {
                if (e.target === backdrop) close(false);
            });

            // ESC 关闭
            const onKey = (e) => {
                if (e.key === 'Escape') {
                    close(false);
                    document.removeEventListener('keydown', onKey);
                }
            };
            document.addEventListener('keydown', onKey);
        });
    };

    // ── confirm / alert 简化版
    window.cqConfirm = function (message, title) {
        return cqDialog({
            title: title || '请确认',
            content: escHtml(message),
            actions: [
                { label: '取消', value: false, type: 'ghost' },
                { label: '确定', value: true,  type: 'primary' },
            ],
        });
    };

    window.cqAlert = function (message, title) {
        return cqDialog({
            title: title || '提示',
            content: escHtml(message),
            actions: [{ label: '知道了', value: true, type: 'primary' }],
        });
    };
})();
