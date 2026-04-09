/* ════════════════════════════════════════════════════════
   grid-dots.js — Linear 风动态点阵背景
   - 等间距点阵（30-40px 间隔）
   - 每个点随机间隔 opacity 闪烁
   - 部分点带 cyan/violet 高亮
   - 鼠标附近的点会高亮（subtle parallax）
   - z-index:-2 在极光之上、内容之下
   - reduced-motion 下静态显示
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (document.getElementById('grid-dots-stage')) return;

    const REDUCE = window.matchMedia
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // 文字页 quiet 模式：放大间距 + 减少高亮 + 关脉冲
    const BG_MODE = (document.body && document.body.dataset.bgMode) ||
                    (document.documentElement && document.documentElement.dataset.bgMode) || 'ambient';
    if (BG_MODE === 'off' || BG_MODE === 'minimal') return;

    const QUIET = BG_MODE === 'quiet';
    const GAP = QUIET ? 56 : 36;
    const DOT_SIZE = 1.5;
    const HIGHLIGHT_RATE = QUIET ? 0.04 : 0.08;
    const PULSE_PROB = QUIET ? 0.0008 : 0.003;
    const PULSE_DUR = 1800;
    const MOUSE_RADIUS = QUIET ? 100 : 140;
    const STAGE_OPACITY = QUIET ? 0.55 : 1;

    // ── canvas
    const canvas = document.createElement('canvas');
    canvas.id = 'grid-dots-stage';
    canvas.style.cssText = [
        'position:fixed',
        'inset:0',
        'width:100%',
        'height:100%',
        'pointer-events:none',
        'z-index:-2',          // 极光在 -3 之下，但 aurora 现在是 -2，需要调
        'opacity:0',
        'transition:opacity 1.6s ease',
    ].join(';');

    function mount() {
        document.body.appendChild(canvas);
        requestAnimationFrame(() => { canvas.style.opacity = String(STAGE_OPACITY); });
    }
    if (document.body) mount();
    else document.addEventListener('DOMContentLoaded', mount);

    const ctx = canvas.getContext('2d', { alpha: true });
    let W = 0, H = 0, dpr = 1;
    let dots = [];        // 所有点 [{x,y, baseAlpha, highlight, color, pulseStart}]
    let mouseX = -9999, mouseY = -9999;

    // 高亮点的 5 色（与 tokens.css 同步）
    const HIGHLIGHT_COLORS = [
        '79,172,254',   // primary
        '0,242,254',    // secondary
        '162,155,254',  // accent
        '240,147,251',  // pink
        '255,154,86',   // warm
    ];

    function buildDots() {
        dots = [];
        const cols = Math.ceil(W / GAP) + 1;
        const rows = Math.ceil(H / GAP) + 1;
        for (let r = 0; r < rows; r++) {
            for (let c = 0; c < cols; c++) {
                const isHighlight = Math.random() < HIGHLIGHT_RATE;
                dots.push({
                    x: c * GAP,
                    y: r * GAP,
                    baseAlpha: isHighlight ? 0.18 : 0.06,
                    highlight: isHighlight,
                    color: isHighlight
                        ? HIGHLIGHT_COLORS[(Math.random() * HIGHLIGHT_COLORS.length) | 0]
                        : '255,255,255',
                    pulseStart: 0,
                });
            }
        }
    }

    function resize() {
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        W = window.innerWidth;
        H = window.innerHeight;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        buildDots();
    }
    resize();
    window.addEventListener('resize', resize);

    if (!REDUCE) {
        window.addEventListener('mousemove', (e) => {
            mouseX = e.clientX;
            mouseY = e.clientY;
        }, { passive: true });
        // 离开窗口
        window.addEventListener('mouseleave', () => {
            mouseX = mouseY = -9999;
        });
    }

    let running = true;
    function tick(now) {
        if (!running) return;
        ctx.clearRect(0, 0, W, H);

        for (let i = 0; i < dots.length; i++) {
            const d = dots[i];

            // 概率开始脉冲
            if (d.pulseStart === 0 && Math.random() < PULSE_PROB) {
                d.pulseStart = now;
            }

            let alpha = d.baseAlpha;
            let size = DOT_SIZE;

            // 脉冲计算
            if (d.pulseStart > 0) {
                const t = (now - d.pulseStart) / PULSE_DUR;
                if (t >= 1) {
                    d.pulseStart = 0;
                } else {
                    // ease bell curve（先涨后落）
                    const bell = Math.sin(t * Math.PI);
                    alpha = d.baseAlpha + bell * (d.highlight ? 0.55 : 0.30);
                    size = DOT_SIZE + bell * (d.highlight ? 1.5 : 0.8);
                }
            }

            // 鼠标接近高亮
            if (mouseX > -1000) {
                const dx = d.x - mouseX, dy = d.y - mouseY;
                const dist = Math.sqrt(dx*dx + dy*dy);
                if (dist < MOUSE_RADIUS) {
                    const t = 1 - dist / MOUSE_RADIUS;
                    alpha = Math.max(alpha, d.baseAlpha + t * 0.35);
                    size = Math.max(size, DOT_SIZE + t * 1.2);
                }
            }

            ctx.fillStyle = `rgba(${d.color},${alpha.toFixed(3)})`;
            ctx.beginPath();
            ctx.arc(d.x, d.y, size, 0, Math.PI * 2);
            ctx.fill();
        }

        requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);

    // 减动效用户：只画一帧静态
    if (REDUCE) {
        running = false;
        // 单帧渲染已在第一次 tick 完成，停止循环即可
    }

    // Tab 不可见暂停
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            running = false;
        } else if (!running && !REDUCE) {
            running = true;
            requestAnimationFrame(tick);
        }
    });

    window.cqGridDots = {
        stop: () => { running = false; canvas.style.opacity = '0'; },
        start: () => {
            canvas.style.opacity = '1';
            if (!running) {
                running = true;
                requestAnimationFrame(tick);
            }
        },
    };
})();
