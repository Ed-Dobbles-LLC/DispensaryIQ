/* DispensaryIQ — export.js v4
   Publication-grade PDF + PNG-ZIP exports of the full 11-page pack.

   PDF (window.diqExportPDF):
     - Letter portrait, 612 x 792 pt
     - Forces LIGHT theme on each captured iframe (consistent print-grade look)
     - Navy header band with wordmark + page title
     - Gray footer band with date, page X of Y, and site-page name
     - 28pt margins, content area 556 x 700 pt
     - Each site-page fits 1 PDF page (scaled to fit, centered).
       Tall pages allowed up to 2 PDF pages, split at the midpoint
       with the same header/footer repeated.

   PNG (window.diqExportPNG):
     - ZIP of 11 individual PNG files at scale 1.5 (each captured page = 1 PNG)
     - Light theme forced during capture for printable output

   Libraries lazy-loaded on first click.
*/

(function() {
  'use strict';

  const PAGES = [
    {file: 'index.html',                   name: 'Scorecard'},
    {file: 'coverage.html',                name: 'Coverage'},
    {file: 'products.html',                name: 'Products'},
    {file: 'market-share.html',            name: 'Market share'},
    {file: 'price-compliance.html',        name: 'Price compliance'},
    {file: 'shelf-quality-explainer.html', name: 'Methodology'},
    {file: 'display-quality.html',         name: 'Display quality'},
    {file: 'ny-find.html',                 name: 'NY watchlist'},
    {file: 'alerts.html',                  name: 'Alerts'},
    {file: 'territory.html',               name: 'Territory'},
    {file: 'named-accounts.html',          name: 'Accounts'},
  ];

  const HTML2CANVAS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
  const JSPDF_CDN       = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
  const JSZIP_CDN       = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';

  // ---- Brand colors for chrome (matches site palette) ----
  const NAVY   = '#060A57';
  const TEAL   = '#1FD4A8';
  const INK    = '#0A0E1F';
  const INK_S  = '#3B4258';
  const INK_F  = '#6B7280';
  const RULE   = '#E5E7EB';

  function dateStr() {
    const d = new Date();
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
      const s = document.createElement('script');
      s.src = src; s.onload = resolve;
      s.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(s);
    });
  }
  async function ensureLibs(needZip) {
    if (!window.html2canvas) await loadScript(HTML2CANVAS_CDN);
    if (!window.jspdf)       await loadScript(JSPDF_CDN);
    if (needZip && !window.JSZip) await loadScript(JSZIP_CDN);
  }

  // ===== Progress modal =====

  let modalEl = null;
  function injectModalStyles() {
    if (document.getElementById('diq-export-modal-styles')) return;
    const s = document.createElement('style');
    s.id = 'diq-export-modal-styles';
    s.textContent = `
      .diq-export-modal-backdrop {position:fixed;inset:0;background:rgba(6,10,31,0.85);z-index:9998;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);}
      .diq-export-modal {background:#11162A;border:1px solid #1A2074;border-radius:8px;padding:28px 36px;min-width:360px;max-width:480px;font-family:'Calibri',sans-serif;color:#F5F6FA;box-shadow:0 20px 60px rgba(0,0,0,0.6);}
      .diq-export-modal h3 {margin:0 0 6px 0;font-family:'Montserrat',sans-serif;font-weight:700;font-size:16px;color:#F5F6FA;}
      .diq-export-modal p {margin:0 0 16px 0;font-size:13px;color:#B4BACC;}
      .diq-export-progress {height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;margin-bottom:12px;}
      .diq-export-progress-bar {height:100%;background:linear-gradient(90deg,#00B98E,#1FD4A8);width:0%;transition:width 0.3s ease;}
      .diq-export-status {font-family:'Consolas',monospace;font-size:11px;color:#7A8099;text-transform:uppercase;letter-spacing:0.06em;}
      .diq-export-close {margin-top:14px;padding:8px 16px;background:transparent;border:1px solid rgba(255,255,255,0.20);color:#F5F6FA;font-family:'Calibri',sans-serif;font-size:12px;border-radius:4px;cursor:pointer;}
      .diq-export-close:hover {border-color:#00B98E;color:#00B98E;}
      .diq-export-iframe-stage {position:fixed;left:-10000px;top:0;width:1300px;height:auto;border:0;pointer-events:none;}
    `;
    document.head.appendChild(s);
  }
  function showModal(title, msg) {
    injectModalStyles();
    if (modalEl) modalEl.remove();
    modalEl = document.createElement('div');
    modalEl.className = 'diq-export-modal-backdrop';
    modalEl.innerHTML = `<div class="diq-export-modal"><h3>${title}</h3><p>${msg}</p><div class="diq-export-progress"><div class="diq-export-progress-bar"></div></div><p class="diq-export-status" id="diq-export-status">Initializing…</p></div>`;
    document.body.appendChild(modalEl);
  }
  function updateProgress(pct, status) {
    if (!modalEl) return;
    const bar = modalEl.querySelector('.diq-export-progress-bar');
    const st  = modalEl.querySelector('#diq-export-status');
    if (bar) bar.style.width = pct + '%';
    if (st)  st.textContent = status;
  }
  function finishModal(msg) {
    if (!modalEl) return;
    const m = modalEl.querySelector('.diq-export-modal');
    m.innerHTML = `<h3>Done</h3><p>${msg}</p><button class="diq-export-close">Close</button>`;
    m.querySelector('.diq-export-close').addEventListener('click', () => { modalEl.remove(); modalEl = null; });
  }
  function failModal(err) {
    if (!modalEl) return;
    const m = modalEl.querySelector('.diq-export-modal');
    m.innerHTML = `<h3 style="color:#DB5461">Export failed</h3><p>${err}</p><button class="diq-export-close">Close</button>`;
    m.querySelector('.diq-export-close').addEventListener('click', () => { modalEl.remove(); modalEl = null; });
  }

  // ===== Iframe capture w/ forced LIGHT theme =====

  async function captureIframePage(stage, pageUrl) {
    await new Promise((resolve, reject) => {
      stage.onload = () => resolve();
      stage.onerror = reject;
      stage.src = pageUrl;
    });
    // Wait for fonts + initial render
    await new Promise(r => setTimeout(r, 1200));

    // Force LIGHT theme inside the iframe regardless of user's saved preference
    try {
      const ifDoc = stage.contentDocument;
      ifDoc.documentElement.setAttribute('data-theme', 'light');
      // Force a layout flush so the new theme paints
      void ifDoc.body.offsetHeight;
    } catch(e) { /* same-origin guard, should always succeed */ }

    // A second tick for the theme transition + any deferred renders
    await new Promise(r => setTimeout(r, 700));

    const body = stage.contentDocument.body;
    stage.style.height = body.scrollHeight + 'px';

    return await window.html2canvas(body, {
      backgroundColor: '#FFFFFF',
      useCORS: true,
      allowTaint: true,
      scale: 1.5,
      width: 1300,
      height: body.scrollHeight,
      windowWidth: 1300,
      windowHeight: body.scrollHeight,
    });
  }

  // ===== PDF chrome (header + footer on each page) =====

  function drawHeader(pdf, opts) {
    const pdfW = pdf.internal.pageSize.getWidth();
    // Navy header band, 34pt tall
    pdf.setFillColor(NAVY);
    pdf.rect(0, 0, pdfW, 34, 'F');
    // Wordmark
    pdf.setFont('helvetica', 'bold');
    pdf.setTextColor(255, 255, 255);
    pdf.setFontSize(13);
    pdf.text('Dispensary', 28, 22);
    pdf.setTextColor(31, 212, 168); // teal
    const dw = pdf.getTextWidth('Dispensary');
    pdf.text('IQ', 28 + dw, 22);
    // Right: pilot meta
    pdf.setFont('helvetica', 'normal');
    pdf.setTextColor(255, 255, 255);
    pdf.setFontSize(9);
    const meta = opts.pilotMeta || 'Pilot Week 20 · 2026-05-18';
    pdf.text(meta, pdfW - 28, 22, {align: 'right'});
    // Thin teal accent line
    pdf.setDrawColor(31, 212, 168);
    pdf.setLineWidth(1.2);
    pdf.line(0, 34, pdfW, 34);
  }

  function drawFooter(pdf, opts) {
    const pdfW = pdf.internal.pageSize.getWidth();
    const pdfH = pdf.internal.pageSize.getHeight();
    // Footer line
    pdf.setDrawColor(229, 231, 235);
    pdf.setLineWidth(0.5);
    pdf.line(28, pdfH - 26, pdfW - 28, pdfH - 26);
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(8);
    // Left: confidential tagline
    pdf.setTextColor(107, 114, 128);
    pdf.text('Cohort-stratified  ·  License-reconciled  ·  Fair-share-anchored  ·  CPG-native', 28, pdfH - 14);
    // Right: page X of Y · page name
    const right = `Page ${opts.pageNum} of ${opts.totalPages}  ·  ${opts.pageName}`;
    pdf.setTextColor(59, 66, 88);
    pdf.text(right, pdfW - 28, pdfH - 14, {align: 'right'});
  }

  function drawCover(pdf, opts) {
    const pdfW = pdf.internal.pageSize.getWidth();
    const pdfH = pdf.internal.pageSize.getHeight();
    // Full-page navy
    pdf.setFillColor(NAVY);
    pdf.rect(0, 0, pdfW, pdfH, 'F');
    // Wordmark center-top
    pdf.setFont('helvetica', 'bold');
    pdf.setFontSize(34);
    pdf.setTextColor(255, 255, 255);
    pdf.text('Dispensary', pdfW / 2 - 86, pdfH / 2 - 30);
    pdf.setTextColor(31, 212, 168);
    pdf.text('IQ', pdfW / 2 + 92, pdfH / 2 - 30);
    // Tagline
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(11);
    pdf.setTextColor(180, 186, 204);
    pdf.text('Weekly intelligence pack', pdfW / 2, pdfH / 2 - 2, {align: 'center'});
    pdf.text('Prepared for Curaleaf  ·  ' + opts.pilotMeta, pdfW / 2, pdfH / 2 + 18, {align: 'center'});
    // Pillars at bottom
    pdf.setFontSize(8);
    pdf.setTextColor(122, 128, 153);
    pdf.text('COHORT-STRATIFIED   ·   LICENSE-RECONCILED   ·   FAIR-SHARE-ANCHORED   ·   CPG-NATIVE',
             pdfW / 2, pdfH - 50, {align: 'center'});
  }

  // ===== PDF — combined, publication-grade =====

  window.diqExportPDF = async function() {
    showModal('Generating PDF', `Capturing all ${PAGES.length} pages, forcing light theme, formatting with chrome. ~45–90 seconds.`);
    try {
      await ensureLibs(false);
      const { jsPDF } = window.jspdf;

      // Letter portrait
      const pdf = new jsPDF({orientation: 'portrait', unit: 'pt', format: 'letter'});
      const pdfW = pdf.internal.pageSize.getWidth();   // 612
      const pdfH = pdf.internal.pageSize.getHeight();  // 792

      const margin     = 28;
      const headerH    = 34;
      const footerH    = 32;
      const contentW   = pdfW - 2 * margin;
      const contentH   = pdfH - headerH - footerH - 2 * (margin - 14);  // ~700pt
      const contentY0  = headerH + (margin - 14);
      const contentX0  = margin;

      const pilotMeta = `Pilot Week 20 · ${dateStr()}`;

      const stage = document.createElement('iframe');
      stage.className = 'diq-export-iframe-stage';
      document.body.appendChild(stage);

      // Pass 1: capture all canvases first, so we can compute total PDF pages
      const canvases = [];
      for (let i = 0; i < PAGES.length; i++) {
        updateProgress(Math.round((i / PAGES.length) * 70), `Capturing ${i+1} of ${PAGES.length}: ${PAGES[i].name}`);
        canvases.push(await captureIframePage(stage, PAGES[i].file));
      }
      stage.remove();

      // Compute layout per page — how many PDF pages each site-page needs
      const layouts = canvases.map((canvas, i) => {
        const aspect = canvas.height / canvas.width;
        // Try fitting full canvas at content width
        const fittedH = contentW * aspect;
        if (fittedH <= contentH * 1.05) {
          // Fits 1 PDF page (allow 5% slop)
          return {numPages: 1, fittedW: contentW, fittedH};
        }
        // If aspect ratio is moderate (canvas <= 2.2x as tall as wide proportionally), split into 2 PDF pages
        if (fittedH <= contentH * 2.0) {
          return {numPages: 2, fittedW: contentW, fittedH};
        }
        // Very tall pages get up to 3 PDF pages
        return {numPages: 3, fittedW: contentW, fittedH};
      });

      const totalPdfPages = 1 + layouts.reduce((s, L) => s + L.numPages, 0); // +1 cover

      updateProgress(72, 'Rendering cover page');
      // Cover page
      drawCover(pdf, {pilotMeta});

      let pdfPageNum = 1; // cover = 1

      // Pass 2: render canvases onto PDF pages with chrome
      for (let i = 0; i < canvases.length; i++) {
        const canvas = canvases[i];
        const page = PAGES[i];
        const L = layouts[i];
        const dataUrl = canvas.toDataURL('image/png');

        for (let p = 0; p < L.numPages; p++) {
          pdf.addPage();
          pdfPageNum += 1;
          updateProgress(72 + Math.round(((i * 3 + p) / (canvases.length * 3)) * 24),
                         `Laying out PDF page ${pdfPageNum} of ${totalPdfPages}: ${page.name}`);

          drawHeader(pdf, {pilotMeta, pageName: page.name});
          drawFooter(pdf, {pageNum: pdfPageNum, totalPages: totalPdfPages, pageName: page.name});

          // Centered image, shift up by p * contentH for multi-page splits
          const xOff = contentX0 + (contentW - L.fittedW) / 2;
          const yOff = contentY0 - p * contentH;
          pdf.addImage(dataUrl, 'PNG', xOff, yOff, L.fittedW, L.fittedH, undefined, 'FAST');

          // Clip painted content to content area by drawing solid header/footer bars on top
          // (jsPDF doesn't support true clipping in this version cleanly; chrome overpaints any spill)
          // Repaint footer area to mask any image spill beyond bottom margin:
          pdf.setFillColor(255, 255, 255);
          pdf.rect(0, pdfH - footerH, pdfW, footerH, 'F');
          drawFooter(pdf, {pageNum: pdfPageNum, totalPages: totalPdfPages, pageName: page.name});
          // Also re-paint header to mask any spill above content
          pdf.setFillColor(255, 255, 255);
          pdf.rect(0, headerH, pdfW, contentY0 - headerH, 'F');
          drawHeader(pdf, {pilotMeta, pageName: page.name});
        }
      }

      updateProgress(98, 'Saving PDF');
      const filename = `DispensaryIQ-${dateStr()}.pdf`;
      pdf.save(filename);
      updateProgress(100, 'Complete');
      finishModal(`Downloaded <code style="background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:3px;font-family:Consolas,monospace;font-size:11px">${filename}</code> — ${totalPdfPages} pages (1 cover + ${totalPdfPages - 1} content).`);
    } catch (e) {
      console.error(e);
      failModal(e.message || 'Unknown error during PDF export.');
    }
  };

  // ===== PNG — ZIP of individual pages =====

  window.diqExportPNG = async function() {
    showModal('Generating image pack', `Capturing all ${PAGES.length} pages as individual PNGs and bundling into a ZIP. ~30–60 seconds.`);
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
        zip.file(`${seq}-${page.name.replace(/\s/g, '-')}.png`, blob);
      }
      stage.remove();

      updateProgress(94, 'Building ZIP archive');
      const zipBlob = await zip.generateAsync({type: 'blob'}, (meta) => {
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

  window.diqExportAll = window.diqExportPDF; // legacy alias
})();
