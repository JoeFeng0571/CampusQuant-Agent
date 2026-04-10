/* ════════════════════════════════════════════════════════
   command-palette.js — Linear / Raycast 同款 Cmd+K 命令面板
   - Cmd+K (Mac) / Ctrl+K (Win) 唤起
   - 全站快速跳转 + 命令搜索
   - 模糊匹配 + 键盘导航 (↑↓ Enter Esc)
   - 自动注入 CSS
   ════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    if (window.cqCommandPalette) return;

    // 命令清单（页面跳转 + 操作）
    const COMMANDS = [
        { id:'nav-dashboard', label:'控制台', icon:'layout-dashboard', href:'dashboard.html', group:'页面', kw:'home dash 首页' },
        { id:'nav-trade',     label:'模拟演练 / 交易', icon:'line-chart', href:'trade.html', group:'页面', kw:'trade buy sell 买卖 委托' },
        { id:'nav-market',    label:'市场快讯',  icon:'newspaper', href:'market.html', group:'页面', kw:'market news 行情 ticker' },
        { id:'nav-analysis',  label:'个股分析',  icon:'search-code', href:'analysis.html', group:'页面', kw:'analysis ai 研报 deep' },
        { id:'nav-platforms', label:'持仓体检',  icon:'stethoscope', href:'platforms.html', group:'页面', kw:'health check 体检 仓位' },
        { id:'nav-community', label:'投教社区',  icon:'users-round', href:'community.html', group:'页面', kw:'community post forum 讨论' },
        { id:'nav-team',      label:'关于我们',  icon:'info', href:'team.html', group:'页面', kw:'about team 团队' },
        { id:'nav-home',      label:'学习中心',  icon:'book-open', href:'home.html', group:'学习', kw:'learn study study center' },
        { id:'nav-resources', label:'学习资源库',icon:'library', href:'resources.html', group:'学习', kw:'resources books 书' },
        { id:'nav-basics',    label:'基础财商课程', icon:'graduation-cap', href:'learn_basics.html', group:'学习', kw:'basics fundamentals 基础' },
        { id:'nav-strategies',label:'投资策略锦囊', icon:'lightbulb', href:'learn_strategies.html', group:'学习', kw:'strategies tips 策略' },
        { id:'nav-antifraud', label:'防骗指南',     icon:'shield-check', href:'learn_antifraud.html', group:'学习', kw:'antifraud safety 防骗 安全' },
        { id:'nav-auth',      label:'登录 / 注册',  icon:'user', href:'auth.html', group:'账户', kw:'login signup register' },
        { id:'act-logout',    label:'退出登录', icon:'log-out', group:'账户', kw:'logout signout',
          run: () => { if (confirm('确定退出？')) { localStorage.removeItem('cq_token'); localStorage.removeItem('cq_username'); location.reload(); } } },
        { id:'act-theme',     label:'切换主题（即将上线）', icon:'palette', group:'设置', kw:'theme dark light',
          run: () => cqToast && cqToast('主题切换功能即将上线', 'info') },
    ];

    // CSS
    const style = document.createElement('style');
    style.textContent = `
        .cq-cmd-backdrop {
            position: fixed; inset: 0; z-index: 9998;
            background: rgba(5,8,16,.7);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            opacity: 0;
            pointer-events: none;            /* 关闭时不拦截点击 */
            transition: opacity .3s ease;
            display: flex;
            align-items: flex-start;
            justify-content: center;
            padding-top: 14vh;
        }
        .cq-cmd-backdrop.show {
            opacity: 1;
            pointer-events: auto;
        }
        .cq-cmd-panel {
            width: min(640px, 92vw);
            max-height: 70vh;
            background: linear-gradient(180deg, rgba(20,25,40,0.96), rgba(15,20,35,0.96));
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 18px;
            backdrop-filter: blur(28px) saturate(150%);
            -webkit-backdrop-filter: blur(28px) saturate(150%);
            box-shadow:
                0 1px 0 rgba(255,255,255,0.08) inset,
                0 1px 2px rgba(0,0,0,0.3),
                0 24px 56px rgba(0,0,0,0.5),
                0 48px 96px rgba(0,0,0,0.4);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            transform: scale(.96) translateY(-12px);
            opacity: 0;
            transition: transform .35s cubic-bezier(.16,1,.3,1), opacity .3s;
        }
        .cq-cmd-backdrop.show .cq-cmd-panel { transform: scale(1) translateY(0); opacity: 1; }
        .cq-cmd-search {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 18px 22px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .cq-cmd-search-icon {
            width: 18px; height: 18px;
            color: rgba(255,255,255,0.45);
            flex-shrink: 0;
        }
        .cq-cmd-input {
            flex: 1;
            background: transparent;
            border: none;
            outline: none;
            color: #fff;
            font-size: 16px;
            font-family: var(--font-sans, inherit);
        }
        .cq-cmd-input::placeholder { color: rgba(255,255,255,0.35); }
        .cq-cmd-kbd {
            font-family: var(--font-mono, monospace);
            font-size: 11px;
            padding: 3px 7px;
            border-radius: 5px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.12);
            color: rgba(255,255,255,0.55);
        }
        .cq-cmd-list {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
            scrollbar-width: thin;
        }
        .cq-cmd-list::-webkit-scrollbar { width: 6px; }
        .cq-cmd-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,.1); border-radius: 3px; }
        .cq-cmd-group {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: rgba(255,255,255,0.35);
            padding: 12px 14px 6px;
            font-weight: 600;
        }
        .cq-cmd-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 14px;
            border-radius: 10px;
            cursor: pointer;
            color: rgba(255,255,255,0.87);
            font-size: 14px;
            transition: background .12s, color .12s;
        }
        .cq-cmd-item.sel {
            background: linear-gradient(90deg, rgba(45,212,191,.18), rgba(45,212,191,.08));
            color: #fff;
        }
        .cq-cmd-item.sel .cq-cmd-icon { color: #22d3ee; }
        .cq-cmd-item:hover { background: rgba(255,255,255,0.05); }
        .cq-cmd-icon {
            width: 18px; height: 18px;
            color: rgba(255,255,255,0.5);
            flex-shrink: 0;
            transition: color .12s;
        }
        .cq-cmd-icon svg { width: 18px; height: 18px; }
        .cq-cmd-label { flex: 1; }
        .cq-cmd-empty {
            padding: 32px 14px;
            text-align: center;
            color: rgba(255,255,255,0.4);
            font-size: 13px;
        }
        .cq-cmd-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 18px;
            border-top: 1px solid rgba(255,255,255,0.06);
            font-size: 11px;
            color: rgba(255,255,255,0.4);
        }
        .cq-cmd-footer .cq-cmd-hints {
            display: flex; gap: 14px;
        }
        .cq-cmd-footer .cq-cmd-hints span {
            display: inline-flex; align-items: center; gap: 6px;
        }
    `;
    document.head.appendChild(style);

    let backdrop = null;
    let input = null;
    let list = null;
    let filtered = [];
    let selIdx = 0;
    let isOpen = false;

    function build() {
        backdrop = document.createElement('div');
        backdrop.className = 'cq-cmd-backdrop';
        backdrop.innerHTML = `
            <div class="cq-cmd-panel" role="dialog" aria-modal="true">
                <div class="cq-cmd-search">
                    <svg class="cq-cmd-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    <input type="text" class="cq-cmd-input" placeholder="搜索页面、命令、操作…" />
                    <span class="cq-cmd-kbd">ESC</span>
                </div>
                <div class="cq-cmd-list"></div>
                <div class="cq-cmd-footer">
                    <span>校园财商命令面板</span>
                    <span class="cq-cmd-hints">
                        <span><span class="cq-cmd-kbd">↑↓</span> 选择</span>
                        <span><span class="cq-cmd-kbd">↵</span> 执行</span>
                    </span>
                </div>
            </div>`;
        document.body.appendChild(backdrop);
        input = backdrop.querySelector('.cq-cmd-input');
        list  = backdrop.querySelector('.cq-cmd-list');

        input.addEventListener('input', () => render(input.value));
        input.addEventListener('keydown', onKey);
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) close();
        });
    }

    function fuzzy(query, item) {
        if (!query) return 1;
        const q = query.toLowerCase().trim();
        const text = (item.label + ' ' + (item.kw || '') + ' ' + item.group).toLowerCase();
        if (text.includes(q)) return 10;
        // 字符顺序匹配
        let qi = 0;
        for (let i = 0; i < text.length && qi < q.length; i++) {
            if (text[i] === q[qi]) qi++;
        }
        return qi === q.length ? 1 : 0;
    }

    function render(query) {
        filtered = COMMANDS
            .map(c => ({ c, score: fuzzy(query, c) }))
            .filter(x => x.score > 0)
            .sort((a, b) => b.score - a.score)
            .map(x => x.c);
        selIdx = 0;
        if (!filtered.length) {
            list.innerHTML = '<div class="cq-cmd-empty">没有匹配的命令</div>';
            return;
        }
        // 按 group 分组
        const groups = {};
        filtered.forEach(c => {
            if (!groups[c.group]) groups[c.group] = [];
            groups[c.group].push(c);
        });
        let html = '';
        let idx = 0;
        for (const g of Object.keys(groups)) {
            html += `<div class="cq-cmd-group">${g}</div>`;
            for (const c of groups[g]) {
                html += `<div class="cq-cmd-item" data-i="${idx}">
                    <span class="cq-cmd-icon"><i data-lucide="${c.icon}"></i></span>
                    <span class="cq-cmd-label">${c.label}</span>
                </div>`;
                idx++;
            }
        }
        list.innerHTML = html;
        // 重新渲染图标
        if (window.lucide && window.lucide.createIcons) {
            try { lucide.createIcons(); } catch (_) {}
        }
        // 选中第一项
        updateSel();
        // 点击事件
        list.querySelectorAll('.cq-cmd-item').forEach((el) => {
            el.addEventListener('click', () => {
                selIdx = parseInt(el.dataset.i, 10);
                exec();
            });
            el.addEventListener('mousemove', () => {
                selIdx = parseInt(el.dataset.i, 10);
                updateSel();
            });
        });
    }

    function updateSel() {
        list.querySelectorAll('.cq-cmd-item').forEach((el, i) => {
            el.classList.toggle('sel', i === selIdx);
        });
        // scrollIntoView
        const sel = list.querySelector('.cq-cmd-item.sel');
        if (sel) sel.scrollIntoView({ block: 'nearest' });
    }

    function exec() {
        const c = filtered[selIdx];
        if (!c) return;
        close();
        if (c.run) c.run();
        else if (c.href) location.href = c.href;
    }

    function onKey(e) {
        if (e.key === 'ArrowDown') { e.preventDefault(); selIdx = Math.min(filtered.length - 1, selIdx + 1); updateSel(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); selIdx = Math.max(0, selIdx - 1); updateSel(); }
        else if (e.key === 'Enter') { e.preventDefault(); exec(); }
        else if (e.key === 'Escape') { e.preventDefault(); close(); }
    }

    function open() {
        if (isOpen) return;
        if (!backdrop) build();
        isOpen = true;
        render('');
        requestAnimationFrame(() => {
            backdrop.classList.add('show');
            input.focus();
            input.value = '';
        });
    }

    function close() {
        if (!isOpen || !backdrop) return;
        isOpen = false;
        backdrop.classList.remove('show');
    }

    // 全局快捷键
    document.addEventListener('keydown', (e) => {
        const isCmdK = (e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K');
        if (isCmdK) { e.preventDefault(); isOpen ? close() : open(); }
    });

    window.cqCommandPalette = { open, close };
})();
