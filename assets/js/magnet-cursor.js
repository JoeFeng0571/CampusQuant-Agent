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
    function init() {
        const magnetEls = () => document.querySelectorAll('[data-magnet]');
        document.addEventListener('mousemove', (e) => {
            magnetEls().forEach(el => {
                const r = el.getBoundingClientRect();
                const cx = r.left + r.width / 2;
                const cy = r.top + r.height / 2;
                const dist = Math.hypot(e.clientX - cx, e.clientY - cy);
                const radius = parseFloat(el.dataset.magnet) || 80;
                if (dist < radius) {
                    const power = (1 - dist / radius) * 0.4;
                    const tx = (e.clientX - cx) * power;
                    const ty = (e.clientY - cy) * power;
                    el.style.transform = `translate(${tx}px,${ty}px)`;
                    el.style.transition = 'transform .15s cubic-bezier(.16,1,.3,1)';
                } else {
                    el.style.transform = '';
                }
            });
        }, { passive: true });
    }

    if (document.body) init();
    else document.addEventListener('DOMContentLoaded', init);
})();
