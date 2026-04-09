/* ════════════════════════════════════════════════════════
   footer.js — 全站统一的多列 footer 注入
   - 自动替换页面原有 <footer> 内容（如果存在）
   - 4 列布局：品牌 / 产品 / 学习 / 法务
   - 渐变边框 + 大字 logo + 社交链接占位
   - 不破坏页面结构，仅替换 footer 内 innerHTML
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
                    <span>⚠ 所有交易均为模拟，不连接真实交易所</span>
                    <span class="cq-footer-sep">·</span>
                    <span>仅供大学生投资教育使用</span>
                </div>
            </div>
        </div>
    `;

    const STYLE = `
        footer { position: relative; z-index: 1; }
        .cq-footer {
            margin-top: 80px;
            padding: 56px 32px 32px;
            background:
                linear-gradient(180deg, transparent, rgba(8,12,22,.55) 30%, rgba(8,12,22,.85) 100%),
                linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.04));
            border-top: 1px solid rgba(255,255,255,0.06);
            position: relative;
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
        }
        .cq-footer::before {
            content:'';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 1px;
            background: linear-gradient(90deg,
                transparent,
                rgba(79,172,254,.4),
                rgba(162,155,254,.3),
                rgba(255,107,157,.4),
                transparent);
        }
        .cq-footer-grid {
            display: grid;
            grid-template-columns: 2fr 1fr 1fr 1fr;
            gap: 48px;
            max-width: 1320px;
            margin: 0 auto;
            padding-bottom: 40px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .cq-footer-brand { max-width: 320px; }
        .cq-footer-logo {
            font-family: var(--font-display, inherit);
            font-size: 24px;
            font-weight: 800;
            letter-spacing: -0.02em;
            background: linear-gradient(90deg, #4facfe, #00f2fe);
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 12px;
        }
        .cq-footer-tagline {
            color: var(--text-2, rgba(255,255,255,0.65));
            font-size: 13px;
            line-height: 1.7;
            margin-bottom: 18px;
        }
        .cq-footer-status {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 7px 14px;
            background: rgba(85,239,196,0.08);
            border: 1px solid rgba(85,239,196,0.2);
            border-radius: 999px;
            font-size: 11px;
            color: rgba(85,239,196,0.95);
            font-family: var(--font-mono, monospace);
            font-weight: 600;
        }
        .cq-status-dot {
            display: inline-block;
            width: 6px; height: 6px;
            border-radius: 50%;
            background: #5eead4;
            box-shadow: 0 0 8px #5eead4;
            animation: cq-pulse 2s ease-in-out infinite;
        }
        @keyframes cq-pulse {
            0%,100% { opacity: 1; transform: scale(1); }
            50%     { opacity: .4; transform: scale(.85); }
        }
        .cq-footer-col {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .cq-footer-title {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-3, rgba(255,255,255,0.45));
            font-weight: 700;
            margin-bottom: 6px;
            font-family: var(--font-mono, monospace);
        }
        .cq-footer-col a {
            color: var(--text-2, rgba(255,255,255,0.75));
            text-decoration: none;
            font-size: 13px;
            transition: color .2s, transform .2s;
            display: inline-block;
        }
        .cq-footer-col a:hover {
            color: #00f2fe;
            transform: translateX(3px);
        }
        .cq-footer-bar {
            max-width: 1320px;
            margin: 0 auto;
            padding-top: 28px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 14px;
            font-size: 11px;
            color: var(--text-3, rgba(255,255,255,0.4));
            font-family: var(--font-mono, monospace);
        }
        .cq-footer-meta {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        .cq-footer-sep { opacity: .35; }

        @media (max-width: 900px) {
            .cq-footer { padding: 40px 20px 24px; margin-top: 56px; }
            .cq-footer-grid { grid-template-columns: 1fr 1fr; gap: 32px 24px; }
            .cq-footer-brand { grid-column: 1 / -1; max-width: none; }
        }
        @media (max-width: 480px) {
            .cq-footer-grid { grid-template-columns: 1fr; gap: 28px; }
            .cq-footer-bar { font-size: 10px; flex-direction: column; align-items: flex-start; }
        }
    `;

    function init() {
        // 注入 CSS
        if (!document.getElementById('cq-footer-style')) {
            const s = document.createElement('style');
            s.id = 'cq-footer-style';
            s.textContent = STYLE;
            document.head.appendChild(s);
        }

        // 替换或新增 footer
        let footerEl = document.querySelector('footer');
        if (footerEl) {
            footerEl.innerHTML = HTML;
        } else {
            // body 末尾新增（在 script 标签前）
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
