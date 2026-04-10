/* ════════════════════════════════════════════════════════
   reading-progress.js — 顶部阅读进度条 + 返回顶部按钮
   - 仅在 body[data-bg-mode="quiet"] 文字页启用
   - 顶部 2px 渐变进度条
   - 滚动 600px 后右下角浮出"返回顶部"按钮
   - 零依赖
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function init() {
        // 仅文字页启用
        if (!document.body || document.body.dataset.bgMode !== 'quiet') return;

        // ── 进度条
        const bar = document.createElement('div');
        bar.id = 'cq-reading-progress';
        bar.style.cssText = [
            'position:fixed',
            'top:0', 'left:0',
            'height:2px',
            'width:0%',
            'background:linear-gradient(90deg,#2dd4bf,#22d3ee,#22d3ee)',
            'z-index:9991',
            'transition:width .12s ease-out',
            'box-shadow:0 0 12px rgba(34,211,238,.5)',
            'pointer-events:none',
        ].join(';');
        document.body.appendChild(bar);

        // ── 返回顶部按钮
        const btn = document.createElement('button');
        btn.id = 'cq-back-to-top';
        btn.setAttribute('aria-label', '返回顶部');
        btn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>';
        btn.style.cssText = [
            'position:fixed',
            'right:24px', 'bottom:24px',
            'width:44px', 'height:44px',
            'border-radius:50%',
            'border:1px solid rgba(255,255,255,.12)',
            'background:rgba(20,25,40,0.9)',
            'backdrop-filter:blur(20px)',
            '-webkit-backdrop-filter:blur(20px)',
            'color:rgba(255,255,255,.85)',
            'cursor:pointer',
            'display:flex', 'align-items:center', 'justify-content:center',
            'box-shadow:0 8px 24px rgba(0,0,0,.4), 0 1px 0 rgba(255,255,255,.08) inset',
            'z-index:9990',
            'opacity:0', 'pointer-events:none',
            'transform:translateY(8px)',
            'transition:all .35s cubic-bezier(.16,1,.3,1)',
            'font-family:inherit',
        ].join(';');
        btn.addEventListener('mouseover', () => {
            btn.style.background = 'rgba(30,40,60,0.95)';
            btn.style.borderColor = 'rgba(34,211,238,.5)';
            btn.style.color = 'rgba(34,211,238,1)';
        });
        btn.addEventListener('mouseout', () => {
            btn.style.background = 'rgba(20,25,40,0.9)';
            btn.style.borderColor = 'rgba(255,255,255,.12)';
            btn.style.color = 'rgba(255,255,255,.85)';
        });
        btn.addEventListener('click', () => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
        document.body.appendChild(btn);

        // ── 滚动事件
        let ticking = false;
        function update() {
            const scrollTop  = window.scrollY || document.documentElement.scrollTop;
            const scrollMax  = (document.documentElement.scrollHeight - window.innerHeight) || 1;
            const pct = Math.min(100, Math.max(0, (scrollTop / scrollMax) * 100));
            bar.style.width = pct + '%';
            if (scrollTop > 600) {
                btn.style.opacity = '1';
                btn.style.transform = 'translateY(0)';
                btn.style.pointerEvents = 'auto';
            } else {
                btn.style.opacity = '0';
                btn.style.transform = 'translateY(8px)';
                btn.style.pointerEvents = 'none';
            }
            ticking = false;
        }
        window.addEventListener('scroll', () => {
            if (!ticking) {
                requestAnimationFrame(update);
                ticking = true;
            }
        }, { passive: true });
        update();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
