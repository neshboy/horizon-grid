const fs = require('fs');
const path = require('path');

const OUT_DIR = __dirname;
const { frontSections, techSections } = JSON.parse(fs.readFileSync(path.join(OUT_DIR, 'sections.json'), 'utf8'));

const TODAY = '2026-08-24';
const VERSION = '0.3.0';
const INSTALLER_FILENAME = `HORIZON-GRID-Setup-${VERSION}.exe`;
const INSTALLER_SHA256 = '8faeb24586cde4a737d57e84ff3c836b48f2631cadab4526f0d6461403209def';

const CSS = `
  @page { size: A4; margin: 135px 45px 80px 45px; }
  * { box-sizing: border-box; }
  body {
    font-family: "Segoe UI", Arial, Helvetica, sans-serif;
    color: #1a1d23;
    font-size: 11.5px;
    line-height: 1.55;
    margin: 0;
  }
  .page-content { padding: 6px 8px 0 8px; }
  /*
   * Top spacing on headings uses padding-top, not margin-top. A margin at
   * the very top of an element that lands at the start of a fresh printed
   * page collapses to zero in Chrome's print engine (a standard CSS
   * print-pagination behavior), which let headings render flush against
   * the page's reserved header band -- confirmed by a real page (h3 "The
   * First Few Seconds", naturally pushed to a new page by page-break-after:
   * avoid ahead of a large figure) where the heading rendered ABOVE the
   * running header text. Padding is inside the box and never collapses,
   * so it reserves the same clearance whether or not the heading happens
   * to start a page.
   */
  h1 {
    font-size: 22px;
    color: #1447c9;
    border-bottom: 2px solid #2563eb;
    padding-bottom: 8px;
    padding-top: 16px;
    margin-top: 0;
    margin-bottom: 16px;
    page-break-after: avoid;
  }
  /*
   * h2/h3 deliberately do NOT set page-break-after: avoid. Chrome's print
   * pagination combines that with page-break-inside:avoid on a following
   * large figure in a way that miscalculates the pushed-to-next-page
   * position -- confirmed live: a heading pushed to the top of a new page
   * by that combination rendered its text ABOVE the page's own running
   * header instead of below it. An occasional heading left as the last
   * line on a page is a much smaller cosmetic issue than that overlap.
   */
  h2 { font-size: 16px; color: #16181d; padding-top: 22px; margin-top: 0; margin-bottom: 10px; }
  h3 { font-size: 13px; color: #2b2f38; padding-top: 18px; margin-top: 0; margin-bottom: 8px; }
  p { margin: 0 0 10px 0; }
  ul, ol { margin: 0 0 10px 0; padding-left: 22px; }
  li { margin-bottom: 4px; }
  a { color: #1447c9; text-decoration: none; }
  strong { color: #10131a; }
  code {
    font-family: "Consolas", "Courier New", monospace;
    background: #f0f2f5;
    border: 1px solid #dde1e8;
    border-radius: 3px;
    padding: 1px 4px;
    font-size: 10.5px;
  }
  pre {
    background: #0f1115;
    color: #e6e6eb;
    border-radius: 6px;
    padding: 12px 14px;
    overflow-x: auto;
    font-size: 10px;
    page-break-inside: avoid;
  }
  pre code { background: none; border: none; color: inherit; padding: 0; }
  table {
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0 16px 0;
    font-size: 10px;
    page-break-inside: avoid;
  }
  th, td { border: 1px solid #d5d9e0; padding: 5px 8px; text-align: left; vertical-align: top; }
  th { background: #eef1f7; color: #10131a; font-weight: 600; }
  tr:nth-child(even) td { background: #f8f9fb; }
  blockquote {
    border-left: 3px solid #2563eb;
    margin: 10px 0;
    padding: 4px 14px;
    color: #444a55;
    font-style: italic;
    background: #f5f7fb;
  }
  figure.doc-figure {
    margin: 16px 0 16px 0;
    padding-top: 14px;
    text-align: center;
    page-break-inside: avoid;
  }
  /*
   * Every figure's image is capped at a height that fits within one
   * printed page (with room left for its caption), never just width-
   * capped. An image taller than one page combined with page-break-
   * inside:avoid made Chrome's print engine skip one or more entirely
   * blank pages while failing to find a single page the whole image
   * could fit on whole, confirmed live across three independent large
   * diagrams/screenshots (each produced its own run of 2-3 blank pages).
   * Capping height so every figure fits on one page by construction
   * removes the failure condition instead of fighting the pagination
   * heuristic that triggers it. Large images render smaller as a result;
   * legible detail already exists in the smaller, non-"full" companion
   * figures placed alongside each of these.
   */
  figure.doc-figure img {
    max-width: 100%;
    max-height: 740px;
    width: auto;
    height: auto;
    border: 1px solid #d5d9e0;
    border-radius: 4px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  }
  figure.doc-figure figcaption {
    font-size: 9.5px;
    color: #555b66;
    margin-top: 6px;
    text-align: left;
    padding: 0 20px;
  }
  .section { page-break-before: always; }
  .section:first-of-type { page-break-before: auto; }
  .cover {
    height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    background: linear-gradient(180deg, #0f1115 0%, #151823 100%);
    color: #ffffff;
  }
  .cover .kicker { font-size: 13px; letter-spacing: 3px; color: #7fa6f5; margin-bottom: 18px; text-transform: uppercase; }
  .cover h1 { font-size: 40px; color: #ffffff; border: none; margin: 0 0 14px 0; padding: 0; }
  .cover .subtitle { font-size: 15px; color: #c3cbdb; max-width: 560px; margin-bottom: 50px; }
  .cover .meta { font-size: 11px; color: #8f97ab; line-height: 1.9; border-top: 1px solid #333a4d; padding-top: 20px; margin-top: 20px; }
  .cover .meta strong { color: #d7deee; }
  .cover .confidentiality { margin-top: 40px; font-size: 10.5px; color: #6c7488; letter-spacing: 1px; text-transform: uppercase; }

  .toc-part { font-size: 12px; text-transform: uppercase; letter-spacing: 1.5px; color: #2563eb; margin-top: 12px; margin-bottom: 4px; font-weight: 600; }
  .toc-row { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1px dotted #cfd4dd; padding: 2.5px 0; font-size: 11.5px; }
  .toc-row a { color: #16181d; }
  .toc-page { color: #555b66; font-size: 11px; padding-left: 10px; white-space: nowrap; }

  .sectionmark { font-size: 1px; color: #ffffff; line-height: 1px; display: inline-block; }
`;

