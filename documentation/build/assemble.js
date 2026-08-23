const fs = require('fs');
const path = require('path');
const { marked } = require('marked');
const sizeOf = require('image-size').default ?? require('image-size');

// Printed content area at the current A4 + margin settings in build-html.js
// (@page margin 135px top / 80px bottom / 45px sides) -- used to decide
// whether a figure can plausibly fit on one printed page at all. A figure
// taller than this, combined with page-break-inside:avoid, makes Chrome's
// print engine skip an entire blank page trying (and failing) to find a
// single page it fits on whole -- confirmed live on the Windows Deployment
// diagram (2547px source), which produced exactly one wasted blank page
// before the diagram anyway had to be split across two pages regardless.
const CONTENT_WIDTH_PX = 700;
const CONTENT_HEIGHT_PX = 860;

const SRC = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\DOCUMENTATION_SOURCE';
const SHOTS_DIR = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\SCREENSHOTS';
const DIAGRAMS_DIR = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\ARCHITECTURE_DIAGRAMS';
const OUT_DIR = __dirname;

const FRONT_FILES = [
  'user-01-front-matter.md',
  'user-02-user-journey.md',
  'user-03-installation.md',
  'user-04-first-run.md',
  'user-05-ioc-investigation.md',
  'user-06-providers.md',
  'user-07-ai-analysis.md',
  'user-08-evidence-correlation.md',
  'user-09-cases-basket.md',
  'user-10-export-reporting.md',
  'user-11-soc-workflow.md',
  'user-12-health-troubleshooting.md',
  'user-13-security-data-handling.md',
  'user-14-faq-best-practices-quick-reference.md',
];
const TECH_FILES = [
  'tech-01-architecture.md',
  'tech-02-dataflow.md',
  'tech-03-ai-architecture.md',
  'tech-04-provider-architecture.md',
  'tech-05-database-architecture.md',
  'tech-06-windows-deployment.md',
  'tech-07-security-architecture.md',
  'tech-08-testing-qa.md',
  'tech-09-performance.md',
  'tech-10-limitations.md',
  'tech-11-future-roadmap.md',
];

let figureCounter = 0;
const figureLog = [];

function slugify(title) {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}

function resolveFigurePath(filename) {
  if (/-diagram-\d+\.png$/.test(filename)) return path.join(DIAGRAMS_DIR, filename).replace(/\\/g, '/');
  return path.join(SHOTS_DIR, filename).replace(/\\/g, '/');
}

function replaceFigures(markdown, sourceFile) {
  return markdown.replace(/\[FIGURE:\s*([^\|\]]+?)\s*\|\s*([^\]]+?)\]/g, (_, filename, caption) => {
    figureCounter += 1;
    const n = figureCounter;
    const filePath = resolveFigurePath(filename.trim());
    if (!fs.existsSync(filePath)) {
      console.error(`MISSING FIGURE FILE: ${filePath} (referenced in ${sourceFile})`);
    }
    let tall = false;
    try {
      const { width, height } = sizeOf(fs.readFileSync(filePath));
      const printedHeight = height * (CONTENT_WIDTH_PX / width);
      tall = printedHeight > CONTENT_HEIGHT_PX;
    } catch (e) {
      console.error(`Could not read dimensions for ${filePath}: ${e.message}`);
    }
    figureLog.push({ n, filename: filename.trim(), sourceFile, tall });
    const fileUrl = 'file:///' + filePath;
    const figClass = tall ? 'doc-figure doc-figure-tall' : 'doc-figure';
    return `\n<figure class="${figClass}">\n<img src="${fileUrl}" alt="Figure ${n}" />\n<figcaption><strong>Figure ${n} &mdash; </strong>${caption.trim()}</figcaption>\n</figure>\n`;
  });
}

// Split a file's raw markdown into one chunk per top-level (H1) heading, so
// a file with 4 H1's (like the front-matter file) yields 4 independent,
// separately-paginated, separately-TOC'd logical sections.
function splitIntoH1Sections(markdown) {
  const lines = markdown.split(/\r?\n/);
  const sections = [];
  let current = null;
  for (const line of lines) {
    const h1 = line.match(/^#\s+(.+)$/);
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

function buildSectionsHtml(files, sourceLabel) {
  const logicalSections = [];
  for (const file of files) {
    const raw = fs.readFileSync(path.join(SRC, file), 'utf8');
    const withFigures = replaceFigures(raw, file);
    const h1Sections = splitIntoH1Sections(withFigures);
    for (const sec of h1Sections) {
      const anchor = slugify(sec.title);
      const bodyHtml = marked.parse(sec.body);
      logicalSections.push({ title: sec.title, anchor, html: bodyHtml, sourceFile: file });
    }
  }
  return logicalSections;
}

const frontSections = buildSectionsHtml(FRONT_FILES, 'front');
const techSections = buildSectionsHtml(TECH_FILES, 'tech');

console.log(`Front sections: ${frontSections.length}`);
frontSections.forEach((s) => console.log('  -', s.title));
console.log(`Tech sections: ${techSections.length}`);
techSections.forEach((s) => console.log('  -', s.title));
console.log(`Total figures: ${figureCounter}`);

fs.writeFileSync(
  path.join(OUT_DIR, 'sections.json'),
  JSON.stringify({ frontSections, techSections, figureLog }, null, 2)
);
console.log('\nWrote sections.json');
