/* ════════════════════════════════════════════════════════
   footer.js v3 — 全站统一 footer 注入
   Linear/Vercel 风格：紧凑、干净、亮/暗模式支持
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const HTML = `
        <div class="cq-footer">
            <div class="cq-footer-grid">
                <div class="cq-footer-brand">
                    <div class="cq-footer-logo">CampusQuant</div>
                    <div class="cq-footer-tagline">用 AI 帮每位大学生建立正确的财富认知</div>
                    <div class="cq-footer-status">
                        <span class="cq-status-dot"></span>
                        <span>系统运行中 · 全部服务正常</span>
                    </div>
                </div>
                <div class="cq-footer-col">
                    <div class="cq-footer-title">产品</div>
                    <a href="dashboard.html">控制台</a>
                    <a href="trade.html">模拟演练</a>
                    <a href="market.html">市场快讯</a>
                    <a href="analysis.html">个股分析</a>
                    <a href="platforms.html">持仓体检</a>
                </div>
                <div class="cq-footer-col">
                    <div class="cq-footer-title">学习</div>
                    <a href="home.html">学习中心</a>
                    <a href="learn_basics.html">基础财商课程</a>
                    <a href="learn_strategies.html">投资策略锦囊</a>
                    <a href="learn_antifraud.html">防骗指南</a>
                    <a href="resources.html">学习资源库</a>
                </div>
                <div class="cq-footer-col">
                    <div class="cq-footer-title">关于</div>
                    <a href="team.html">团队</a>
                    <a href="community.html">投教社区</a>
                    <a href="javascript:void(0)" onclick="cqAlert && cqAlert('用户协议正在草拟中', '提示')">用户协议</a>
                    <a href="javascript:void(0)" onclick="cqAlert && cqAlert('隐私政策正在草拟中', '提示')">隐私政策</a>
                </div>
            </div>
            <div class="cq-footer-bar">
                <div>© 2026 CampusQuant Team · 校园财商智能分析平台</div>
                <div class="cq-footer-meta">
                    <span>所有交易均为模拟，不连接真实交易所</span>
                    <span class="cq-footer-sep">·</span>
                    <span>仅供大学生投资教育使用</span>
                </div>
            </div>
        </div>
    `;

    const STYLE = `
        footer { position: relative; z-index: 1; }

        .cq-footer {
            margin-top: 48px;
            padding: 36px 32px 20px;
            border-top: 1px solid var(--border, rgba(255,255,255,.09));
            background: transparent;
        }

        /* Light mode */
        [data-theme="light"] .cq-footer {
            border-top-color: rgba(0,0,0,.09);
        }

        .cq-footer-grid {
            display: grid;
            grid-template-columns: 2fr 1fr 1fr 1fr;
            gap: 40px 32px;
            max-width: 1320px;
            margin: 0 auto;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border, rgba(255,255,255,.09));
        }
        [data-theme="light"] .cq-footer-grid {
            border-bottom-color: rgba(0,0,0,.09);
        }

        .cq-footer-brand { max-width: 280px; }

        .cq-footer-logo {
            font-size: 17px;
            font-weight: 800;
            letter-spacing: -0.01em;
            color: var(--text, rgba(255,255,255,.92));
            margin-bottom: 10px;
        }
        [data-theme="light"] .cq-footer-logo { color: rgba(0,0,0,.85); }

        .cq-footer-tagline {
            color: var(--text-sub, rgba(255,255,255,.55));
            font-size: 12px;
            line-height: 1.65;
            margin-bottom: 14px;
        }
        [data-theme="light"] .cq-footer-tagline { color: rgba(0,0,0,.50); }

        .cq-footer-status {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            padding: 5px 12px;
            background: rgba(74,222,128,0.08);
            border: 1px solid rgba(74,222,128,0.20);
            border-radius: 99px;
            font-size: 11px;
            color: rgba(74,222,128,0.90);
            font-family: var(--font-mono, monospace);
        }
        [data-theme="light"] .cq-footer-status {
            background: rgba(22,163,74,0.08);
            border-color: rgba(22,163,74,0.20);
            color: #15803d;
        }

        .cq-status-dot {
            display: inline-block;
            width: 5px; height: 5px;
            border-radius: 50%;
            background: #4ade80;
            flex-shrink: 0;
        }
        [data-theme="light"] .cq-status-dot { background: #16a34a; }

        .cq-footer-col {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .cq-footer-title {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--text-dim, rgba(255,255,255,.40));
            font-weight: 600;
            margin-bottom: 4px;
            font-family: var(--font-mono, monospace);
        }
        [data-theme="light"] .cq-footer-title { color: rgba(0,0,0,.38); }

        .cq-footer-col a {
            color: var(--text-sub, rgba(255,255,255,.55));
            text-decoration: none;
            font-size: 13px;
            transition: color .15s;
        }
        .cq-footer-col a:hover { color: var(--text-1, rgba(255,255,255,.85)); }
        [data-theme="light"] .cq-footer-col a { color: rgba(0,0,0,.52); }
        [data-theme="light"] .cq-footer-col a:hover { color: rgba(0,0,0,.80); }

        .cq-footer-bar {
            max-width: 1320px;
            margin: 0 auto;
            padding-top: 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            font-size: 11px;
            color: var(--text-dim, rgba(255,255,255,.38));
            font-family: var(--font-mono, monospace);
        }
        [data-theme="light"] .cq-footer-bar { color: rgba(0,0,0,.36); }

        .cq-footer-meta {
            display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
        }
        .cq-footer-sep { opacity: .35; }

        @media (max-width: 900px) {
            .cq-footer { padding: 28px 20px 16px; margin-top: 36px; }
            .cq-footer-grid { grid-template-columns: 1fr 1fr; gap: 24px 20px; }
            .cq-footer-brand { grid-column: 1 / -1; max-width: none; }
        }
        @media (max-width: 480px) {
            .cq-footer-grid { grid-template-columns: 1fr; gap: 20px; }
            .cq-footer-bar { font-size: 10px; flex-direction: column; align-items: flex-start; gap: 6px; }
            .cq-footer-meta { gap: 6px; }
        }
    `;

    function init() {
        if (!document.getElementById('cq-footer-style')) {
            const s = document.createElement('style');
            s.id = 'cq-footer-style';
            s.textContent = STYLE;
            document.head.appendChild(s);
        }
        let footerEl = document.querySelector('footer');
        if (footerEl) {
            footerEl.innerHTML = HTML;
        } else {
            footerEl = document.createElement('footer');
            footerEl.innerHTML = HTML;
            const firstScript = document.body.querySelector('script');
            if (firstScript) document.body.insertBefore(footerEl, firstScript);
            else document.body.appendChild(footerEl);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
