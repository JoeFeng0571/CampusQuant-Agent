(() => {
  'use strict';

  const APP_PAGE_RE = /(?:^|\/)(dashboard|trade|analysis|platforms|market|community|team|resources|home|auth)\.html(?:[?#].*)?$/i;

  function isEmbedded() {
    return window.top !== window.self;
  }

  const currentFile = window.location.pathname.split('/').pop() || '';

  if (!isEmbedded() && APP_PAGE_RE.test(currentFile) && !/standalone=1/i.test(window.location.search)) {
    const shellTarget = `index.html#${encodeURIComponent(`${currentFile}${window.location.search}${window.location.hash}`)}`;
    if (currentFile !== 'index.html') {
      window.location.replace(shellTarget);
      return;
    }
  }

  function resolve(url) {
    return new URL(url, window.location.href).href;
  }

  function isAppUrl(url) {
    try {
      const resolved = resolve(url);
      const target = new URL(resolved);
      return target.origin === window.location.origin && APP_PAGE_RE.test(target.pathname + target.search + target.hash);
    } catch (_) {
      return false;
    }
  }

  function postNavigate(url, options = {}) {
    const resolved = resolve(url);
    if (isEmbedded()) {
      window.parent.postMessage(
        {
          type: 'CQ_NAVIGATE',
          url: resolved,
          replace: !!options.replace,
        },
        window.location.origin
      );
    } else if (options.replace) {
      window.location.replace(resolved);
    } else {
      window.location.href = resolved;
    }
  }

  function parseOnclickTarget(el) {
    const raw = el.getAttribute('onclick') || '';
    const match = raw.match(/location\.href\s*=\s*['"]([^'"]+\.html(?:[^'"]*)?)['"]/i);
    return match ? match[1] : '';
  }

  window.CQShell = {
    navigate: postNavigate,
    isEmbedded: isEmbedded(),
  };

  document.addEventListener(
    'click',
    (event) => {
      const anchor = event.target.closest('a[href]');
      if (anchor && !anchor.hasAttribute('download') && anchor.target !== '_blank') {
        const href = anchor.getAttribute('href') || '';
        if (isAppUrl(href)) {
          event.preventDefault();
          event.stopPropagation();
          postNavigate(href);
          return;
        }
      }

      const clickable = event.target.closest('[onclick]');
      if (!clickable) return;
      const target = parseOnclickTarget(clickable);
      if (!target || !isAppUrl(target) || !isEmbedded()) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      postNavigate(target);
    },
    true
  );

  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data || {};
    if (data.type !== 'CQ_PAGE_ACTIVATED') return;
    window.dispatchEvent(new CustomEvent('cq-shell-activated', { detail: data }));
  });
})();
