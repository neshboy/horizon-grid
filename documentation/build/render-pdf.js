const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { PDFParse } = require('pdf-parse');
const { buildFullHtml, frontSections, techSections } = require('./build-html.js');

const OUT_DIR = __dirname;
const FINAL_PDF = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\FINAL_PRODUCT_DOCUMENTATION.pdf';

const CHROME_PATHS = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];

const HEADER_TEMPLATE = `
  <div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 8px; color: #8a8f99; width: 100%; padding: 0 40px; display: flex; justify-content: space-between;">
    <span>HORIZON GRID</span>
    <span>Product Documentation</span>
  </div>`;
const FOOTER_TEMPLATE = `
  <div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 8px; color: #8a8f99; width: 100%; padding: 0 40px; display: flex; justify-content: space-between;">
    <span>Prepared for Evaluation</span>
    <span><span class="pageNumber"></span> / <span class="totalPages"></span></span>
  </div>`;

async function renderPdf(browser, htmlPath, outPath) {
  const page = await browser.newPage();
  // Navigate to a real file:// URL (rather than page.setContent on
  // about:blank) so the document's own origin is file:// too -- otherwise
  // Chrome's cross-origin file-access sandboxing blocks the file:// <img>
  // src references used for every screenshot/diagram.
  await page.goto('file:///' + htmlPath.replace(/\\/g, '/'), { waitUntil: 'load' });
  await page.pdf({
    path: outPath,
    format: 'A4',
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: HEADER_TEMPLATE,
    footerTemplate: FOOTER_TEMPLATE,
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

async function main() {
  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  const browser = await puppeteer.launch({ executablePath: execPath, headless: 'new' });

  console.log('Pass 1: rendering with placeholder TOC page numbers...');
  const pass1Html = buildFullHtml({ pageNumbers: null });
  const pass1HtmlPath = path.join(OUT_DIR, 'doc-pass1.html');
  fs.writeFileSync(pass1HtmlPath, pass1Html, 'utf8');
  const pass1Pdf = path.join(OUT_DIR, 'pass1.pdf');
  await renderPdf(browser, pass1HtmlPath, pass1Pdf);

  console.log('Extracting section page numbers from pass 1...');
  const totalMarkers = frontSections.length + techSections.length;
  const pageNumbers = await findSectionPageNumbers(pass1Pdf, totalMarkers);
  console.log('Page numbers:', pageNumbers);

  const missing = Object.entries(pageNumbers).filter(([, v]) => v === null);
  if (missing.length) {
    console.error('WARNING: could not locate page number for section indices:', missing.map(([k]) => k));
  }

  console.log('Pass 2: rendering final PDF with real TOC page numbers...');
  const pass2Html = buildFullHtml({ pageNumbers });
  const pass2HtmlPath = path.join(OUT_DIR, 'doc-final.html');
  fs.writeFileSync(pass2HtmlPath, pass2Html, 'utf8');
  await renderPdf(browser, pass2HtmlPath, FINAL_PDF);

  await browser.close();
  console.log('\nFinal PDF written to:', FINAL_PDF);
  console.log('Size:', fs.statSync(FINAL_PDF).size, 'bytes');
}

main().catch((e) => { console.error('FATAL:', e); process.exit(1); });
