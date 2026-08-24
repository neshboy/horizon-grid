// Generic, parameterized version of assemble.js + build-html.js + render-pdf.js
// + build-docx.js, used to produce the THREE additional standalone documents
// (User Manual / Source Code Documentation / Backend Documentation) without
// touching the original four scripts, which continue to produce the existing
// combined FINAL_PRODUCT_DOCUMENTATION.pdf/docx exactly as before.
const fs = require('fs');
const path = require('path');
const { marked } = require('marked');
const sizeOf = require('image-size').default ?? require('image-size');
const puppeteer = require('puppeteer-core');
const { PDFParse } = require('pdf-parse');
const HTMLtoDOCX = require('html-to-docx');
const JSZip = require('jszip');

const SRC = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\DOCUMENTATION_SOURCE';
const SHOTS_DIR = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\SCREENSHOTS';
const DIAGRAMS_DIR = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\ARCHITECTURE_DIAGRAMS';
const OUT_DIR = 'C:\\Users\\User\\ioc-intel-platform\\documentation';
const TODAY = '2026-08-24';
const VERSION = '0.3.0';

const CONTENT_WIDTH_PX = 700;
const CONTENT_HEIGHT_PX = 860;

const CHROME_PATHS = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];

function slugify(title) {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}

function resolveFigurePath(filename) {
  if (/-diagram-\d+\.png$/.test(filename)) return path.join(DIAGRAMS_DIR, filename).replace(/\\/g, '/');
  return path.join(SHOTS_DIR, filename).replace(/\\/g, '/');
}

function replaceFigures(markdown, sourceFile, figureState) {
  return markdown.replace(/\[FIGURE:\s*([^\|\]]+?)\s*\|\s*([^\]]+?)\]/g, (_, filename, caption) => {
    figureState.counter += 1;
    const n = figureState.counter;
    const filePath = resolveFigurePath(filename.trim());
    if (!fs.existsSync(filePath)) {
      console.error(`MISSING FIGURE FILE: ${filePath} (referenced in ${sourceFile})`);
      return `\n<p style="color:red;">[MISSING FIGURE: ${filename.trim()}]</p>\n`;
    }
    let tall = false;
    try {
      const { width, height } = sizeOf(fs.readFileSync(filePath));
      const printedHeight = height * (CONTENT_WIDTH_PX / width);
      tall = printedHeight > CONTENT_HEIGHT_PX;
    } catch (e) {
      console.error(`Could not read dimensions for ${filePath}: ${e.message}`);
    }
    const fileUrl = 'file:///' + filePath;
    const figClass = tall ? 'doc-figure doc-figure-tall' : 'doc-figure';
    return `\n<figure class="${figClass}">\n<img src="${fileUrl}" alt="Figure ${n}" />\n<figcaption><strong>Figure ${n} &mdash; </strong>${caption.trim()}</figcaption>\n</figure>\n`;
  });
}

