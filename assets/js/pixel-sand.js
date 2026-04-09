/* ════════════════════════════════════════════════════════
   pixel-sand.js — 像素流沙背景
   零依赖 Canvas 粒子系统，固定全屏背景，z-index:-1
   功能：
     - 2-3px 方块粒子下落 + 正弦横向漂移
     - 三层视差（远/中/近，速度递增）
     - 颜色从设计 token 取（cyan/violet/pink/warm/mint）
     - Tab 不可见时暂停（visibilitychange）
     - prefers-reduced-motion 友好（直接不渲染）
     - 自动初始化（无需调用）
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // reduced motion 用户：什么都不做
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }
    // 文字页 quiet/minimal/off 模式：直接不显示流沙（容易让文字眼花）
    const BG_MODE = (document.body && document.body.dataset.bgMode) ||
                    (document.documentElement && document.documentElement.dataset.bgMode) || 'ambient';
    if (BG_MODE !== 'ambient') return;

    // 调色板（与 tokens.css 同步）
    const PALETTE = [
        { c: '79,172,254', a: 0.55 },  // primary cyan
        { c: '0,242,254',  a: 0.50 },  // secondary
        { c: '162,155,254', a: 0.55 }, // accent violet
        { c: '183,148,244', a: 0.50 }, // violet
        { c: '240,147,251', a: 0.45 }, // pink
        { c: '255,154,86',  a: 0.45 }, // warm orange
        { c: '255,107,157', a: 0.45 }, // warm pink
        { c: '94,234,212',  a: 0.40 }, // mint
        { c: '255,216,107', a: 0.40 }, // gold
    ];

    // 三个景深层（远到近）
    const LAYERS = [
        { count: 35, sizeMin: 1, sizeMax: 2, speedMin: 0.15, speedMax: 0.35, alpha: 0.45 },
        { count: 30, sizeMin: 2, sizeMax: 3, speedMin: 0.35, speedMax: 0.6,  alpha: 0.7 },
        { count: 18, sizeMin: 2, sizeMax: 4, speedMin: 0.55, speedMax: 0.95, alpha: 0.95 },
    ];

    // ── 创建 canvas
    const canvas = document.createElement('canvas');
    canvas.id = 'pixel-sand-canvas';
    canvas.style.cssText = [
        'position:fixed',
        'inset:0',
        'width:100%',
        'height:100%',
        'pointer-events:none',
        'z-index:-1',
        'opacity:0',
        'transition:opacity 1.2s ease',
    ].join(';');

    function mount() {
        document.body.appendChild(canvas);
        // 淡入显示
        requestAnimationFrame(() => { canvas.style.opacity = '1'; });
    }
    if (document.body) mount();
    else document.addEventListener('DOMContentLoaded', mount);

    const ctx = canvas.getContext('2d', { alpha: true });
    let W = 0, H = 0, dpr = 1;

    // 像素感关键：禁用插值
    function resize() {
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        W = window.innerWidth;
        H = window.innerHeight;
        canvas.width  = W * dpr;
        canvas.height = H * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.imageSmoothingEnabled = false;
    }
    resize();
    window.addEventListener('resize', resize);

    // ── 粒子工厂
    function makeParticle(layer, fromTop) {
        const color = PALETTE[(Math.random() * PALETTE.length) | 0];
        return {
            x:  Math.random() * W,
            y:  fromTop ? -10 - Math.random() * H * 0.3 : Math.random() * H,
            sz: (layer.sizeMin + Math.random() * (layer.sizeMax - layer.sizeMin)) | 0,
            sp: layer.speedMin + Math.random() * (layer.speedMax - layer.speedMin),
            // 横向漂移用正弦：相位 + 频率
            phase: Math.random() * Math.PI * 2,
            freq:  0.0008 + Math.random() * 0.0014,
            amp:   8 + Math.random() * 18,
            // 颜色
            color: `rgba(${color.c},${(color.a * layer.alpha).toFixed(3)})`,
            // 偶尔有"高亮"星点（更亮）
            glow: Math.random() < 0.08,
        };
    }

    // 初始化所有粒子（按层归类）
    const particles = [];
    LAYERS.forEach(layer => {
        for (let i = 0; i < layer.count; i++) {
            particles.push({ p: makeParticle(layer, false), layer });
        }
    });

    // ── 主循环
    let running = true;
    let lastTime = performance.now();
    function tick(now) {
        if (!running) return;
        const dt = Math.min(now - lastTime, 50); // clamp to avoid huge jumps
        lastTime = now;

        // 半透明清屏（让粒子有微弱拖尾）
        ctx.clearRect(0, 0, W, H);

        for (let i = 0; i < particles.length; i++) {
            const item = particles[i];
            const p = item.p;
            // 下落
            p.y += p.sp * dt * 0.06;
            // 横向漂移
            const drift = Math.sin(now * p.freq + p.phase) * p.amp * 0.02;
            const drawX = p.x + drift;

            // 出底重生
            if (p.y > H + 4) {
                particles[i] = { p: makeParticle(item.layer, true), layer: item.layer };
                continue;
            }

            // 绘制方块
            ctx.fillStyle = p.color;
            ctx.fillRect(drawX | 0, p.y | 0, p.sz, p.sz);

            // 高亮星点：再画一个白色亮芯
            if (p.glow) {
                ctx.fillStyle = 'rgba(255,255,255,0.55)';
                ctx.fillRect((drawX | 0), (p.y | 0), 1, 1);
            }
        }

        requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    // ── Tab 不可见时暂停（省 CPU/电量）
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            running = false;
        } else if (!running) {
            running = true;
            lastTime = performance.now();
            requestAnimationFrame(tick);
        }
    });

    // ── 暴露 API（可选：手动开关）
    window.cqPixelSand = {
        stop: () => { running = false; canvas.style.opacity = '0'; },
        start: () => {
            canvas.style.opacity = '1';
            if (!running) {
                running = true;
                lastTime = performance.now();
                requestAnimationFrame(tick);
            }
        },
    };
})();