function sectionMarker(idx) {
  return `<span class="sectionmark">SECTIONMARK_${idx}</span>`;
}

function renderSectionsHtml(sections, startIdx) {
  return sections
    .map((s, i) => {
      const idx = startIdx + i;
      return `<div class="section" id="${s.anchor}">${sectionMarker(idx)}<div class="page-content"><h1>${s.title}</h1>${s.html}</div></div>`;
    })
    .join('\n');
}

function buildToc(frontSections, techSections, pageNumbers) {
  const row = (s, idx) => {
    const pg = pageNumbers ? (pageNumbers[idx] ?? '') : '&hellip;';
    return `<div class="toc-row"><a href="#${s.anchor}">${s.title}</a><span class="toc-page">${pg}</span></div>`;
  };
  let html = '<div class="section toc"><div class="page-content"><h1>Table of Contents</h1>';
  html += '<div class="toc-part">Part I &mdash; Product Guide</div>';
  frontSections.forEach((s, i) => { html += row(s, i); });
  html += '<div class="toc-part">Part II &mdash; Technical Appendix</div>';
  techSections.forEach((s, i) => { html += row(s, frontSections.length + i); });
  html += '</div></div>';
  return html;
}

function buildCover() {
  return `
  <div class="cover">
    <div class="kicker">Product Documentation</div>
    <h1>HORIZON GRID</h1>
    <div class="subtitle">Every Signal. One Operational Picture.</div>
    <div class="meta">
      <div><strong>Version:</strong> ${VERSION}</div>
      <div><strong>Windows Installer:</strong> ${INSTALLER_FILENAME}</div>
      <div><strong>Installer SHA-256:</strong> ${INSTALLER_SHA256}</div>
      <div><strong>Documentation prepared:</strong> ${TODAY}</div>
    </div>
    <div class="confidentiality">Prepared for Evaluation</div>
  </div>`;
}

function buildFullHtml({ pageNumbers }) {
  const tocHtml = buildToc(frontSections, techSections, pageNumbers);
  const frontHtml = renderSectionsHtml(frontSections, 0);
  const techHtml = renderSectionsHtml(techSections, frontSections.length);
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>${CSS}</style>
</head>
<body>
${buildCover()}
${tocHtml}
${frontHtml}
${techHtml}
</body>
</html>`;
}

module.exports = { buildFullHtml, frontSections, techSections };

if (require.main === module) {
  const html = buildFullHtml({ pageNumbers: null });
  fs.writeFileSync(path.join(OUT_DIR, 'doc-pass1.html'), html, 'utf8');
  console.log('Wrote doc-pass1.html');
}