function splitIntoH1Sections(markdown) {
  const lines = markdown.split(/\r?\n/);
  const sections = [];
  let current = null;
  let inFence = false;
  for (const line of lines) {
    if (/^```/.test(line)) inFence = !inFence;
    const h1 = !inFence && line.match(/^#\s+(.+)$/);
    if (h1) {
      if (current) sections.push(current);
      current = { title: h1[1].trim(), bodyLines: [] };
    } else if (current) {
      current.bodyLines.push(line);
    }
  }
  if (current) sections.push(current);
  return sections.map((s) => ({ title: s.title, body: s.bodyLines.join('\n') }));
}

function buildSectionsHtml(files, figureState) {
  const logicalSections = [];
  for (const file of files) {
    const fullPath = path.join(SRC, file);
    if (!fs.existsSync(fullPath)) {
      console.error(`MISSING SOURCE FILE: ${fullPath}`);
      continue;
    }
    const raw = fs.readFileSync(fullPath, 'utf8');
    const withFigures = replaceFigures(raw, file, figureState);
    const h1Sections = splitIntoH1Sections(withFigures);
    for (const sec of h1Sections) {
      const anchor = slugify(sec.title);
      const bodyHtml = marked.parse(sec.body);
      logicalSections.push({ title: sec.title, anchor, html: bodyHtml, sourceFile: file });
    }
  }
  return logicalSections;
}

const CSS = `
  @page { size: A4; margin: 135px 45px 80px 45px; }
  * { box-sizing: border-box; }
  body { font-family: "Segoe UI", Arial, Helvetica, sans-serif; color: #1a1d23; font-size: 11.5px; line-height: 1.55; margin: 0; }
  .page-content { padding: 6px 8px 0 8px; }
  h1 { font-size: 22px; color: #1447c9; border-bottom: 2px solid #2563eb; padding-bottom: 8px; padding-top: 16px; margin-top: 0; margin-bottom: 16px; page-break-after: avoid; }
  h2 { font-size: 16px; color: #16181d; padding-top: 22px; margin-top: 0; margin-bottom: 10px; }
  h3 { font-size: 13px; color: #2b2f38; padding-top: 18px; margin-top: 0; margin-bottom: 8px; }
  p { margin: 0 0 10px 0; }
  ul, ol { margin: 0 0 10px 0; padding-left: 22px; }
  li { margin-bottom: 4px; }
  a { color: #1447c9; text-decoration: none; }
  strong { color: #10131a; }
  code { font-family: "Consolas", "Courier New", monospace; background: #f0f2f5; border: 1px solid #dde1e8; border-radius: 3px; padding: 1px 4px; font-size: 10.5px; }
  pre { background: #0f1115; color: #e6e6eb; border-radius: 6px; padding: 12px 14px; overflow-x: auto; font-size: 10px; page-break-inside: avoid; }
  pre code { background: none; border: none; color: inherit; padding: 0; }
  table { border-collapse: collapse; width: 100%; margin: 10px 0 16px 0; font-size: 10px; page-break-inside: avoid; }
  th, td { border: 1px solid #d5d9e0; padding: 5px 8px; text-align: left; vertical-align: top; }
  th { background: #eef1f7; color: #10131a; font-weight: 600; }
  tr:nth-child(even) td { background: #f8f9fb; }
  blockquote { border-left: 3px solid #2563eb; margin: 10px 0; padding: 4px 14px; color: #444a55; font-style: italic; background: #f5f7fb; }
  figure.doc-figure { margin: 16px 0 16px 0; padding-top: 14px; text-align: center; page-break-inside: avoid; }
  figure.doc-figure img { max-width: 100%; max-height: 740px; width: auto; height: auto; border: 1px solid #d5d9e0; border-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  figure.doc-figure figcaption { font-size: 9.5px; color: #555b66; margin-top: 6px; text-align: left; padding: 0 20px; }
  .section { page-break-before: always; }
  .section:first-of-type { page-break-before: auto; }
  .cover { height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; background: linear-gradient(180deg, #0f1115 0%, #151823 100%); color: #ffffff; }
  .cover .kicker { font-size: 13px; letter-spacing: 3px; color: #7fa6f5; margin-bottom: 18px; text-transform: uppercase; }
  .cover h1 { font-size: 36px; color: #ffffff; border: none; margin: 0 0 14px 0; padding: 0; }
  .cover .subtitle { font-size: 15px; color: #c3cbdb; max-width: 560px; margin-bottom: 50px; }
  .cover .meta { font-size: 11px; color: #8f97ab; line-height: 1.9; border-top: 1px solid #333a4d; padding-top: 20px; margin-top: 20px; }
  .cover .meta strong { color: #d7deee; }
  .cover .confidentiality { margin-top: 40px; font-size: 10.5px; color: #6c7488; letter-spacing: 1px; text-transform: uppercase; }
  .toc-row { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1px dotted #cfd4dd; padding: 2.5px 0; font-size: 11.5px; }
  .toc-row a { color: #16181d; }
  .toc-page { color: #555b66; font-size: 11px; padding-left: 10px; white-space: nowrap; }
  .sectionmark { font-size: 1px; color: #ffffff; line-height: 1px; display: inline-block; }
`;

function sectionMarker(idx) { return `<span class="sectionmark">SECTIONMARK_${idx}</span>`; }

function renderSectionsHtml(sections) {
  return sections
    .map((s, i) => `<div class="section" id="${s.anchor}">${sectionMarker(i)}<div class="page-content"><h1>${s.title}</h1>${s.html}</div></div>`)
    .join('\n');
}

function buildToc(sections, pageNumbers) {
  let html = '<div class="section toc"><div class="page-content"><h1>Table of Contents</h1>';
  sections.forEach((s, i) => {
    const pg = pageNumbers ? (pageNumbers[i] ?? '') : '&hellip;';
    html += `<div class="toc-row"><a href="#${s.anchor}">${s.title}</a><span class="toc-page">${pg}</span></div>`;
  });
  html += '</div></div>';
  return html;
}

function buildCover(cfg) {
  return `
  <div class="cover">
    <div class="kicker">${cfg.kicker}</div>
    <h1>${cfg.title}</h1>
    <div class="subtitle">${cfg.subtitle}</div>
    <div class="meta">
      <div><strong>Version:</strong> ${VERSION}</div>
      <div><strong>Documentation prepared:</strong> ${TODAY}</div>
    </div>
    <div class="confidentiality">Prepared for Evaluation</div>
  </div>`;
}

function buildFullHtml(cfg, sections, pageNumbers) {
  return `<!doctype html>
<html><head><meta charset="utf-8" /><style>${CSS}</style></head>
<body>
${buildCover(cfg)}
${buildToc(sections, pageNumbers)}
${renderSectionsHtml(sections)}
</body></html>`;
}

async function renderPdfPage(browser, htmlPath, outPath, cfg) {
  const page = await browser.newPage();
  await page.goto('file:///' + htmlPath.replace(/\\/g, '/'), { waitUntil: 'load' });
  // Header must reflect THIS document's own title/subtitle, not a hardcoded
  // guess -- confirmed live via a real generated PDF that the previous
  // ternary (BACKEND/SOURCE_CODE/else "User Manual") silently mislabeled
  // every one of the other ~18 documents in this package as "User Manual"
  // under the old product name, in the actual page header of every page.
  const headerTitle = cfg?.title ?? 'HORIZON GRID';
  const headerSubtitle = cfg?.subtitle ?? '';
  await page.pdf({
    path: outPath,
    format: 'A4',
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: `<div style="font-family:'Segoe UI',Arial,sans-serif;font-size:8px;color:#8a8f99;width:100%;padding:0 40px;display:flex;justify-content:space-between;"><span>${headerTitle}</span><span>${headerSubtitle}</span></div>`,
    footerTemplate: `<div style="font-family:'Segoe UI',Arial,sans-serif;font-size:8px;color:#8a8f99;width:100%;padding:0 40px;display:flex;justify-content:space-between;"><span>Prepared for Evaluation</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`,
    margin: { top: '135px', bottom: '80px', left: '45px', right: '45px' },
  });
  await page.close();
}

async function findSectionPageNumbers(pdfPath, totalMarkers) {
  const buf = fs.readFileSync(pdfPath);
  const parser = new PDFParse({ data: buf });
  const result = await parser.getText();
  await parser.destroy();
  const pageNumbers = {};
  for (let i = 0; i < totalMarkers; i++) {
    const marker = `SECTIONMARK_${i}`;
    const page = result.pages.find((p) => p.text.includes(marker));
    pageNumbers[i] = page ? page.num : null;
  }
  return pageNumbers;
}

function toBase64Images(html) {
  return html.replace(/src="file:\/\/\/([^"]+)"/g, (_, filePath) => {
    const normalized = decodeURIComponent(filePath);
    const buf = fs.readFileSync(normalized);
    const ext = path.extname(normalized).slice(1) || 'png';
    return `src="data:image/${ext};base64,${buf.toString('base64')}"`;
  });
}

async function buildDocx(cfg, sections) {
  const TOC_MARKER = 'ZZTOCPLACEHOLDERZZ';
  const sectionsHtml = sections
    .map((s, i) => {
      const pageBreak = i === 0 ? '' : '<div class="page-break" style="page-break-after: always"></div>';
      return `${pageBreak}<h1>${s.title}</h1>${toBase64Images(s.html)}`;
    })
    .join('\n');
  const coverHtml = `
  <div style="text-align:center; margin-top:220px;">
    <p style="letter-spacing:3px; color:#7fa6f5;">${cfg.kicker.toUpperCase()}</p>
    <h1 style="font-size:30pt; margin-bottom:4px;">${cfg.title}</h1>
    <p style="font-size:13pt;">${cfg.subtitle}</p>
    <br/>
    <p><strong>Version:</strong> ${VERSION}</p>
    <p><strong>Documentation prepared:</strong> ${TODAY}</p>
    <br/>
    <p style="letter-spacing:1px;">PREPARED FOR EVALUATION</p>
  </div>
  <div class="page-break" style="page-break-after: always"></div>`;
  const tocHtml = `<h1>Table of Contents</h1><p>${TOC_MARKER}</p><div class="page-break" style="page-break-after: always"></div>`;
  const fullHtml = `<!doctype html><html><head><meta charset="utf-8" /></head><body>${coverHtml}${tocHtml}${sectionsHtml}</body></html>`;

  const TOC_FIELD_XML =
    '<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr><w:sdtContent>' +
    '<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>' +
    '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-1" \\h \\z \\u </w:instrText></w:r>' +
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' +
    '<w:r><w:t>Right-click here and choose "Update Field" (or press F9) to generate the Table of Contents.</w:t></w:r>' +
    '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>' +
    '</w:sdtContent></w:sdt>';

  const buffer = await HTMLtoDOCX(fullHtml, null, {
    table: { row: { cantSplit: true } },
    footer: true,
    pageNumber: true,
    title: `${cfg.title} -- ${cfg.subtitle}`,
    creator: 'HORIZON GRID Documentation',
    margins: { top: 1000, right: 900, bottom: 1000, left: 900 },
  });

  const zip = await JSZip.loadAsync(buffer);
  const docXmlPath = 'word/document.xml';
  let docXml = await zip.file(docXmlPath).async('string');
  const markerParagraphRe = new RegExp(`<w:p[^>]*>(?:(?!<\\/w:p>)[\\s\\S])*${TOC_MARKER}[\\s\\S]*?<\\/w:p>`);
  if (!markerParagraphRe.test(docXml)) throw new Error('TOC marker paragraph not found');
  docXml = docXml.replace(markerParagraphRe, TOC_FIELD_XML);
  zip.file(docXmlPath, docXml);

  const settingsPath = 'word/settings.xml';
  let settingsXml = await zip.file(settingsPath).async('string');
  if (!settingsXml.includes('updateFields')) {
    settingsXml = settingsXml.replace(/(<w:settings[^>]*>)/, '$1<w:updateFields w:val="true"/>');
    zip.file(settingsPath, settingsXml);
  }
  return zip.generateAsync({ type: 'nodebuffer' });
}

async function buildOne(cfg) {
  console.log(`\n=== Building ${cfg.docName} ===`);
  const figureState = { counter: 0 };
  const sections = buildSectionsHtml(cfg.files, figureState);
  console.log(`  ${sections.length} sections, ${figureState.counter} figures`);

  const pdfOut = path.join(OUT_DIR, `${cfg.docName}.pdf`);
  const docxOut = path.join(OUT_DIR, `${cfg.docName}.docx`);

  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  const browser = await puppeteer.launch({ executablePath: execPath, headless: 'new' });

  const pass1Html = buildFullHtml(cfg, sections, null);
  const pass1HtmlPath = path.join(OUT_DIR, 'build', `${cfg.docName}-pass1.html`);
  fs.writeFileSync(pass1HtmlPath, pass1Html, 'utf8');
  const pass1Pdf = path.join(OUT_DIR, 'build', `${cfg.docName}-pass1.pdf`);
  await renderPdfPage(browser, pass1HtmlPath, pass1Pdf, cfg);

  const pageNumbers = await findSectionPageNumbers(pass1Pdf, sections.length);
  const missing = Object.entries(pageNumbers).filter(([, v]) => v === null);
  if (missing.length) console.error('  WARNING: missing page numbers for:', missing.map(([k]) => k));

  const pass2Html = buildFullHtml(cfg, sections, pageNumbers);
  const pass2HtmlPath = path.join(OUT_DIR, 'build', `${cfg.docName}-final.html`);
  fs.writeFileSync(pass2HtmlPath, pass2Html, 'utf8');
  await renderPdfPage(browser, pass2HtmlPath, pdfOut, cfg);
  console.log(`  PDF: ${pdfOut} (${fs.statSync(pdfOut).size} bytes)`);

  await browser.close();

  const docxBuffer = await buildDocx(cfg, sections);
  fs.writeFileSync(docxOut, docxBuffer);
  console.log(`  DOCX: ${docxOut} (${fs.statSync(docxOut).size} bytes)`);
}

module.exports = { buildOne };

if (require.main === module) {
  const configPath = process.argv[2];
  if (!configPath) {
    console.error('Usage: node build-doc-generic.js <config.json>');
    process.exit(1);
  }
  const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  buildOne(cfg).catch((e) => { console.error('FATAL:', e); process.exit(1); });
}
