/* ════════════════════════════════════════════════════════
   view-transitions.js — 平滑页面切换
   - Chrome 111+ View Transitions API（无白屏）
   - 不支持的浏览器降级为 fade-out → 跳转
   - 拦截站内 <a> 点击，外部链接不拦
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }

    const supportsVT = typeof document.startViewTransition === 'function';

    // 注入过渡 CSS
    const style = document.createElement('style');
    style.textContent = `
        @view-transition { navigation: auto; }
        ::view-transition-old(root) {
            animation: vt-fade-out .25s cubic-bezier(.16,1,.3,1) both;
        }
        ::view-transition-new(root) {
            animation: vt-fade-in .35s cubic-bezier(.16,1,.3,1) both;
        }
        @keyframes vt-fade-out {
            from { opacity: 1; transform: translateY(0); }
            to   { opacity: 0; transform: translateY(-6px); }
        }
        @keyframes vt-fade-in {
            from { opacity: 0; transform: translateY(8px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        /* 不支持 VT 的浏览器：手动 fade */
        body.cq-fading { opacity: 0; transition: opacity .2s ease; }
    `;
    document.head.appendChild(style);

    // 是否站内链接
    function isInternalLink(href) {
        if (!href) return false;
        if (href.startsWith('#')) return false;
        if (href.startsWith('javascript:')) return false;
        if (href.startsWith('mailto:')) return false;
        if (href.startsWith('tel:')) return false;
        if (/^https?:\/\//i.test(href)) {
            try {
                const u = new URL(href);
                return u.host === location.host;
            } catch (_) { return false; }
        }
        return true;
    }

    // 拦截 <a> 点击
    document.addEventListener('click', (e) => {
        // 可能点的是 <a> 内部的 svg/span
        const a = e.target.closest('a[href]');
        if (!a) return;
        if (a.target === '_blank') return;
        if (a.hasAttribute('download')) return;
        if (a.dataset.noTransition) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        const href = a.getAttribute('href');
        if (!isInternalLink(href)) return;

        e.preventDefault();

        const navigate = () => { location.href = href; };

        if (supportsVT) {
            document.startViewTransition(() => {
                // 同步跳转
                navigate();
            });
        } else {
            // 降级 fade
            document.body.classList.add('cq-fading');
            setTimeout(navigate, 180);
        }
    }, true);
})();
