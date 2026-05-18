/* DispensaryIQ — export.js v3
   Two modes, both all-pages:
     diqExportPDF()  — all 11 pages combined into one landscape PDF
     diqExportPNG()  — all 11 pages packaged as individual PNGs in a ZIP

   Libraries lazy-loaded on first click: html2canvas, jsPDF, JSZip.
*/

(function() {
  'use strict';

  const PAGES = [
    {file: 'index.html',                  name: 'Scorecard'},
    {file: 'coverage.html',               name: 'Coverage'},
    {file: 'products.html',               name: 'Products'},
    {file: 'market-share.html',           name: 'Market-share'},
    {file: 'price-compliance.html',       name: 'Price-compliance'},
    {file: 'shelf-quality-explainer.html',name: 'Methodology'},
    {file: 'display-quality.html',        name: 'Display-quality'},
    {file: 'ny-find.html',                name: 'NY-watchlist'},
    {file: 'alerts.html',                 name: 'Alerts'},
    {file: 'territory.html',              name: 'Territory'},
    {file: 'named-accounts.html',         name: 'Accounts'},
  ];

  const HTML2CANVAS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
  const JSPDF_CDN       = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
  const JSZIP_CDN       = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';

  function dateStr() {
    const d = new Date();
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
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

  async function ensureLibs(needZip) {
    if (!window.html2canvas) await loadScript(HTML2CANVAS_CDN);
    if (!window.jspdf)       await loadScript(JSPDF_CDN);
    if (needZip && !window.JSZip) await loadScript(JSZIP_CDN);
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

  // ----- Capture a page in an iframe and return a canvas -----
  async function captureIframePage(stage, pageUrl) {
    await new Promise((resolve, reject) => {
      stage.onload = () => resolve();
      stage.onerror = reject;
      stage.src = pageUrl;
    });
    // Let JS and fonts settle
    await new Promise(r => setTimeout(r, 1800));

    const doc = stage.contentDocument;
    const body = doc.body;
    stage.style.height = body.scrollHeight + 'px';

    return await window.html2canvas(body, {
      backgroundColor: null,         // use the page's own background (theme-aware)
      useCORS: true,
      allowTaint: true,
      scale: 1.5,
      width: 1400,
      height: body.scrollHeight,
      windowWidth: 1400,
      windowHeight: body.scrollHeight,
    });
  }

  // ----- PDF: all 11 pages combined -----
  window.diqExportPDF = async function() {
    showModal('Generating combined PDF', `Capturing all ${PAGES.length} pages and stitching into one PDF. This takes ~30–60 seconds.`);
    try {
      await ensureLibs(false);
      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF({ orientation: 'landscape', unit: 'px', format: [1400, 900], hotfixes: ['px_scaling'] });

      const stage = document.createElement('iframe');
      stage.className = 'diq-export-iframe-stage';
      document.body.appendChild(stage);

      for (let i = 0; i < PAGES.length; i++) {
        const page = PAGES[i];
        updateProgress(Math.round((i / PAGES.length) * 92), `Capturing ${i+1} of ${PAGES.length}: ${page.name}`);

        const canvas = await captureIframePage(stage, page.file);

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

      const filename = `DispensaryIQ-${dateStr()}.pdf`;
      pdf.save(filename);
      updateProgress(100, 'Complete');
      finishModal(`Downloaded <code style="background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:3px;font-family:Consolas,monospace;font-size:11px">${filename}</code> — ${PAGES.length} pages.`);
    } catch (e) {
      console.error(e);
      failModal(e.message || 'Unknown error during PDF export.');
    }
  };

  // ----- PNG: all 11 pages as individual PNGs zipped together -----
  window.diqExportPNG = async function() {
    showModal('Generating image pack', `Capturing all ${PAGES.length} pages as individual PNGs and bundling into a ZIP. This takes ~30–60 seconds.`);
    try {
      await ensureLibs(true);
      const zip = new window.JSZip();

      const stage = document.createElement('iframe');
      stage.className = 'diq-export-iframe-stage';
      document.body.appendChild(stage);

      for (let i = 0; i < PAGES.length; i++) {
        const page = PAGES[i];
        updateProgress(Math.round((i / PAGES.length) * 88), `Capturing ${i+1} of ${PAGES.length}: ${page.name}`);

        const canvas = await captureIframePage(stage, page.file);
        const blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
        const seq = String(i+1).padStart(2, '0');
        zip.file(`${seq}-${page.name}.png`, blob);
      }

      stage.remove();
      updateProgress(94, 'Building ZIP archive');

      const zipBlob = await zip.generateAsync({ type: 'blob' }, (meta) => {
        updateProgress(94 + Math.round(meta.percent * 0.06), 'Compressing');
      });

      const filename = `DispensaryIQ-${dateStr()}.zip`;
      const url = URL.createObjectURL(zipBlob);
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);

      updateProgress(100, 'Complete');
      finishModal(`Downloaded <code style="background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:3px;font-family:Consolas,monospace;font-size:11px">${filename}</code> — ${PAGES.length} PNGs.`);
    } catch (e) {
      console.error(e);
      failModal(e.message || 'Unknown error during PNG export.');
    }
  };

  // Legacy alias — anywhere still wired to "diqExportAll" gets the same all-pages PDF
  window.diqExportAll = window.diqExportPDF;
})();
