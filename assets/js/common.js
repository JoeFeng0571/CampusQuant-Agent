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

    // ══════════ INIT ══════════
    function init() {
        setNavActive();
        initSidebar();
        cqRenderAuthWidget();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
