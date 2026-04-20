/**
 * assets/js/term-tooltip.js
 *
 * 财商术语 Tooltip + 跳转组件。
 *
 * 用法：
 *     <script src="/assets/js/term-tooltip.js" defer></script>
 *     CampusQuantTerms.decorate(document.querySelector('#analysis-report'));
 *
 * 原理：
 *   1. 首次调用时 fetch /assets/data/terms.json
 *   2. 对给定容器内的文本节点按"最长优先"正则匹配术语
 *   3. 命中的片段替换为 <span class="cq-term"> 元素，绑定 hover/click 行为
 *   4. 样式从 <style> 注入（全局挂一次，避免每个页面重复）
 *
 * 设计约束：
 *   - 不改变文本语义（只包一层 span，语义无损）
 *   - 不干扰已有事件委托（只对文本节点操作）
 *   - 幂等：同一容器多次调用不会重复装饰
 */
(function () {
  'use strict';

  const STATE = {
    terms: null,
    sortedKeys: null,
    tooltipEl: null,
    anchorBase: '/resources.html',
  };

  const STYLE = `
    .cq-term {
      color: var(--primary, #2dd4bf);
      cursor: help;
      border-bottom: 1px dashed currentColor;
      text-decoration: none;
      transition: background 0.15s;
    }
    .cq-term:hover {
      background: rgba(45, 212, 191, 0.10);
      border-radius: 3px;
    }
    .cq-term[data-level="advanced"]     { color: #c084fc; }
    .cq-term[data-level="intermediate"] { color: #5eead4; }
    .cq-term[data-level="beginner"]     { color: #a7f3d0; }

    #cq-term-tooltip {
      position: fixed;
      z-index: 99999;
      max-width: 320px;
      padding: 12px 14px;
      background: rgba(8, 17, 31, 0.96);
      border: 1px solid rgba(45, 212, 191, 0.35);
      border-radius: 10px;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
      font-size: 13px;
      line-height: 1.6;
      color: #e2e8f0;
      pointer-events: auto;
      opacity: 0;
      transform: translateY(-4px);
      transition: opacity 0.18s, transform 0.18s;
      backdrop-filter: blur(8px);
    }
    #cq-term-tooltip.visible {
      opacity: 1;
      transform: translateY(0);
    }
    #cq-term-tooltip .cq-tip-head {
      display: flex; justify-content: space-between; align-items: baseline;
      gap: 8px; margin-bottom: 6px;
    }
    #cq-term-tooltip .cq-tip-name {
      font-weight: 700; font-size: 14px; color: var(--primary, #2dd4bf);
    }
    #cq-term-tooltip .cq-tip-level {
      font-size: 10px; padding: 2px 6px; border-radius: 4px;
      background: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.65);
      text-transform: uppercase; letter-spacing: 0.05em;
    }
    #cq-term-tooltip .cq-tip-body {
      color: rgba(255, 255, 255, 0.82);
    }
    #cq-term-tooltip .cq-tip-link {
      display: inline-block; margin-top: 8px;
      color: var(--primary, #2dd4bf); font-weight: 600; font-size: 12px;
      text-decoration: none;
    }
    #cq-term-tooltip .cq-tip-link:hover { text-decoration: underline; }
  `;

  function injectStyle() {
    if (document.getElementById('cq-term-style')) return;
    const el = document.createElement('style');
    el.id = 'cq-term-style';
    el.textContent = STYLE;
    document.head.appendChild(el);
  }

  function ensureTooltip() {
    if (STATE.tooltipEl) return STATE.tooltipEl;
    const el = document.createElement('div');
    el.id = 'cq-term-tooltip';
    document.body.appendChild(el);
    STATE.tooltipEl = el;
    // 点击 tooltip 外部隐藏
    document.addEventListener('click', (ev) => {
      if (!el.contains(ev.target) && !ev.target.classList?.contains('cq-term')) {
        hideTooltip();
      }
    });
    return el;
  }

  function showTooltip(anchor, term) {
    const el = ensureTooltip();
    const data = STATE.terms[term];
    if (!data) return;
    el.innerHTML = `
      <div class="cq-tip-head">
        <span class="cq-tip-name">${escapeHtml(data.full_name || term)}</span>
        <span class="cq-tip-level">${data.level || ''}</span>
      </div>
      <div class="cq-tip-body">${escapeHtml(data.definition || '')}</div>
      <a class="cq-tip-link" href="${STATE.anchorBase}${data.anchor || ''}" target="_blank" rel="noopener">
        展开学习 →
      </a>
    `;
    const rect = anchor.getBoundingClientRect();
    const top = rect.bottom + 8;
    let left = rect.left;
    const maxLeft = window.innerWidth - 340;
    if (left > maxLeft) left = maxLeft;
    el.style.top = `${top}px`;
    el.style.left = `${Math.max(8, left)}px`;
    el.classList.add('visible');
  }

  function hideTooltip() {
    if (!STATE.tooltipEl) return;
    STATE.tooltipEl.classList.remove('visible');
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function loadTerms() {
    if (STATE.terms) return STATE.terms;
    try {
      const resp = await fetch('/assets/data/terms.json', { cache: 'force-cache' });
      if (!resp.ok) throw new Error('terms.json HTTP ' + resp.status);
      const raw = await resp.json();
      const { _meta = {}, ...terms } = raw;
      STATE.terms = terms;
      STATE.anchorBase = _meta.anchor_base || STATE.anchorBase;
      // 最长优先匹配（避免 "PEG" 被 "PE" 截断）
      STATE.sortedKeys = Object.keys(terms).sort((a, b) => b.length - a.length);
      return terms;
    } catch (err) {
      console.warn('[term-tooltip] failed to load terms.json:', err);
      STATE.terms = {};
      STATE.sortedKeys = [];
      return {};
    }
  }

  /**
   * 把容器内所有文本节点中的术语包成 <span class="cq-term">。
   * 已装饰过的节点（祖先含 data-cq-decorated）会跳过。
   */
  function decorate(container) {
    if (!container) container = document.body;
    if (!STATE.sortedKeys || STATE.sortedKeys.length === 0) return;

    // 构造一次正则（所有术语 OR 起来）
    const pattern = STATE.sortedKeys
      .map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('|');
    const regex = new RegExp(pattern, 'g');

    const walker = document.createTreeWalker(
      container, NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          // 跳过 script/style/已装饰元素
          let el = node.parentElement;
          while (el && el !== container) {
            const tag = el.tagName;
            if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'A' ||
                el.classList?.contains('cq-term') ||
                el.hasAttribute?.('data-cq-decorated')) {
              return NodeFilter.FILTER_REJECT;
            }
            el = el.parentElement;
          }
          return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
        },
      }
    );

    const targets = [];
    let n;
    while ((n = walker.nextNode())) targets.push(n);

    targets.forEach((textNode) => {
      const text = textNode.nodeValue;
      if (!regex.test(text)) return;
      regex.lastIndex = 0;

      const frag = document.createDocumentFragment();
      let lastIdx = 0;
      let m;
      while ((m = regex.exec(text)) !== null) {
        if (m.index > lastIdx) {
          frag.appendChild(document.createTextNode(text.slice(lastIdx, m.index)));
        }
        const span = document.createElement('span');
        span.className = 'cq-term';
        span.textContent = m[0];
        span.dataset.term = m[0];
        const def = STATE.terms[m[0]];
        if (def?.level) span.dataset.level = def.level;
        if (def?.category) span.dataset.category = def.category;
        frag.appendChild(span);
        lastIdx = m.index + m[0].length;
      }
      if (lastIdx < text.length) {
        frag.appendChild(document.createTextNode(text.slice(lastIdx)));
      }
      textNode.parentNode.replaceChild(frag, textNode);
    });

    container.setAttribute('data-cq-decorated', '1');
  }

  // ── 事件委托（一次性挂到 document） ───────────────────
  function attachGlobalHandlers() {
    document.addEventListener('mouseover', (ev) => {
      const el = ev.target.closest?.('.cq-term');
      if (el) showTooltip(el, el.dataset.term);
    });
    document.addEventListener('mouseout', (ev) => {
      const el = ev.target.closest?.('.cq-term');
      if (!el) return;
      const rel = ev.relatedTarget;
      if (rel && (rel.closest('.cq-term') || rel.closest('#cq-term-tooltip'))) return;
      hideTooltip();
    });
    document.addEventListener('click', (ev) => {
      const el = ev.target.closest?.('.cq-term');
      if (el) {
        ev.preventDefault();
        const def = STATE.terms[el.dataset.term];
        if (def?.anchor) {
          window.open(STATE.anchorBase + def.anchor, '_blank', 'noopener');
        }
      }
    });
  }

  // ── 公共 API ───────────────────────────────────────────
  window.CampusQuantTerms = {
    /**
     * 装饰给定 container（或 body）。可反复调用，已装饰节点跳过。
     * 会自动懒加载 terms.json。
     */
    async decorate(container) {
      injectStyle();
      ensureTooltip();
      await loadTerms();
      decorate(container || document.body);
    },

    /**
     * 供未来使用：手动查询单个术语定义。
     */
    async getTerm(term) {
      await loadTerms();
      return STATE.terms[term];
    },
  };

  // DOMContentLoaded 自动装饰 body（主流页面开箱即用）
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      injectStyle();
      attachGlobalHandlers();
      loadTerms().then(() => decorate(document.body));
    });
  } else {
    injectStyle();
    attachGlobalHandlers();
    loadTerms().then(() => decorate(document.body));
  }
})();
