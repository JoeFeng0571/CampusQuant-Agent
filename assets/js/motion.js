/* ════════════════════════════════════════════════════════
   motion.js — scroll reveal + count-up + mouse glow
   零依赖，纯原生 IntersectionObserver
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // ══════════ SCROLL REVEAL ══════════
    // 用法: <div class="reveal">  /  .reveal-left / .reveal-right / .reveal-scale
    //       data-delay="1..5" 错峰
    function initReveal() {
        const els = document.querySelectorAll('.reveal, .reveal-left, .reveal-right, .reveal-scale');
        if (!els.length || !('IntersectionObserver' in window)) {
            // 不支持 IO 的旧浏览器：直接显示
            els.forEach(el => el.classList.add('in'));
            return;
        }
        const io = new IntersectionObserver((entries) => {
            entries.forEach(e => {
                if (e.isIntersecting) {
                    e.target.classList.add('in');
                    io.unobserve(e.target);
                }
            });
        }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
        els.forEach(el => io.observe(el));
    }

    // ══════════ COUNT-UP ══════════
    // 用法: <span class="num-roll" data-count="123456" data-decimals="0" data-prefix="¥" data-suffix="">0</span>
    // 调用: cqAnimateNumber(el, fromVal, toVal, durMs)
    window.cqAnimateNumber = function (el, from, to, dur) {
        if (!el) return;
        dur = dur || 1200;
        const decimals = parseInt(el.dataset.decimals || '0', 10);
        const prefix = el.dataset.prefix || '';
        const suffix = el.dataset.suffix || '';
        const start = performance.now();
        const ease = t => 1 - Math.pow(1 - t, 3);
        function step(now) {
            const p = Math.min((now - start) / dur, 1);
            const v = from + (to - from) * ease(p);
            el.textContent = prefix + v.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + suffix;
            if (p < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
        // 记录当前值，方便 cqUpdateNumber 下次从这里滚
        el.dataset.currentValue = String(to);
    };

    // 智能更新：从上次值滚到新值，并按方向 flash
    window.cqUpdateNumber = function (el, to, dur) {
        if (!el) return;
        const from = parseFloat(el.dataset.currentValue || '0') || 0;
        if (Math.abs(from - to) < 0.001) return;  // 没变化不动
        cqAnimateNumber(el, from, to, dur || 700);
        // flash by direction
        el.classList.remove('num-flash-up', 'num-flash-down');
        // 强制重新触发 animation
        void el.offsetWidth;
        if (to > from) el.classList.add('num-flash-up');
        else if (to < from) el.classList.add('num-flash-down');
    };

    function initCountUp() {
        const els = document.querySelectorAll('.num-roll[data-count]');
        if (!els.length || !('IntersectionObserver' in window)) {
            els.forEach(el => {
                const to = parseFloat(el.dataset.count) || 0;
                cqAnimateNumber(el, 0, to);
            });
            return;
        }
        const io = new IntersectionObserver((entries) => {
            entries.forEach(e => {
                if (e.isIntersecting) {
                    const to = parseFloat(e.target.dataset.count) || 0;
                    cqAnimateNumber(e.target, 0, to);
                    io.unobserve(e.target);
                }
            });
        }, { threshold: 0.4 });
        els.forEach(el => io.observe(el));
    }

    // ══════════ MOUSE GLOW ══════════
    // 给 .mouse-glow 元素加鼠标跟随
    function initMouseGlow() {
        document.querySelectorAll('.mouse-glow').forEach(el => {
            el.addEventListener('mousemove', e => {
                const r = el.getBoundingClientRect();
                el.style.setProperty('--mx', (e.clientX - r.left) + 'px');
                el.style.setProperty('--my', (e.clientY - r.top) + 'px');
            });
        });
    }

    // ══════════ PARALLAX TILT (轻量自实现，~30 行) ══════════
    // 用法: <div class="tilt" data-tilt-max="8">...</div>
    function initTilt() {
        document.querySelectorAll('.tilt').forEach(el => {
            const max = parseFloat(el.dataset.tiltMax || '8');
            el.style.transition = 'transform .3s cubic-bezier(.16,1,.3,1)';
            el.style.transformStyle = 'preserve-3d';
            el.addEventListener('mousemove', e => {
                const r = el.getBoundingClientRect();
                const cx = r.width / 2, cy = r.height / 2;
                const dx = (e.clientX - r.left - cx) / cx;
                const dy = (e.clientY - r.top - cy) / cy;
                el.style.transform = `perspective(900px) rotateX(${(-dy*max).toFixed(2)}deg) rotateY(${(dx*max).toFixed(2)}deg) translateZ(0)`;
            });
            el.addEventListener('mouseleave', () => {
                el.style.transform = 'perspective(900px) rotateX(0) rotateY(0)';
            });
        });
    }

    // ══════════ PAGE ENTER ══════════
    function initPageEnter() {
        document.body.classList.add('page-enter');
    }

    // ══════════ INIT ══════════
    function init() {
        initPageEnter();
        initReveal();
        initCountUp();
        initMouseGlow();
        initTilt();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
