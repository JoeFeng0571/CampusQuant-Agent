/* ════════════════════════════════════════════════════════
   aurora.js — 极光背景（深空感）
   8 个超大模糊渐变光团，30s 一周期缓慢漂移
   z-index:-2 在 pixel-sand 之下，构成两层视觉深度
   - 纯 DOM + CSS transform，性能比 Canvas 更轻
   - reduced-motion 自动降级为静态
   - 8 色调色板与 tokens.css 一致
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (document.getElementById('aurora-stage')) return; // 防重复

    const REDUCE = window.matchMedia
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // 文字页 quiet 模式：用 4 个光团 + 低透明度
    const BG_MODE = (document.body && document.body.dataset.bgMode) ||
                    (document.documentElement && document.documentElement.dataset.bgMode) || 'ambient';
    // 移动端 quiet 模式（降低强度但保留极光氛围）
    const IS_MOBILE = window.matchMedia('(max-width: 768px)').matches;
    const EFFECTIVE_MODE = IS_MOBILE && BG_MODE === 'ambient' ? 'quiet' : BG_MODE;

    // 8 个光团配置：颜色 / 起始位置 / 大小 / 漂移路径
    const ORBS_FULL = [
        { color: '45,212,191',  size: 760, top:'-15%', left:'-10%',  driftX: 18, driftY: 12, dur: 32 },  // teal-400
        { color: '34,211,238',  size: 620, top:'5%',   left: '60%',  driftX:-14, driftY: 16, dur: 30 },  // cyan-400
        { color: '56,189,248',  size: 700, top:'40%',  left:'-15%',  driftX: 16, driftY:-12, dur: 36 },  // sky-400
        { color: '20,184,166',  size: 580, top:'55%',  left: '70%',  driftX:-18, driftY:-10, dur: 28 },  // teal-500
        { color: '94,234,212',  size: 540, top:'75%',  left: '20%',  driftX: 12, driftY:-16, dur: 34 },  // teal-300
        { color: '251,191,36',  size: 600, top:'-10%', left: '35%',  driftX:-10, driftY: 18, dur: 38 },  // amber-400 (warm accent)
        { color: '248,113,113', size: 520, top:'80%',  left:'-5%',   driftX: 20, driftY:-12, dur: 30 },  // red-400 (warm accent)
        { color: '52,211,153',  size: 480, top:'25%',  left: '85%',  driftX:-16, driftY: 14, dur: 33 },  // emerald-400
    ];

    // quiet 模式：减半光团 + 更低不透明度（文字页用）
    const ORBS_QUIET = ORBS_FULL.filter((_, i) => i % 2 === 0).map(o => ({
        ...o,
        size: o.size * 0.85,
        // 颜色不变，下面 opacity 通过 stage 整体调
    }));
    const ORBS = EFFECTIVE_MODE === 'quiet' || EFFECTIVE_MODE === 'minimal' ? ORBS_QUIET : ORBS_FULL;
    const STAGE_OPACITY = EFFECTIVE_MODE === 'minimal' ? 0.25 :
                          EFFECTIVE_MODE === 'quiet'   ? 0.5  : 1;
    if (EFFECTIVE_MODE === 'off') return;

    // 容器（fixed 全屏）
    const stage = document.createElement('div');
    stage.id = 'aurora-stage';
    stage.style.cssText = [
        'position:fixed',
        'inset:0',
        'pointer-events:none',
        'z-index:-3',                  // 极光在最底（grid-dots -2，pixel-sand -1）
        'overflow:hidden',
        'opacity:0',
        'transition:opacity 1.6s ease',
        // 内置一层非常微弱的暗色蒙版，保证内容可读
        'background:radial-gradient(ellipse at 50% 60%,transparent,rgba(10,13,23,.35) 70%)',
    ].join(';');
    // 应用 quiet/minimal 整体透明度
    if (STAGE_OPACITY < 1) {
        stage.dataset.targetOpacity = String(STAGE_OPACITY);
    }

    // CSS 注入（用 ::before 不行，得真元素）
    const styleTag = document.createElement('style');
    styleTag.textContent = `
        .aurora-orb {
            position: absolute;
            border-radius: 50%;
            filter: blur(70px);
            mix-blend-mode: screen;
            will-change: transform;
            opacity: 0.55;
        }
        @keyframes aurora-drift-1 {
            0%, 100% { transform: translate3d(0,0,0)               scale(1); }
            25%      { transform: translate3d(var(--dx),var(--dy),0) scale(1.08); }
            50%      { transform: translate3d(calc(var(--dx)*-.6),var(--dy),0) scale(.94); }
            75%      { transform: translate3d(calc(var(--dx)*.4),calc(var(--dy)*-.7),0) scale(1.04); }
        }
        .aurora-orb {
            animation: aurora-drift-1 var(--dur) ease-in-out infinite;
        }
        @media (prefers-reduced-motion: reduce) {
            .aurora-orb { animation: none !important; }
        }
    `;
    document.head.appendChild(styleTag);

    // 创建光团
    ORBS.forEach((cfg, i) => {
        const orb = document.createElement('div');
        orb.className = 'aurora-orb';
        orb.style.cssText = [
            `width:${cfg.size}px`,
            `height:${cfg.size}px`,
            `top:${cfg.top}`,
            `left:${cfg.left}`,
            `background:radial-gradient(circle,rgba(${cfg.color},.55) 0%,rgba(${cfg.color},.18) 35%,transparent 70%)`,
            `--dx:${cfg.driftX}vw`,
            `--dy:${cfg.driftY}vh`,
            `--dur:${cfg.dur}s`,
            `animation-delay:-${i * 3.5}s`,    // 错峰
        ].join(';');
        stage.appendChild(orb);
    });

    function mount() {
        document.body.appendChild(stage);
        requestAnimationFrame(() => {
            stage.style.opacity = stage.dataset.targetOpacity || '1';
        });
    }
    if (document.body) mount();
    else document.addEventListener('DOMContentLoaded', mount);

    // 暴露 API
    window.cqAurora = {
        stop: () => stage.remove(),
        // 可调强度（0-1）
        setIntensity: (v) => {
            stage.querySelectorAll('.aurora-orb').forEach(o => {
                o.style.opacity = String(Math.max(0, Math.min(1, v * 0.55)) / 0.55 * 0.55);
            });
        },
    };
})();
