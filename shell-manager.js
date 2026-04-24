(() => {
  'use strict';

  const APP_PAGES = new Set([
    'dashboard.html',
    'trade.html',
    'analysis.html',
    'platforms.html',
    'market.html',
    'community.html',
    'team.html',
    'resources.html',
    'auth.html',
  ]);

  const DEFAULT_PAGE = 'dashboard.html';
  const container = document.getElementById('app-shell');
  const loadingEl = document.getElementById('shell-loading');
  const frames = new Map();
  let activeKey = '';

  function showLoading(text = '页面加载中...') {
    if (!loadingEl) return;
    loadingEl.querySelector('.shell-loading-text').textContent = text;
    loadingEl.classList.remove('hidden');
  }

  function hideLoading() {
    if (!loadingEl) return;
    loadingEl.classList.add('hidden');
  }

  function normalizeInput(rawUrl) {
    const raw = String(rawUrl || '').trim();
    const base = new URL(window.location.href);
    const url = new URL(raw || DEFAULT_PAGE, base);
    const file = url.pathname.split('/').pop() || DEFAULT_PAGE;
    if (!APP_PAGES.has(file)) {
      return new URL(DEFAULT_PAGE, base);
    }
    return url;
  }

  function getAppKey(urlLike) {
    const url = normalizeInput(urlLike);
    return url.pathname.split('/').pop() || DEFAULT_PAGE;
  }

  function toRelativeAppUrl(urlLike) {
    const url = normalizeInput(urlLike);
    const file = url.pathname.split('/').pop() || DEFAULT_PAGE;
    return `${file}${url.search}${url.hash}`;
  }

  function readRouteFromHash() {
    const raw = decodeURIComponent(window.location.hash.replace(/^#/, ''));
    return raw || DEFAULT_PAGE;
  }

  function writeHash(urlLike, replace = false) {
    const next = `#${encodeURIComponent(toRelativeAppUrl(urlLike))}`;
    if (replace) {
      history.replaceState(null, '', next);
    } else {
      history.pushState(null, '', next);
    }
  }

  function createFrame(urlLike) {
    const key = getAppKey(urlLike);
    const src = toRelativeAppUrl(urlLike);
    const iframe = document.createElement('iframe');
    iframe.className = 'shell-frame';
    iframe.dataset.key = key;
    iframe.dataset.src = src;
    iframe.dataset.pendingLoad = 'true';
    iframe.src = src;
    iframe.title = key;
    iframe.loading = 'eager';

    iframe.addEventListener('load', () => {
      iframe.dataset.pendingLoad = 'false';
      if (activeKey === key) {
        hideLoading();
      }
    });

    container.appendChild(iframe);
    frames.set(key, iframe);
    return iframe;
  }

  function notifyActivated(frame, urlLike) {
    try {
      const rel = toRelativeAppUrl(urlLike);
      frame.contentWindow?.postMessage(
        {
          type: 'CQ_PAGE_ACTIVATED',
          url: rel,
          key: frame.dataset.key || '',
        },
        window.location.origin
      );

      const w = frame.contentWindow;
      const refreshFns = [
        'renderAuthWidget',
        'renderWelcome',
        'loadAccount',
        'loadNews',
        'loadChatHistory',
        'loadPortfolio',
        'loadOrders',
        'loadPortfolioSummary',
      ];

      refreshFns.forEach((fn) => {
        try {
          if (typeof w?.[fn] === 'function') {
            w[fn]();
          }
        } catch (_) {}
      });

      try {
        if (typeof w?.loadPosts === 'function') {
          w.loadPosts(true);
        }
      } catch (_) {}
    } catch (_) {}
  }

  function activate(urlLike, options = {}) {
    const { replace = false, forceReload = false, syncHash = true } = options;
    const key = getAppKey(urlLike);
    const src = toRelativeAppUrl(urlLike);

    let frame = frames.get(key);
    if (!frame) {
      showLoading('页面加载中...');
      frame = createFrame(src);
    } else if (forceReload || frame.dataset.src !== src) {
      frame.dataset.src = src;
      frame.dataset.pendingLoad = 'true';
      showLoading('页面加载中...');
      frame.src = src;
    }

    frames.forEach((item, itemKey) => {
      item.classList.toggle('active', itemKey === key);
    });

    activeKey = key;
    if (!frame.dataset.loadedOnce) {
      frame.dataset.loadedOnce = 'true';
    } else if (frame.dataset.pendingLoad !== 'true') {
      hideLoading();
    }

    notifyActivated(frame, src);

    if (syncHash) {
      writeHash(src, replace);
    }
  }

  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data || {};
    if (data.type !== 'CQ_NAVIGATE' || !data.url) return;
    activate(data.url, { replace: !!data.replace });
  });

  window.addEventListener('hashchange', () => {
    activate(readRouteFromHash(), { replace: true, syncHash: false });
  });

  activate(readRouteFromHash(), { replace: true });
})();
