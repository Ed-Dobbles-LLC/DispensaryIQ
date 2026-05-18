/* DispensaryIQ — theme.js v1
   Light-default, dark-toggle. localStorage-backed.
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
  // Initial: stored > default light
  const init = getStored() || 'light';
  apply(init);

  window.diqToggleTheme = function() {
    const cur = document.documentElement.getAttribute('data-theme') || 'light';
    const nxt = cur === 'light' ? 'dark' : 'light';
    apply(nxt);
    setStored(nxt);
  };
})();
