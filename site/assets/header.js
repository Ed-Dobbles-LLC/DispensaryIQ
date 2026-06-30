/* DispensaryIQ — header.js v1
   Shared page header for the pitch-facing data deck.

   Replaces the old top-nav link row with two controls:
     • #diq-page-nav  — page dropdown, the SOLE navigation between views
     • #diq-week-nav  — certified-week dropdown, built from data/weeks_manifest.json

   Behaviour
   ---------
   • The page dropdown shows the CURRENT page selected (matched by filename) and,
     on change, navigates to the chosen page — carrying the active ?week= param so
     a week selection persists across the deck.
   • The week dropdown is built from the manifest and defaults to manifest.default.
     Choosing the default week strips the ?week= param (canonical URL → default
     payload); choosing any other week sets ?week=<iso> and reloads.
   • Pages resolve which payload to load purely from the URL param (no manifest
     dependency, no load-order coupling): absent param → the page's canonical
     default-week payload; present param → a week-suffixed payload, and an honest
     empty-state when that file does not exist yet. (W26 data is live in the
     canonical files; older/other certified weeks empty-state until their
     per-week payloads are published.)

   This file changes navigation + week wiring only. It never authors numbers.
*/
(function () {
  'use strict';

  // Mount point each page exposes where the old .diq-nav-links row used to be.
  var MOUNT_ID = 'diq-nav-controls';

  // Navigation pages — label, file, optional css class suffix. Order = deck order.
  var PAGES = [
    { label: 'Scorecard',         file: 'index.html' },
    { label: 'Coverage',          file: 'coverage.html' },
    { label: 'Products',          file: 'products.html' },
    { label: 'Price comparison',  file: 'price-comparison.html' },
    { label: 'Market share',      file: 'market-share.html' },
    { label: 'Price compliance',  file: 'price-compliance.html' },
    { label: 'Display quality',   file: 'display-quality.html' },
    { label: 'NY watchlist',      file: 'ny-find.html' },
    { label: 'Alerts',            file: 'alerts.html' },
    { label: 'Week-over-week',    file: 'week-over-week.html' },
    { label: 'Territory',         file: 'territory.html',       cls: 'phase' },
    { label: 'Accounts',          file: 'named-accounts.html',  cls: 'phase' }
  ];

  var MANIFEST_URL = 'data/weeks_manifest.json';

  window.DIQ = window.DIQ || {};

  // ── Synchronous helpers (no manifest needed) ─────────────────────────────
  // The active week param, or null when on the canonical default week.
  DIQ.activeWeekParam = function () {
    try { return new URLSearchParams(window.location.search).get('week'); }
    catch (e) { return null; }
  };
  DIQ.isDefaultWeek = function () { return !DIQ.activeWeekParam(); };

  // Resolve the payload URL for a page given its canonical (default-week) file.
  //   default week  → baseFile unchanged (e.g. data/market_share_payload.json)
  //   other week    → data/market_share_payload_2026-W23.json
  DIQ.weekPayloadUrl = function (baseFile) {
    var wk = DIQ.activeWeekParam();
    if (!wk) return baseFile;
    return baseFile.replace(/\.json($|\?)/, '_' + wk + '.json$1');
  };

  // Cached manifest (set after fetch). weekLabel falls back to the iso string.
  DIQ.manifest = null;
  DIQ.weekLabel = function (iso) {
    if (DIQ.manifest && Array.isArray(DIQ.manifest.weeks)) {
      for (var i = 0; i < DIQ.manifest.weeks.length; i++) {
        if (DIQ.manifest.weeks[i].iso_week === iso) return DIQ.manifest.weeks[i].label;
      }
    }
    return iso;
  };

  // Honest empty-state — used when a non-default week has no published payload.
  // Replaces the <main> content; never fabricates data.
  DIQ.renderWeekEmptyState = function () {
    var main = document.querySelector('main.diq-main') || document.querySelector('main');
    if (!main) return;
    var wk = DIQ.activeWeekParam();
    var label = wk ? DIQ.weekLabel(wk) : 'this week';
    main.innerHTML =
      '<div class="diq-week-empty">' +
        '<p class="diq-week-empty-eyebrow">Certified week</p>' +
        '<h1 class="diq-week-empty-title">No certified data for ' + escapeHtml(label) + '</h1>' +
        '<p class="diq-week-empty-body">This view has not been published for the selected week yet. ' +
          'Use the week selector above to return to the most recent certified week.</p>' +
      '</div>';
  };

  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function currentFile() {
    var path = window.location.pathname;
    var f = path.substring(path.lastIndexOf('/') + 1);
    if (!f || f.indexOf('.') === -1) f = 'index.html';
    return f.toLowerCase();
  }

  // ── Build the header controls ────────────────────────────────────────────
  function buildControls(manifest) {
    var mount = document.getElementById(MOUNT_ID);
    if (!mount) return;

    var here = currentFile();
    var activeWeek = DIQ.activeWeekParam();
    var defaultWeek = (manifest && manifest.default) || null;
    var weeks = (manifest && Array.isArray(manifest.weeks)) ? manifest.weeks : [];
    var selectedWeek = activeWeek || defaultWeek || (weeks[0] && weeks[0].iso_week) || '';

    // Page nav — render as links (matching diq-nav-link style)
    var linksWrap = document.createElement('div');
    linksWrap.className = 'diq-nav-links';
    PAGES.forEach(function (p) {
      var a = document.createElement('a');
      var cls = 'diq-nav-link';
      if (p.cls) cls += ' ' + p.cls;
      if (p.file.toLowerCase() === here) cls += ' active';
      a.className = cls;
      a.textContent = p.label;
      var href = p.file;
      if (activeWeek) href += '?week=' + encodeURIComponent(activeWeek);
      a.href = href;
      linksWrap.appendChild(a);
    });

    // Week select (keep as dropdown — compact)
    var weekSel = document.createElement('select');
    weekSel.id = 'diq-week-nav';
    weekSel.className = 'diq-nav-select diq-nav-select-week';
    weekSel.setAttribute('aria-label', 'Select certified week');
    weeks.forEach(function (w) {
      var o = document.createElement('option');
      o.value = w.iso_week;
      o.textContent = w.label;
      if (w.iso_week === selectedWeek) o.selected = true;
      weekSel.appendChild(o);
    });
    weekSel.addEventListener('change', function () {
      var chosen = weekSel.value;
      var base = window.location.pathname;
      if (defaultWeek && chosen === defaultWeek) {
        window.location.href = base;
      } else {
        window.location.href = base + '?week=' + encodeURIComponent(chosen);
      }
    });

    // Overflow "More ▾" button — populated by setupOverflow after DOM settle
    var moreWrap = document.createElement('div');
    moreWrap.className = 'diq-nav-more';
    moreWrap.style.display = 'none';

    var moreBtn = document.createElement('button');
    moreBtn.className = 'diq-nav-more-btn';
    moreBtn.textContent = 'More ▾';
    moreWrap.appendChild(moreBtn);

    var moreDrop = document.createElement('div');
    moreDrop.className = 'diq-nav-more-dropdown';
    moreDrop.style.display = 'none';
    moreWrap.appendChild(moreDrop);

    moreBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      moreDrop.style.display = moreDrop.style.display === 'none' ? 'block' : 'none';
    });
    document.addEventListener('click', function () { moreDrop.style.display = 'none'; });

    linksWrap.appendChild(moreWrap);

    mount.innerHTML = '';
    mount.appendChild(linksWrap);
    if (weeks.length > 0) {
      var weekWrap = document.createElement('span');
      weekWrap.className = 'diq-nav-select-wrap diq-nav-select-wrap-week';
      weekWrap.appendChild(weekSel);
      mount.appendChild(weekWrap);
    }

    // Collapse low-priority links into More when they overflow
    var ALWAYS_VISIBLE = ['index.html', 'coverage.html', 'products.html', 'market-share.html'];

    function relayoutNav() {
      var allLinks = Array.from(linksWrap.querySelectorAll('a.diq-nav-link'));
      // Reset: show all links, clear dropdown
      allLinks.forEach(function (a) { a.style.display = ''; });
      moreDrop.innerHTML = '';
      moreWrap.style.display = 'none';
      moreDrop.style.display = 'none';

      // If everything fits, done
      if (linksWrap.scrollWidth <= linksWrap.offsetWidth + 2) return;

      // Collapse from the right, skip always-visible items
      for (var i = allLinks.length - 1; i >= 0; i--) {
        var a = allLinks[i];
        var file = (a.getAttribute('href') || '').split('?')[0].replace(/.*\//, '') || 'index.html';
        if (ALWAYS_VISIBLE.indexOf(file) >= 0) continue;
        var clone = a.cloneNode(true);
        clone.style.display = '';
        moreDrop.insertBefore(clone, moreDrop.firstChild);
        a.style.display = 'none';
        moreWrap.style.display = '';
        if (linksWrap.scrollWidth <= linksWrap.offsetWidth + 2) break;
      }
    }

    if (window.ResizeObserver) {
      new ResizeObserver(relayoutNav).observe(mount);
    }
    setTimeout(relayoutNav, 0);

    // Static pages (no payload to re-fetch) honestly empty-state off the
    // default week. Payload pages handle their own empty-state in init().
    if (!DIQ.isDefaultWeek() && document.body.hasAttribute('data-diq-week-static')) {
      DIQ.renderWeekEmptyState();
    }

    // If a payload page already rendered an empty-state before the manifest
    // resolved, upgrade its title from the raw iso to the friendly label.
    var existingEmpty = document.querySelector('.diq-week-empty-title');
    var ewk = DIQ.activeWeekParam();
    if (existingEmpty && ewk) {
      existingEmpty.textContent = 'No certified data for ' + DIQ.weekLabel(ewk);
    }
  }

  function init() {
    fetch(MANIFEST_URL, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (manifest) {
        DIQ.manifest = manifest;
        buildControls(manifest);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
