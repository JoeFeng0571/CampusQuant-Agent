/* ════════════════════════════════════════════════════════
   magnet-cursor.js — 仅保留磁吸效果，移除自定义光标
   - 自定义光标已撤回（user feedback：太愚蠢）
   - 仅保留 [data-magnet] 元素吸住效果
   - 默认浏览器原生光标
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // ── 防御性清理：清掉旧版自定义光标的残留（Cloudflare 缓存可能 serve 老 JS）
    function cleanupOldCursor() {
        document.documentElement.style.cursor = '';
        if (document.body) document.body.style.cursor = '';
        const oldRing = document.getElementById('cq-cursor-ring');
        const oldDot = document.getElementById('cq-cursor-dot');
        if (oldRing) oldRing.remove();
        if (oldDot) oldDot.remove();
        // 清掉旧版注入的 cursor:none CSS
        document.querySelectorAll('style').forEach(s => {
            if (s.textContent && s.textContent.includes('cursor: none !important')) {
                s.remove();
            }
        });
    }
    cleanupOldCursor();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', cleanupOldCursor);
    }

    if (window.matchMedia('(hover: none) and (pointer: coarse)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    // ── MAGNET：[data-magnet] 元素被吸住
    // 性能优化：rAF 节流 + 缓存元素列表（避免每帧 querySelectorAll）
    function init() {
        let cachedEls = Array.from(document.querySelectorAll('[data-magnet]'));
        // DOM 变化时刷新缓存（懒维护，1s debounce 足够）
        let refreshTimer = null;
        const refreshCache = () => {
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(() => {
                cachedEls = Array.from(document.querySelectorAll('[data-magnet]'));
            }, 1000);
        };
        new MutationObserver(refreshCache).observe(document.body, {
            childList: true, subtree: true,
        });

        let pendingX = 0, pendingY = 0, frameQueued = false;
        const flush = () => {
            frameQueued = false;
            for (let i = 0; i < cachedEls.length; i++) {
                const el = cachedEls[i];
                const r = el.getBoundingClientRect();
                const cx = r.left + r.width / 2;
                const cy = r.top + r.height / 2;
                const dist = Math.hypot(pendingX - cx, pendingY - cy);
                const radius = parseFloat(el.dataset.magnet) || 80;
                if (dist < radius) {
                    const power = (1 - dist / radius) * 0.4;
                    const tx = (pendingX - cx) * power;
                    const ty = (pendingY - cy) * power;
                    el.style.transform = `translate(${tx}px,${ty}px)`;
                    el.style.transition = 'transform .15s cubic-bezier(.16,1,.3,1)';
                } else if (el.style.transform) {
                    el.style.transform = '';
                }
            }
        };
        document.addEventListener('mousemove', (e) => {
            pendingX = e.clientX;
            pendingY = e.clientY;
            if (!frameQueued) {
                frameQueued = true;
                requestAnimationFrame(flush);
            }
        }, { passive: true });
    }

    if (document.body) init();
    else document.addEventListener('DOMContentLoaded', init);
})();
