/* ════════════════════════════════════════════════════════
   settings-drawer.js v5 — 右侧滑入设置抽屉
   - 主题切换（暗 / 明 / 跟随系统）
   - 背景动效开关
   - 减少动画
   - 账户登出
   - 持久化 localStorage
   - 快捷键 ⌘, / Ctrl+,
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (window.cqSettings) return;

    const STORAGE_KEY = 'cq_settings_v1';

    function loadPrefs() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
        catch (_) { return {}; }
    }
    function savePrefs(p) { localStorage.setItem(STORAGE_KEY, JSON.stringify(p)); }

    let prefs = loadPrefs();

    function applyPrefs() {
        // 背景模式
        if (prefs.bgMode && prefs.bgMode !== 'default') {
            document.body.dataset.bgMode = prefs.bgMode;
        } else {
            delete document.body.dataset.bgMode;
        }
        // 减动效
        document.body.classList.toggle('cq-reduce-motion', !!prefs.reduceMotion);
    }
    applyPrefs();

    // ── CSS ──────────────────────────────────────────────
    const STYLE = `
        .cq-settings-backdrop {
            position: fixed; inset: 0; z-index: 9993;
            background: rgba(0,0,0,.40);
            backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
            opacity: 0; transition: opacity .28s; pointer-events: none;
        }
        .cq-settings-backdrop.show { opacity: 1; pointer-events: auto; }

        /* Override base.css aside rule — drawer must be fixed + high z */
        aside.cq-settings-drawer {
            position: fixed !important;
            top: 0; right: 0; bottom: 0;
            width: min(360px, 92vw);
            background: #161b22;
            border-left: 1px solid rgba(255,255,255,.08);
            box-shadow: -16px 0 40px rgba(0,0,0,.45);
            z-index: 9994 !important;
            display: flex; flex-direction: column;
            transform: translateX(100%);
            transition: transform .32s cubic-bezier(.16,1,.3,1);
            color: rgba(255,255,255,.85);
        }
        aside.cq-settings-drawer.show { transform: translateX(0); }

        .cq-settings-header {
            display: flex; justify-content: space-between; align-items: center;
            padding: 20px 24px;
            border-bottom: 1px solid rgba(255,255,255,.07);
            flex-shrink: 0;
        }
        .cq-settings-title {
            font-size: 16px; font-weight: 700; letter-spacing: -0.01em;
            color: rgba(255,255,255,.95);
        }
        .cq-settings-close {
            background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.09);
            color: rgba(255,255,255,.55); width: 30px; height: 30px; border-radius: 7px;
            cursor: pointer; font-size: 17px; line-height: 1;
            display: flex; align-items: center; justify-content: center;
            transition: background .15s, color .15s;
        }
        .cq-settings-close:hover { background: rgba(255,255,255,.12); color: rgba(255,255,255,.90); }

        .cq-settings-body { flex: 1; overflow-y: auto; padding: 12px 24px 20px; }
        .cq-settings-section { margin-top: 20px; }
        .cq-settings-section-title {
            font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em;
            color: rgba(255,255,255,.38); font-weight: 700; margin-bottom: 8px;
            font-family: var(--font-mono, monospace);
        }

        .cq-settings-row {
            display: flex; justify-content: space-between; align-items: center;
            padding: 11px 0; font-size: 13px;
            border-bottom: 1px solid rgba(255,255,255,.05);
        }
        .cq-settings-row:last-child { border-bottom: none; }
        .cq-settings-label { color: rgba(255,255,255,.85); font-weight: 500; }
        .cq-settings-desc { font-size: 11px; color: rgba(255,255,255,.38); margin-top: 2px; }

        /* Segmented control */
        .cq-seg {
            display: inline-flex; background: rgba(255,255,255,.05);
            border: 1px solid rgba(255,255,255,.08); border-radius: 8px;
            padding: 2px; gap: 2px;
        }
        .cq-seg button {
            background: none; border: none; padding: 5px 10px; border-radius: 6px;
            font-size: 12px; color: rgba(255,255,255,.55); cursor: pointer;
            font-family: inherit; transition: color .15s, background .15s; white-space: nowrap;
        }
        .cq-seg button:hover { color: rgba(255,255,255,.85); }
        .cq-seg button.active {
            background: rgba(129,140,248,.22); color: #a5b4fc;
            box-shadow: 0 0 0 1px rgba(129,140,248,.35) inset;
        }

        /* Toggle */
        .cq-toggle {
            position: relative; width: 36px; height: 20px;
            background: rgba(255,255,255,.12); border-radius: 999px;
            cursor: pointer; transition: background .2s; border: none; flex-shrink: 0;
        }
        .cq-toggle::after {
            content: ''; position: absolute; top: 2px; left: 2px;
            width: 16px; height: 16px; border-radius: 50%; background: #fff;
            transition: left .22s cubic-bezier(.16,1,.3,1);
        }
        .cq-toggle.on { background: #6366f1; }
        .cq-toggle.on::after { left: 18px; }

        /* Account section */
        .cq-account-card {
            display: flex; align-items: center; gap: 12px;
            padding: 12px 14px;
            background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.08);
            border-radius: 10px; margin-bottom: 10px;
        }
        .cq-account-avatar {
            width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
            background: rgba(129,140,248,.22); border: 1px solid rgba(129,140,248,.35);
            display: flex; align-items: center; justify-content: center;
            font-size: 14px; font-weight: 700; color: #818cf8;
        }
        .cq-account-name { font-size: 13px; font-weight: 600; color: rgba(255,255,255,.90); }
        .cq-account-sub { font-size: 11px; color: rgba(255,255,255,.40); margin-top: 1px; }
        .cq-logout-btn {
            margin-left: auto; flex-shrink: 0;
            background: rgba(248,113,113,.12); border: 1px solid rgba(248,113,113,.25);
            color: #f87171; font-size: 12px; padding: 5px 12px; border-radius: 6px;
            cursor: pointer; font-family: inherit; transition: background .15s;
        }
        .cq-logout-btn:hover { background: rgba(248,113,113,.22); }

        .cq-login-btn {
            display: block; width: 100%; padding: 9px; border-radius: 8px; text-align: center;
            background: rgba(129,140,248,.15); border: 1px solid rgba(129,140,248,.28);
            color: #818cf8; font-size: 13px; font-weight: 500; cursor: pointer;
            text-decoration: none; transition: background .15s; margin-bottom: 6px;
        }
        .cq-login-btn:hover { background: rgba(129,140,248,.25); }

        /* Footer */
        .cq-settings-footer {
            padding: 14px 24px 18px;
            border-top: 1px solid rgba(255,255,255,.06);
            font-size: 11px; color: rgba(255,255,255,.35);
            font-family: var(--font-mono, monospace);
            display: flex; justify-content: space-between; align-items: center;
            flex-shrink: 0;
        }
        .cq-settings-version {
            background: rgba(255,255,255,.06); padding: 2px 7px; border-radius: 4px;
        }

        /* Reduce motion */
        .cq-reduce-motion *, .cq-reduce-motion *::before, .cq-reduce-motion *::after {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
        }
    `;

    let drawer = null;
    let backdrop = null;
    let isOpen = false;

    function buildDrawerHTML() {
        const token    = localStorage.getItem('cq_token');
        const username = localStorage.getItem('cq_username') || '用户';
        const initial  = username[0].toUpperCase();

        const accountSection = token ? `
            <div class="cq-settings-section">
                <div class="cq-settings-section-title">账户</div>
                <div class="cq-account-card">
                    <div class="cq-account-avatar">${initial}</div>
                    <div>
                        <div class="cq-account-name">${username}</div>
                        <div class="cq-account-sub">模拟投资学员</div>
                    </div>
                    <button class="cq-logout-btn">退出登录</button>
                </div>
            </div>
        ` : `
            <div class="cq-settings-section">
                <div class="cq-settings-section-title">账户</div>
                <a href="auth.html?redirect=${encodeURIComponent(location.pathname + location.search)}" class="cq-login-btn">登录 / 注册</a>
            </div>
        `;

        return `
            <div class="cq-settings-header">
                <div class="cq-settings-title">设置</div>
                <button class="cq-settings-close" aria-label="关闭">×</button>
            </div>
            <div class="cq-settings-body">
                ${accountSection}
                <div class="cq-settings-section">
                    <div class="cq-settings-section-title">外观</div>
                    <div class="cq-settings-row">
                        <div>
                            <div class="cq-settings-label">背景动效</div>
                            <div class="cq-settings-desc">粒子 / 柔和 / 关闭</div>
                        </div>
                        <div class="cq-seg" data-pref="bgMode">
                            <button data-v="default">完整</button>
                            <button data-v="quiet">柔和</button>
                            <button data-v="off">关闭</button>
                        </div>
                    </div>
                    <div class="cq-settings-row">
                        <div>
                            <div class="cq-settings-label">减少动画</div>
                            <div class="cq-settings-desc">晕动症友好模式</div>
                        </div>
                        <button class="cq-toggle" data-pref="reduceMotion"></button>
                    </div>
                </div>
                <div class="cq-settings-section">
                    <div class="cq-settings-section-title">关于</div>
                    <div class="cq-settings-row">
                        <div class="cq-settings-label">CampusQuant</div>
                        <a href="team.html" style="color:var(--primary,#818cf8);font-size:12px;text-decoration:none">关于团队 →</a>
                    </div>
                    <div class="cq-settings-row">
                        <div class="cq-settings-label">版本</div>
                        <span class="cq-ver-span" style="font-size:11px;font-family:var(--font-mono,monospace);color:rgba(255,255,255,.38)">v1.0.0</span>
                    </div>
                </div>
            </div>
            <div class="cq-settings-footer">
                <span>全部交易均为模拟</span>
                <span class="cq-settings-version">校园财商</span>
            </div>
        `;
    }

    function syncUI() {
        if (!drawer) return;
        // Sync segmented controls
        drawer.querySelectorAll('.cq-seg[data-pref]').forEach(seg => {
            const cur = prefs[seg.dataset.pref] || 'default';
            seg.querySelectorAll('button[data-v]').forEach(b => {
                b.classList.toggle('active', b.dataset.v === cur);
            });
        });
        // Sync toggles
        drawer.querySelectorAll('.cq-toggle[data-pref]').forEach(t => {
            t.classList.toggle('on', !!prefs[t.dataset.pref]);
        });
    }

    async function doLogout() {
        const confirmed = window.cqConfirm
            ? await cqConfirm('确定退出登录吗？', '退出登录')
            : confirm('确定退出登录吗？');
        if (!confirmed) return;
        localStorage.removeItem('cq_token');
        localStorage.removeItem('cq_username');
        close();
        if (window.cqRenderAuthWidget) cqRenderAuthWidget();
        setTimeout(() => { location.href = 'index.html'; }, 300);
    }

    // ── Event delegation — one listener on drawer, survives innerHTML swaps ──
    function handleDrawerClick(e) {
        const t = e.target;

        // Close button
        if (t.closest('.cq-settings-close')) { close(); return; }

        // Logout button
        if (t.closest('.cq-logout-btn')) { doLogout(); return; }

        // Segmented control button
        const segBtn = t.closest('[data-v]');
        const seg = segBtn && segBtn.closest('.cq-seg[data-pref]');
        if (segBtn && seg) {
            const pref = seg.dataset.pref;
            prefs[pref] = segBtn.dataset.v;
            savePrefs(prefs);
            syncUI();
            applyPrefs();
            return;
        }

        // Toggle button
        const tog = t.closest('.cq-toggle[data-pref]');
        if (tog) {
            prefs[tog.dataset.pref] = !prefs[tog.dataset.pref];
            savePrefs(prefs);
            syncUI();
            applyPrefs();
            return;
        }
    }

    function build() {
        if (!document.getElementById('cq-settings-style')) {
            const s = document.createElement('style');
            s.id = 'cq-settings-style';
            s.textContent = STYLE;
            document.head.appendChild(s);
        }

        backdrop = document.createElement('div');
        backdrop.className = 'cq-settings-backdrop';
        document.body.appendChild(backdrop);

        drawer = document.createElement('aside');
        drawer.className = 'cq-settings-drawer';
        drawer.setAttribute('role', 'dialog');
        drawer.setAttribute('aria-modal', 'true');
        document.body.appendChild(drawer);

        // Event delegation — bind ONCE, survives all future innerHTML replacements
        drawer.addEventListener('click', handleDrawerClick);
        backdrop.addEventListener('click', close);
    }

    function open() {
        if (isOpen) return;
        if (!drawer) build();
        // Rebuild content (account section needs to reflect current login state)
        drawer.innerHTML = buildDrawerHTML();
        syncUI();
        isOpen = true;
        backdrop.classList.add('show');
        requestAnimationFrame(() => drawer.classList.add('show'));
    }

    function close() {
        if (!isOpen || !drawer) return;
        isOpen = false;
        drawer.classList.remove('show');
        backdrop.classList.remove('show');
    }

    function toggle() { isOpen ? close() : open(); }

    // Keyboard shortcut Cmd+, / Ctrl+,
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === ',') { e.preventDefault(); toggle(); }
        else if (e.key === 'Escape' && isOpen) close();
    });

    window.cqSettings = { open, close, toggle, prefs, applyPrefs };
})();
