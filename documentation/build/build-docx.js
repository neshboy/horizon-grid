const fs = require('fs');
const path = require('path');
const HTMLtoDOCX = require('html-to-docx');
const JSZip = require('jszip');

const OUT_DIR = __dirname;
const FINAL_DOCX = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\FINAL_PRODUCT_DOCUMENTATION.docx';
const { frontSections, techSections } = JSON.parse(fs.readFileSync(path.join(OUT_DIR, 'sections.json'), 'utf8'));

const VERSION = '0.2.5';
const TODAY = '2026-08-23';
const INSTALLER_FILENAME = `HORIZON-GRID-Setup-${VERSION}.exe`;
const INSTALLER_SHA256 = '98dee90cfb16a9c9b2bd56611ba024225fa0261c20386765171fe79e01d198c2';

const TOC_MARKER = 'ZZTOCPLACEHOLDERZZ';

function toBase64Images(html) {
  return html.replace(/src="file:\/\/\/([^"]+)"/g, (_, filePath) => {
    const normalized = decodeURIComponent(filePath);
    const buf = fs.readFileSync(normalized);
    const ext = path.extname(normalized).slice(1) || 'png';
    return `src="data:image/${ext};base64,${buf.toString('base64')}"`;
  });
}

function sectionsHtml(sections) {
  return sections
    .map((s, i) => {
      const pageBreak = i === 0 ? '' : '<div class="page-break" style="page-break-after: always"></div>';
      return `${pageBreak}<h1>${s.title}</h1>${toBase64Images(s.html)}`;
    })
    .join('\n');
}

const coverHtml = `
<div style="text-align:center; margin-top:220px;">
  <p style="letter-spacing:3px; color:#7fa6f5;">PRODUCT DOCUMENTATION</p>
  <h1 style="font-size:32pt; margin-bottom:4px;">HORIZON GRID</h1>
  <p style="font-size:13pt;">Every Signal. One Operational Picture.</p>
  <br/>
  <p><strong>Version:</strong> ${VERSION}</p>
  <p><strong>Windows Installer:</strong> ${INSTALLER_FILENAME}</p>
  <p><strong>Installer SHA-256:</strong> ${INSTALLER_SHA256}</p>
  <p><strong>Documentation prepared:</strong> ${TODAY}</p>
  <br/>
  <p style="letter-spacing:1px;">PREPARED FOR EVALUATION</p>
</div>
<div class="page-break" style="page-break-after: always"></div>
`;

const tocHtml = `
<h1>Table of Contents</h1>
<p>${TOC_MARKER}</p>
<div class="page-break" style="page-break-after: always"></div>
`;

const fullHtml = `<!doctype html>
<html><head><meta charset="utf-8" /></head>
<body>
${coverHtml}
${tocHtml}
${sectionsHtml(frontSections)}
<div class="page-break" style="page-break-after: always"></div>
${sectionsHtml(techSections)}
</body></html>`;

// Real Word TOC field -- auto-populates page numbers (and stays clickable/
// navigable) the moment the reader opens the document in Word, rather than
// a static list of numbers that would only ever be correct for one
// specific pagination. Word shows "Right-click > Update Field" (or updates
// automatically depending on the user's settings) instead of a manual
// re-typed number list.
const TOC_FIELD_XML =
  '<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr><w:sdtContent>' +
  '<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>' +
  '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-1" \\h \\z \\u </w:instrText></w:r>' +
  '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' +
  '<w:r><w:t>Right-click here and choose "Update Field" (or press F9) to generate the Table of Contents.</w:t></w:r>' +
  '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>' +
  '</w:sdtContent></w:sdt>';

async function main() {
  console.log('Generating DOCX via html-to-docx...');
  const buffer = await HTMLtoDOCX(fullHtml, null, {
    table: { row: { cantSplit: true } },
    footer: true,
    pageNumber: true,
    title: 'HORIZON GRID -- Product Documentation',
    creator: 'HORIZON GRID Documentation',
    margins: { top: 1000, right: 900, bottom: 1000, left: 900 },
  });

  console.log('Injecting real Word TOC field...');
  const zip = await JSZip.loadAsync(buffer);
  const docXmlPath = 'word/document.xml';
  let docXml = await zip.file(docXmlPath).async('string');

  const markerParagraphRe = new RegExp(`<w:p[^>]*>(?:(?!<\\/w:p>)[\\s\\S])*${TOC_MARKER}[\\s\\S]*?<\\/w:p>`);
  if (!markerParagraphRe.test(docXml)) {
    throw new Error('TOC marker paragraph not found in generated document.xml -- cannot inject TOC field');
  }
  docXml = docXml.replace(markerParagraphRe, TOC_FIELD_XML);
  zip.file(docXmlPath, docXml);

  // Word needs to be told there ARE fields that may require updating on
  // open, otherwise some versions silently show the placeholder text
  // instead of prompting to build the TOC.
  const settingsPath = 'word/settings.xml';
  let settingsXml = await zip.file(settingsPath).async('string');
  if (!settingsXml.includes('updateFields')) {
    settingsXml = settingsXml.replace('<w:settings', '<w:settings').replace(
      /(<w:settings[^>]*>)/,
      '$1<w:updateFields w:val="true"/>'
    );
    zip.file(settingsPath, settingsXml);
  }

  const finalBuffer = await zip.generateAsync({ type: 'nodebuffer' });
  fs.writeFileSync(FINAL_DOCX, finalBuffer);
  console.log('Wrote', FINAL_DOCX, finalBuffer.length, 'bytes');
}

main().catch((e) => { console.error('FATAL:', e); process.exit(1); });
