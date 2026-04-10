/* ════════════════════════════════════════════════════════
   settings-drawer.js — 右侧滑入设置抽屉
   - 主题切换（明 / 暗 / 跟随系统）
   - 背景模式（ambient / quiet / minimal / off）
   - 动效强度
   - 语言（占位）
   - 持久化到 localStorage，重新加载生效
   - 支持快捷键 ⌘, (Mac) / Ctrl+, (Win)
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (window.cqSettings) return;

    const STORAGE_KEY = 'cq_settings_v1';

    function loadPrefs() {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
        } catch (_) { return {}; }
    }
    function savePrefs(p) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
    }

    let prefs = loadPrefs();

    // 应用 prefs（在抽屉之外也会自动调用）
    function applyPrefs() {
        // 背景模式
        if (prefs.bgMode && prefs.bgMode !== 'default') {
            document.body.dataset.bgMode = prefs.bgMode;
        }
        // 减动效
        if (prefs.reduceMotion) {
            document.body.classList.add('cq-reduce-motion');
        } else {
            document.body.classList.remove('cq-reduce-motion');
        }
        // 主题（dark / light / auto）
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        if (prefs.theme === 'light' || (prefs.theme === 'auto' && !prefersDark)) {
            document.documentElement.dataset.theme = 'light';
        } else {
            document.documentElement.dataset.theme = 'dark';
        }
    }
    applyPrefs();

    // CSS
    const STYLE = `
        .cq-settings-backdrop {
            position: fixed; inset: 0; z-index: 9993;
            background: rgba(5,8,16,.55);
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
            opacity: 0;
            transition: opacity .35s ease;
            pointer-events: none;
        }
        .cq-settings-backdrop.show {
            opacity: 1;
            pointer-events: auto;
        }
        .cq-settings-drawer {
            position: fixed;
            top: 0; right: 0;
            bottom: 0;
            width: min(380px, 92vw);
            background: linear-gradient(180deg, rgba(15,20,35,.97), rgba(10,14,25,.97));
            border-left: 1px solid rgba(255,255,255,.08);
            backdrop-filter: blur(28px) saturate(150%);
            -webkit-backdrop-filter: blur(28px) saturate(150%);
            box-shadow: -24px 0 56px rgba(0,0,0,.4);
            z-index: 9994;
            display: flex;
            flex-direction: column;
            transform: translateX(100%);
            transition: transform .4s cubic-bezier(.16,1,.3,1);
            color: var(--text-1, rgba(255,255,255,.87));
        }
        .cq-settings-drawer.show { transform: translateX(0); }
        .cq-settings-header {
            display: flex; justify-content: space-between; align-items: center;
            padding: 24px 28px;
            border-bottom: 1px solid rgba(255,255,255,.06);
        }
        .cq-settings-title {
            font-family: var(--font-display, inherit);
            font-size: 20px;
            font-weight: 700;
            color: #fff;
            letter-spacing: -0.015em;
        }
        .cq-settings-close {
            background: rgba(255,255,255,.06);
            border: 1px solid rgba(255,255,255,.08);
            color: var(--text-2, rgba(255,255,255,.65));
            width: 32px; height: 32px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 18px;
            line-height: 1;
            display: flex; align-items: center; justify-content: center;
            transition: all .2s;
        }
        .cq-settings-close:hover { background: rgba(255,255,255,.1); color: #fff; }
        .cq-settings-body {
            flex: 1;
            overflow-y: auto;
            padding: 16px 28px 28px;
        }
        .cq-settings-section {
            margin-top: 22px;
        }
        .cq-settings-section-title {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-3, rgba(255,255,255,.45));
            font-weight: 700;
            margin-bottom: 10px;
            font-family: var(--font-mono, monospace);
        }
        .cq-settings-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            font-size: 13px;
            border-bottom: 1px solid rgba(255,255,255,.04);
        }
        .cq-settings-row:last-child { border-bottom: none; }
        .cq-settings-label { color: var(--text-1, rgba(255,255,255,.87)); }
        .cq-settings-desc {
            font-size: 11px;
            color: var(--text-3, rgba(255,255,255,.4));
            margin-top: 2px;
        }
        .cq-seg {
            display: inline-flex;
            background: rgba(255,255,255,.05);
            border: 1px solid rgba(255,255,255,.08);
            border-radius: 8px;
            padding: 2px;
            gap: 2px;
        }
        .cq-seg button {
            background: none;
            border: none;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            color: var(--text-2, rgba(255,255,255,.65));
            cursor: pointer;
            font-family: inherit;
            transition: all .2s;
        }
        .cq-seg button:hover { color: #fff; }
        .cq-seg button.active {
            background: linear-gradient(135deg, rgba(79,172,254,.25), rgba(0,242,254,.15));
            color: #fff;
            box-shadow: 0 0 0 1px rgba(79,172,254,.35) inset;
        }
        .cq-toggle {
            position: relative;
            width: 36px; height: 20px;
            background: rgba(255,255,255,.1);
            border-radius: 999px;
            cursor: pointer;
            transition: background .2s;
            border: none;
        }
        .cq-toggle::after {
            content: '';
            position: absolute;
            top: 2px; left: 2px;
            width: 16px; height: 16px;
            border-radius: 50%;
            background: #fff;
            transition: all .25s cubic-bezier(.16,1,.3,1);
        }
        .cq-toggle.on {
            background: linear-gradient(135deg, #4facfe, #00f2fe);
        }
        .cq-toggle.on::after { left: 18px; }
        .cq-settings-footer {
            padding: 16px 28px 24px;
            border-top: 1px solid rgba(255,255,255,.06);
            font-size: 11px;
            color: var(--text-3, rgba(255,255,255,.45));
            font-family: var(--font-mono, monospace);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .cq-settings-version {
            background: rgba(255,255,255,.05);
            padding: 3px 8px;
            border-radius: 5px;
        }
        .cq-reduce-motion *, .cq-reduce-motion *::before, .cq-reduce-motion *::after {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
        }
    `;

    let drawer = null;
    let backdrop = null;
    let isOpen = false;

    function build() {
        const s = document.createElement('style');
        s.id = 'cq-settings-style';
        s.textContent = STYLE;
        document.head.appendChild(s);

        backdrop = document.createElement('div');
        backdrop.className = 'cq-settings-backdrop';
        document.body.appendChild(backdrop);

        drawer = document.createElement('aside');
        drawer.className = 'cq-settings-drawer';
        drawer.setAttribute('role', 'dialog');
        drawer.setAttribute('aria-modal', 'true');
        drawer.innerHTML = `
            <div class="cq-settings-header">
                <div class="cq-settings-title">设置</div>
                <button class="cq-settings-close" aria-label="关闭">×</button>
            </div>
            <div class="cq-settings-body">
                <div class="cq-settings-section">
                    <div class="cq-settings-section-title">外观</div>
                    <div class="cq-settings-row">
                        <div>
                            <div class="cq-settings-label">主题</div>
                            <div class="cq-settings-desc">暗色 / 明亮 / 跟随系统</div>
                        </div>
                        <div class="cq-seg" data-pref="theme">
                            <button data-v="dark">暗</button>
                            <button data-v="light">明</button>
                            <button data-v="auto">自动</button>
                        </div>
                    </div>
                    <div class="cq-settings-row">
                        <div>
                            <div class="cq-settings-label">背景动效</div>
                            <div class="cq-settings-desc">极光 / 点阵 / 流沙的强度</div>
                        </div>
                        <div class="cq-seg" data-pref="bgMode">
                            <button data-v="default">完整</button>
                            <button data-v="quiet">柔和</button>
                            <button data-v="minimal">极简</button>
                            <button data-v="off">关闭</button>
                        </div>
                    </div>
                    <div class="cq-settings-row">
                        <div>
                            <div class="cq-settings-label">减少动画</div>
                            <div class="cq-settings-desc">关闭所有动效（晕动症友好）</div>
                        </div>
                        <button class="cq-toggle" data-pref="reduceMotion"></button>
                    </div>
                </div>
                <div class="cq-settings-section">
                    <div class="cq-settings-section-title">语言</div>
                    <div class="cq-settings-row">
                        <div>
                            <div class="cq-settings-label">界面语言</div>
                            <div class="cq-settings-desc">English coming soon</div>
                        </div>
                        <div class="cq-seg" data-pref="lang">
                            <button data-v="zh">简体中文</button>
                            <button data-v="en" disabled style="opacity:.4;cursor:not-allowed">English</button>
                        </div>
                    </div>
                </div>
                <div class="cq-settings-section">
                    <div class="cq-settings-section-title">关于</div>
                    <div class="cq-settings-row">
                        <div class="cq-settings-label">CampusQuant</div>
                        <a href="team.html" style="color:var(--secondary,#00f2fe);font-size:12px;text-decoration:none">团队</a>
                    </div>
                    <div class="cq-settings-row">
                        <div class="cq-settings-label">键盘快捷键</div>
                        <button class="cq-seg" style="cursor:pointer;padding:5px 10px;font-size:11px;color:var(--text-1)" onclick="cqSettings.close();setTimeout(()=>cqKeyShortcuts && cqKeyShortcuts.open(),200)">查看 ?</button>
                    </div>
                </div>
            </div>
            <div class="cq-settings-footer">
                <span>校园财商 · 全部模拟数据</span>
                <span class="cq-settings-version">v1.0.0</span>
            </div>
        `;
        document.body.appendChild(drawer);

        // 绑定
        drawer.querySelector('.cq-settings-close').addEventListener('click', close);
        backdrop.addEventListener('click', close);

        // segmented controls
        drawer.querySelectorAll('.cq-seg[data-pref]').forEach(seg => {
            const pref = seg.dataset.pref;
            seg.querySelectorAll('button[data-v]').forEach(b => {
                b.addEventListener('click', () => {
                    if (b.disabled) return;
                    const val = b.dataset.v;
                    prefs[pref] = val;
                    savePrefs(prefs);
                    syncUI();
                    if (pref === 'bgMode') {
                        // 背景模式立即生效需要重载（因为 JS 在加载时读取一次）
                        cqToast && cqToast({ title: '设置已保存', message: '刷新后生效' }, 'success');
                    } else {
                        applyPrefs();
                    }
                });
            });
        });

        // toggles
        drawer.querySelectorAll('.cq-toggle[data-pref]').forEach(t => {
            t.addEventListener('click', () => {
                const pref = t.dataset.pref;
                prefs[pref] = !prefs[pref];
                savePrefs(prefs);
                syncUI();
                applyPrefs();
            });
        });

        syncUI();
    }

    function syncUI() {
        if (!drawer) return;
        // segs
        drawer.querySelectorAll('.cq-seg[data-pref]').forEach(seg => {
            const pref = seg.dataset.pref;
            const cur = prefs[pref] || (pref === 'theme' ? 'dark' : pref === 'lang' ? 'zh' : 'default');
            seg.querySelectorAll('button[data-v]').forEach(b => {
                b.classList.toggle('active', b.dataset.v === cur);
            });
        });
        // toggles
        drawer.querySelectorAll('.cq-toggle[data-pref]').forEach(t => {
            t.classList.toggle('on', !!prefs[t.dataset.pref]);
        });
    }

    function open() {
        if (isOpen) return;
        if (!drawer) build();
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

    // 全局快捷键 Cmd+, / Ctrl+,
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === ',') {
            e.preventDefault();
            toggle();
        } else if (e.key === 'Escape' && isOpen) {
            close();
        }
    });

    window.cqSettings = { open, close, toggle, prefs, applyPrefs };
})();
