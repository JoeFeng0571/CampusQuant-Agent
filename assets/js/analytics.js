/* ════════════════════════════════════════════════════════
   analytics.js — 轻量级用户行为埋点
   - 页面访问 (PV)
   - 按钮点击 (关键操作)
   - 分析触发
   - 使用 sendBeacon 不阻塞页面
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const API = window.location.origin;
    const SESSION_ID = sessionStorage.getItem('cq_sid') || (() => {
        const id = 'S' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        sessionStorage.setItem('cq_sid', id);
        return id;
    })();

    function track(event, props) {
        const payload = {
            event: event,
            page: window.location.pathname,
            session: SESSION_ID,
            user: localStorage.getItem('cq_username') || 'anonymous',
            ts: new Date().toISOString(),
            ...props,
        };

        // Use sendBeacon (non-blocking, survives page unload)
        try {
            const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
            navigator.sendBeacon(API + '/api/v1/analytics/track', blob);
        } catch (e) {
            // Fallback to fetch
            fetch(API + '/api/v1/analytics/track', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                keepalive: true,
            }).catch(() => {});
        }
    }

    // Auto-track page view
    track('page_view');

    // Track key button clicks via data-track attribute
    // Usage: <button data-track="analyze_start">开始分析</button>
    document.addEventListener('click', function (e) {
        const el = e.target.closest('[data-track]');
        if (el) {
            track('click', { action: el.dataset.track, label: el.textContent.trim().slice(0, 30) });
        }
    });

    // Expose global for manual tracking
    window.cqTrack = track;
})();
