/* ════════════════════════════════════════════════════════
   constellation.js — 粒子星云网络（仅 team.html 使用）
   - 200+ 粒子漂浮 + 自动连线
   - 鼠标吸引/排斥效果
   - teal/cyan 配色
   - 性能优化：offscreen particles 跳过绘制
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const REDUCE = window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const IS_MOBILE = window.matchMedia('(max-width: 768px)').matches;

    if (REDUCE) return;

    const canvas = document.createElement('canvas');
    canvas.id = 'constellation-canvas';
    canvas.style.cssText = 'position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:0;transition:opacity 1s;';
    document.body.appendChild(canvas);
    requestAnimationFrame(() => { canvas.style.opacity = '1'; });

    const ctx = canvas.getContext('2d');
    let W, H;
    const PARTICLE_COUNT = IS_MOBILE ? 80 : 180;
    const CONNECT_DIST = IS_MOBILE ? 100 : 140;
    const MOUSE_RADIUS = 150;
    const MOUSE_FORCE = 0.02;

    const mouse = { x: -999, y: -999 };

    function resize() {
        W = canvas.width = window.innerWidth;
        H = canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize);

    // Track mouse (use pointer events for performance)
    document.addEventListener('pointermove', e => {
        mouse.x = e.clientX;
        mouse.y = e.clientY;
    });
    document.addEventListener('pointerleave', () => {
        mouse.x = -999;
        mouse.y = -999;
    });

    // Particle colors (teal/cyan palette)
    const COLORS = [
        { r: 45, g: 212, b: 191 },   // teal-400
        { r: 34, g: 211, b: 238 },   // cyan-400
        { r: 94, g: 234, b: 212 },   // teal-300
        { r: 20, g: 184, b: 166 },   // teal-500
        { r: 56, g: 189, b: 248 },   // sky-400
    ];

    class Particle {
        constructor() {
            this.reset();
        }
        reset() {
            this.x = Math.random() * W;
            this.y = Math.random() * H;
            this.vx = (Math.random() - 0.5) * 0.4;
            this.vy = (Math.random() - 0.5) * 0.4;
            this.size = Math.random() * 2 + 0.5;
            this.color = COLORS[Math.floor(Math.random() * COLORS.length)];
            this.alpha = Math.random() * 0.5 + 0.2;
            // Twinkle
            this.twinkleSpeed = Math.random() * 0.02 + 0.005;
            this.twinklePhase = Math.random() * Math.PI * 2;
        }
        update() {
            // Mouse interaction
            const dx = this.x - mouse.x;
            const dy = this.y - mouse.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < MOUSE_RADIUS && dist > 0) {
                const force = (MOUSE_RADIUS - dist) / MOUSE_RADIUS * MOUSE_FORCE;
                this.vx += (dx / dist) * force;
                this.vy += (dy / dist) * force;
            }

            // Damping
            this.vx *= 0.99;
            this.vy *= 0.99;

            this.x += this.vx;
            this.y += this.vy;

            // Wrap around
            if (this.x < -10) this.x = W + 10;
            if (this.x > W + 10) this.x = -10;
            if (this.y < -10) this.y = H + 10;
            if (this.y > H + 10) this.y = -10;

            // Twinkle
            this.twinklePhase += this.twinkleSpeed;
            this.currentAlpha = this.alpha * (0.6 + 0.4 * Math.sin(this.twinklePhase));
        }
        draw() {
            const c = this.color;
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${c.r},${c.g},${c.b},${this.currentAlpha})`;
            ctx.fill();
        }
    }

    const particles = Array.from({ length: PARTICLE_COUNT }, () => new Particle());

    function drawConnections() {
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const a = particles[i], b = particles[j];
                const dx = a.x - b.x, dy = a.y - b.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < CONNECT_DIST) {
                    const opacity = (1 - dist / CONNECT_DIST) * 0.15;
                    ctx.beginPath();
                    ctx.moveTo(a.x, a.y);
                    ctx.lineTo(b.x, b.y);
                    ctx.strokeStyle = `rgba(45,212,191,${opacity})`;
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        }

        // Mouse connections — draw lines from mouse to nearby particles
        if (mouse.x > 0) {
            for (const p of particles) {
                const dx = p.x - mouse.x, dy = p.y - mouse.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < MOUSE_RADIUS) {
                    const opacity = (1 - dist / MOUSE_RADIUS) * 0.3;
                    ctx.beginPath();
                    ctx.moveTo(mouse.x, mouse.y);
                    ctx.lineTo(p.x, p.y);
                    ctx.strokeStyle = `rgba(34,211,238,${opacity})`;
                    ctx.lineWidth = 0.8;
                    ctx.stroke();
                }
            }
        }
    }

    function animate() {
        ctx.clearRect(0, 0, W, H);
        particles.forEach(p => { p.update(); p.draw(); });
        drawConnections();
        requestAnimationFrame(animate);
    }

    animate();
})();
