/* ════════════════════════════════════════════════════════
   common.js — sidebar / auth widget / nav active
   每个页面只引入一次
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // ══════════ API base ══════════
    window.CQ_API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://127.0.0.1:8000'
        : window.location.origin;

    // ══════════ HTML escape util ══════════
    window.cqEsc = function (s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    };

    // ══════════ NAV active state ══════════
    function setNavActive() {
        const path = location.pathname.split('/').pop() || 'dashboard.html';
        document.querySelectorAll('header nav a[href]').forEach(a => {
            const href = a.getAttribute('href');
            if (!href || href.startsWith('javascript:')) return;
            if (href === path) a.classList.add('active');
        });
    }

    // ══════════ SIDEBAR ══════════
    function initSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        const toggle  = document.getElementById('sidebar-toggle');
        const close   = document.getElementById('sidebar-close');
        if (!sidebar || !overlay || !toggle) return;

        const open = () => {
            sidebar.classList.add('open');
            overlay.classList.add('open');
            document.body.style.overflow = 'hidden';
        };
        const closeFn = () => {
            sidebar.classList.remove('open');
            overlay.classList.remove('open');
            document.body.style.overflow = '';
        };
        toggle.addEventListener('click', open);
        if (close) close.addEventListener('click', closeFn);
        overlay.addEventListener('click', closeFn);
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && sidebar.classList.contains('open')) closeFn();
        });
    }

    // ══════════ AUTH WIDGET ══════════
    window.cqRenderAuthWidget = function () {
        const slot = document.getElementById('auth-widget');
        if (!slot) return;
        const token = localStorage.getItem('cq_token');
        const username = localStorage.getItem('cq_username') || '';

        if (token && username) {
            const initial = username.charAt(0).toUpperCase();
            slot.innerHTML = `
                <div class="auth-widget">
                    <div class="auth-avatar" title="${cqEsc(username)}" onclick="cqLogout()">${cqEsc(initial)}</div>
                    <span class="auth-name">${cqEsc(username)}</span>
                </div>`;
        } else {
            slot.innerHTML = `
                <div class="auth-widget">
                    <a href="auth.html" class="auth-login-btn">登录 / 注册</a>
                </div>`;
        }
    };

    window.cqLogout = function () {
        if (!confirm('确定要退出登录吗？')) return;
        localStorage.removeItem('cq_token');
        localStorage.removeItem('cq_username');
        cqRenderAuthWidget();
    };

    // ══════════ LUCIDE 图标渲染 ══════════
    // 等 Lucide CDN 加载完后调用 lucide.createIcons()
    function initLucideIcons() {
        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            try { lucide.createIcons(); } catch (e) { /* ignore */ }
            return true;
        }
        return false;
    }
    window.cqRefreshIcons = initLucideIcons;

    // ══════════ NAV TOOLBAR（设置/快捷键/命令面板按钮自动注入） ══════════
    function injectNavTools() {
        const nav = document.querySelector('header nav');
        if (!nav) return;
        if (nav.querySelector('.cq-nav-tools')) return;
        const tools = document.createElement('div');
        tools.className = 'cq-nav-tools';
        tools.style.cssText = 'display:flex;align-items:center;gap:6px;margin-left:8px;flex-shrink:0;';
        tools.innerHTML = `
            <button class="cq-nav-tool" title="命令面板 (⌘K)" onclick="cqCommandPalette && cqCommandPalette.open()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            </button>
            <button class="cq-nav-tool" title="设置 (⌘,)" onclick="cqSettings && cqSettings.open()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            </button>
        `;
        // 注入 CSS 一次
        if (!document.getElementById('cq-nav-tools-style')) {
            const s = document.createElement('style');
            s.id = 'cq-nav-tools-style';
            s.textContent = `
                .cq-nav-tool {
                    width: 32px; height: 32px;
                    border-radius: 8px;
                    border: 1px solid rgba(255,255,255,.06);
                    background: rgba(255,255,255,.03);
                    color: rgba(255,255,255,.55);
                    cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: all .2s;
                    padding: 0;
                }
                .cq-nav-tool:hover {
                    background: rgba(45,212,191,.12);
                    border-color: rgba(45,212,191,.30);
                    color: #2dd4bf;
                }
                @media (max-width: 768px) {
                    .cq-nav-tools { display: none !important; }
                }
            `;
            document.head.appendChild(s);
        }
        // 插入到 auth-widget 之前
        const authWidget = nav.querySelector('#auth-widget');
        if (authWidget) {
            nav.insertBefore(tools, authWidget);
        } else {
            nav.appendChild(tools);
        }
    }

    // ══════════ FIRST VISIT HINT ══════════
    // 首次访问时（一次性）提示新功能
    function showFirstVisitHint() {
        const HINT_KEY = 'cq_hint_v1_seen';
        if (localStorage.getItem(HINT_KEY)) return;
        // 等 ui-kit + lucide 都加载完
        let attempts = 0;
        const tryShow = () => {
            attempts++;
            if (window.cqToast) {
                setTimeout(() => {
                    cqToast({
                        title: '欢迎来到 CampusQuant',
                        message: '试试 ⌘K 命令面板，或点击右上角 ⚙ 图标个性化设置',
                    }, 'info', 7000);
                    localStorage.setItem(HINT_KEY, '1');
                }, 1200);
            } else if (attempts < 30) {
                setTimeout(tryShow, 200);
            }
        };
        tryShow();
    }

    // ══════════ INIT ══════════
    function init() {
        setNavActive();
        initSidebar();
        cqRenderAuthWidget();
        injectNavTools();
        showFirstVisitHint();
        // Lucide 可能还没加载，延迟试 + 重试
        if (!initLucideIcons()) {
            let tries = 0;
            const t = setInterval(() => {
                if (initLucideIcons() || ++tries > 20) clearInterval(t);
            }, 50);
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
