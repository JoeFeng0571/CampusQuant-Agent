/* ════════════════════════════════════════════════════════
   magnet-cursor.js — 鼠标磁吸 + 自定义光标环
   - 自定义光标：1 个跟随光环（body）+ 1 个中心点
   - 磁吸效果：[data-magnet] 元素附近会被光标"吸住"
   - 移动设备直接 noop
   - reduced-motion 下 noop
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // 移动端 / 触摸设备 noop
    if (window.matchMedia('(hover: none) and (pointer: coarse)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    // ── 创建自定义光标
    const ring = document.createElement('div');
    ring.id = 'cq-cursor-ring';
    ring.style.cssText = [
        'position:fixed',
        'top:0', 'left:0',
        'width:32px', 'height:32px',
        'border:1.5px solid rgba(0,242,254,.55)',
        'border-radius:50%',
        'pointer-events:none',
        'z-index:99999',
        'transform:translate(-50%,-50%)',
        'transition:width .25s cubic-bezier(.16,1,.3,1), height .25s cubic-bezier(.16,1,.3,1), border-color .2s, background .2s, opacity .25s',
        'mix-blend-mode:difference',
        'opacity:0',
        'will-change:transform, width, height',
    ].join(';');

    const dot = document.createElement('div');
    dot.id = 'cq-cursor-dot';
    dot.style.cssText = [
        'position:fixed',
        'top:0', 'left:0',
        'width:4px', 'height:4px',
        'background:rgba(255,255,255,.85)',
        'border-radius:50%',
        'pointer-events:none',
        'z-index:99999',
        'transform:translate(-50%,-50%)',
        'mix-blend-mode:difference',
        'opacity:0',
        'transition:opacity .25s',
        'will-change:transform',
    ].join(';');

    function mount() {
        document.body.appendChild(ring);
        document.body.appendChild(dot);
    }
    if (document.body) mount();
    else document.addEventListener('DOMContentLoaded', mount);

    let mx = 0, my = 0, rx = 0, ry = 0, dx = 0, dy = 0;
    let visible = false;

    window.addEventListener('mousemove', (e) => {
        mx = e.clientX;
        my = e.clientY;
        if (!visible) {
            visible = true;
            ring.style.opacity = '1';
            dot.style.opacity = '1';
        }
    }, { passive: true });

    window.addEventListener('mouseleave', () => {
        visible = false;
        ring.style.opacity = '0';
        dot.style.opacity = '0';
    });

    // ── 平滑跟随
    function loop() {
        // 光环 lerp（缓动跟随）
        rx += (mx - rx) * 0.18;
        ry += (my - ry) * 0.18;
        // 中心点 lerp 更快
        dx += (mx - dx) * 0.5;
        dy += (my - dy) * 0.5;
        ring.style.transform = `translate(${rx}px,${ry}px) translate(-50%,-50%)`;
        dot.style.transform = `translate(${dx}px,${dy}px) translate(-50%,-50%)`;
        requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);

    // ── hover 交互元素时光环放大
    const HOVER_SELECTOR = 'a, button, [role="button"], input, textarea, select, [data-magnet], .qnav-item, .panel, .res-card, .post-item, .module-card, .topic, [onclick]';

    document.addEventListener('mouseover', (e) => {
        if (e.target.closest(HOVER_SELECTOR)) {
            ring.style.width = '52px';
            ring.style.height = '52px';
            ring.style.borderColor = 'rgba(255,154,86,.7)';
            ring.style.background = 'rgba(255,154,86,.05)';
        }
    }, { capture: true });

    document.addEventListener('mouseout', (e) => {
        if (e.target.closest(HOVER_SELECTOR)) {
            ring.style.width = '32px';
            ring.style.height = '32px';
            ring.style.borderColor = 'rgba(0,242,254,.55)';
            ring.style.background = 'transparent';
        }
    }, { capture: true });

    // ── 隐藏原生光标（仅在 hover 状态）
    document.documentElement.style.cursor = 'none';
    // 但要让所有交互元素显示原生光标后备
    const nativeCursorStyle = document.createElement('style');
    nativeCursorStyle.textContent = `
        html, body, * { cursor: none !important; }
        input[type="text"], input[type="email"], input[type="password"],
        input[type="number"], input[type="search"], textarea {
            cursor: text !important;
        }
    `;
    document.head.appendChild(nativeCursorStyle);

    // ── MAGNET：[data-magnet] 元素被吸住
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

    window.cqCursor = {
        hide: () => { ring.style.display = 'none'; dot.style.display = 'none'; },
        show: () => { ring.style.display = ''; dot.style.display = ''; },
    };
})();
