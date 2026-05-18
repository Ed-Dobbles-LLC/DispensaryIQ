/* DispensaryIQ — theme.js v2
   Dark-default, light-toggle. localStorage-backed.
   Loaded synchronously before paint to avoid flash-of-wrong-theme.
*/
(function() {
  'use strict';
  const KEY = 'diq-theme';
  function getStored() {
    try { return localStorage.getItem(KEY); } catch(e) { return null; }
  }
  function setStored(v) {
    try { localStorage.setItem(KEY, v); } catch(e) {}
  }
  function apply(t) {
    document.documentElement.setAttribute('data-theme', t);
  }
  // v21: ?print=1 URL param forces light theme + print body class
  // (used by PDF export to capture clean content without site nav/chrome)
  let isPrint = false;
  try {
    isPrint = new URLSearchParams(window.location.search).get('print') === '1';
  } catch(e) {}

  // Initial: print > stored > default DARK
  const init = isPrint ? 'light' : (getStored() || 'dark');
  apply(init);

  if (isPrint) {
    function applyPrintClass() {
      if (document.body) document.body.classList.add('diq-print-mode');
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', applyPrintClass);
    } else {
      applyPrintClass();
    }
  }

  window.diqToggleTheme = function() {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    const nxt = cur === 'dark' ? 'light' : 'dark';
    apply(nxt);
    setStored(nxt);
  };
})();
