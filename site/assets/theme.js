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
  // Initial: stored > default DARK
  const init = getStored() || 'dark';
  apply(init);

  window.diqToggleTheme = function() {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    const nxt = cur === 'dark' ? 'light' : 'dark';
    apply(nxt);
    setStored(nxt);
  };
})();
