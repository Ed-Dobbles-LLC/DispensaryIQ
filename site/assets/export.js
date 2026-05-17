/* DispensaryIQ — export.js v1
   Three modes:
     diqExportPDF()  — single page via window.print() with clean filename
     diqExportPNG()  — single page snapshot, dark theme as-displayed
     diqExportAll()  — combined PDF of all 11 pages (dark, multi-page handling)

   Libraries lazy-loaded on first non-print export call.
*/

(function() {
  'use strict';

  const PAGES = [
    {file: 'index.html',                  name: 'Scorecard'},
    {file: 'coverage.html',               name: 'Coverage'},
    {file: 'products.html',               name: 'Products'},
    {file: 'market-share.html',           name: 'Market-share'},
    {file: 'price-compliance.html',       name: 'Price-compliance'},
    {file: 'shelf-quality-explainer.html',name: 'Shelf-metrics'},
    {file: 'display-quality.html',        name: 'Display-quality'},
    {file: 'ny-find.html',                name: 'NY-watchlist'},
    {file: 'alerts.html',                 name: 'Alerts'},
    {file: 'territory.html',              name: 'Territory'},
    {file: 'named-accounts.html',         name: 'Accounts'},
  ];

  const HTML2CANVAS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
  const JSPDF_CDN       = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';

  function dateStr() {
    const d = new Date();
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  }

  function currentPageSlug() {
    const path = (window.location.pathname.split('/').pop() || 'index.html');
    const found = PAGES.find(p => p.file === path);
    return found ? found.name : 'Page';
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(s);
    });
  }

  async function ensureLibs() {
    if (!window.html2canvas) await loadScript(HTML2CANVAS_CDN);
    if (!window.jspdf)       await loadScript(JSPDF_CDN);
  }

  // ----- Progress modal -----

  let modalEl = null;

  function injectModalStyles() {
    if (document.getElementById('diq-export-modal-styles')) return;
    const style = document.createElement('style');
    style.id = 'diq-export-modal-styles';
    style.textContent = `
      .diq-export-modal-backdrop {
        position: fixed; inset: 0; background: rgba(6, 10, 31, 0.85);
        z-index: 9998; display: flex; align-items: center; justify-content: center;
        backdrop-filter: blur(4px);
      }
      .diq-export-modal {
        background: #11162A; border: 1px solid #1A2074; border-radius: 8px;
        padding: 28px 36px; min-width: 360px; max-width: 480px;
        font-family: 'Calibri', sans-serif; color: #F5F6FA;
        box-shadow: 0 20px 60px rgba(0,0,0,0.6);
      }
      .diq-export-modal h3 {
        margin: 0 0 6px 0; font-family: 'Montserrat', sans-serif;
        font-weight: 700; font-size: 16px; color: #F5F6FA;
      }
      .diq-export-modal p {
        margin: 0 0 16px 0; font-size: 13px; color: #B4BACC;
      }
      .diq-export-progress {
        height: 6px; background: rgba(255,255,255,0.08); border-radius: 3px;
        overflow: hidden; margin-bottom: 12px;
      }
      .diq-export-progress-bar {
        height: 100%; background: linear-gradient(90deg, #00B98E, #1FD4A8);
        width: 0%; transition: width 0.3s ease;
      }
      .diq-export-status {
        font-family: 'Consolas', monospace; font-size: 11px;
        color: #7A8099; text-transform: uppercase; letter-spacing: 0.06em;
      }
      .diq-export-close {
        margin-top: 14px; padding: 8px 16px; background: transparent;
        border: 1px solid rgba(255,255,255,0.20); color: #F5F6FA;
        font-family: 'Calibri', sans-serif; font-size: 12px; border-radius: 4px;
        cursor: pointer;
      }
      .diq-export-close:hover { border-color: #00B98E; color: #00B98E; }

      .diq-export-iframe-stage {
        position: fixed; left: -10000px; top: 0; width: 1400px; height: auto;
        border: 0; pointer-events: none;
      }
    `;
    document.head.appendChild(style);
  }

  function showModal(title, msg) {
    injectModalStyles();
    if (modalEl) modalEl.remove();
    modalEl = document.createElement('div');
    modalEl.className = 'diq-export-modal-backdrop';
    modalEl.innerHTML = `
      <div class="diq-export-modal">
        <h3>${title}</h3>
        <p>${msg}</p>
        <div class="diq-export-progress"><div class="diq-export-progress-bar"></div></div>
        <p class="diq-export-status" id="diq-export-status">Initializing…</p>
      </div>
    `;
    document.body.appendChild(modalEl);
  }

  function updateProgress(pct, status) {
    if (!modalEl) return;
    const bar = modalEl.querySelector('.diq-export-progress-bar');
    const st  = modalEl.querySelector('#diq-export-status');
    if (bar) bar.style.width = `${pct}%`;
    if (st)  st.textContent = status;
  }

  function finishModal(msg) {
    if (!modalEl) return;
    const modal = modalEl.querySelector('.diq-export-modal');
    modal.innerHTML = `
      <h3>Done</h3>
      <p>${msg}</p>
      <button class="diq-export-close">Close</button>
    `;
    modal.querySelector('.diq-export-close').addEventListener('click', () => {
      modalEl.remove(); modalEl = null;
    });
  }

  function failModal(err) {
    if (!modalEl) return;
    const modal = modalEl.querySelector('.diq-export-modal');
    modal.innerHTML = `
      <h3 style="color:#DB5461">Export failed</h3>
      <p>${err}</p>
      <button class="diq-export-close">Close</button>
    `;
    modal.querySelector('.diq-export-close').addEventListener('click', () => {
      modalEl.remove(); modalEl = null;
    });
  }

  // ----- Single page: PDF via print -----

  window.diqExportPDF = function() {
    // Browser uses document.title as default filename for "Save as PDF"
    const originalTitle = document.title;
    document.title = `DispensaryIQ-${currentPageSlug()}-${dateStr()}`;
    window.print();
    // Restore after a tick (print dialog reads title at time of call)
    setTimeout(() => { document.title = originalTitle; }, 1000);
  };

  // ----- Single page: PNG via html2canvas -----

  window.diqExportPNG = async function() {
    showModal('Generating image', 'Capturing this page as PNG…');
    try {
      await ensureLibs();
      updateProgress(40, 'Rendering DOM');

      // Hide modal and any sticky/fixed elements during capture
      const navEl = document.querySelector('.diq-nav');
      const wasNavVisible = navEl ? navEl.style.visibility : null;
      if (modalEl) modalEl.style.visibility = 'hidden';

      const target = document.body;
      const canvas = await window.html2canvas(target, {
        backgroundColor: '#0A0E1F',
        useCORS: true,
        allowTaint: true,
        scale: 2,
        scrollX: 0,
        scrollY: 0,
        windowWidth: document.documentElement.scrollWidth,
        windowHeight: document.documentElement.scrollHeight,
        ignoreElements: el => el.classList && el.classList.contains('diq-export-modal-backdrop'),
      });

      if (modalEl) modalEl.style.visibility = 'visible';
      updateProgress(90, 'Encoding PNG');

      const blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `DispensaryIQ-${currentPageSlug()}-${dateStr()}.png`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);

      updateProgress(100, 'Complete');
      finishModal(`Downloaded <code style="background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:3px;font-family:Consolas,monospace;font-size:11px">${a.download}</code>`);
    } catch (e) {
      console.error(e);
      failModal(e.message || 'Unknown error during PNG export.');
    }
  };

  // ----- All pages: combined PDF via iframes + jsPDF -----

  window.diqExportAll = async function() {
    showModal('Generating combined PDF', `Capturing all ${PAGES.length} pages and stitching into one PDF. This takes ~30–60 seconds.`);
    try {
      await ensureLibs();
      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF({ orientation: 'landscape', unit: 'px', format: [1400, 900], hotfixes: ['px_scaling'] });

      const stage = document.createElement('iframe');
      stage.className = 'diq-export-iframe-stage';
      document.body.appendChild(stage);

      for (let i = 0; i < PAGES.length; i++) {
        const page = PAGES[i];
        const pct = Math.round((i / PAGES.length) * 92);
        updateProgress(pct, `Capturing ${i+1} of ${PAGES.length}: ${page.name}`);

        // Load page into iframe
        await new Promise((resolve, reject) => {
          stage.onload = () => resolve();
          stage.onerror = reject;
          stage.src = page.file;
        });

        // Wait for fonts + JS to render
        await new Promise(r => setTimeout(r, 1800));

        // Capture
        const doc = stage.contentDocument;
        const body = doc.body;
        // Match outer viewport
        stage.style.height = body.scrollHeight + 'px';

        const canvas = await window.html2canvas(body, {
          backgroundColor: '#0A0E1F',
          useCORS: true,
          allowTaint: true,
          scale: 1.5,
          width: 1400,
          height: body.scrollHeight,
          windowWidth: 1400,
          windowHeight: body.scrollHeight,
        });

        // Add to PDF, splitting if taller than one PDF page
        const pdfW = pdf.internal.pageSize.getWidth();
        const pdfH = pdf.internal.pageSize.getHeight();
        const imgW = pdfW;
        const imgH = (canvas.height * imgW) / canvas.width;
        const dataUrl = canvas.toDataURL('image/png');

        if (i > 0) pdf.addPage();
        let heightLeft = imgH;
        let position = 0;
        pdf.addImage(dataUrl, 'PNG', 0, position, imgW, imgH, undefined, 'FAST');
        heightLeft -= pdfH;
        while (heightLeft > 0) {
          position = heightLeft - imgH;
          pdf.addPage();
          pdf.addImage(dataUrl, 'PNG', 0, position, imgW, imgH, undefined, 'FAST');
          heightLeft -= pdfH;
        }
      }

      stage.remove();
      updateProgress(96, 'Building PDF file');

      const filename = `DispensaryIQ-CompletePack-${dateStr()}.pdf`;
      pdf.save(filename);
      updateProgress(100, 'Complete');
      finishModal(`Downloaded <code style="background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:3px;font-family:Consolas,monospace;font-size:11px">${filename}</code> — ${PAGES.length} pages.`);
    } catch (e) {
      console.error(e);
      failModal(e.message || 'Unknown error during combined PDF export.');
    }
  };
})();
