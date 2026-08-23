const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const SOURCE_DIR = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\DOCUMENTATION_SOURCE';
const DIAGRAMS_DIR = 'C:\\Users\\User\\ioc-intel-platform\\documentation\\ARCHITECTURE_DIAGRAMS';
const MERMAID_JS = path.join(__dirname, 'node_modules', 'mermaid', 'dist', 'mermaid.min.js');
fs.mkdirSync(DIAGRAMS_DIR, { recursive: true });

const CHROME_PATHS = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];

function findMermaidBlocks(content) {
  const blocks = [];
  const re = /```mermaid\r?\n([\s\S]*?)```/g;
  let m;
  while ((m = re.exec(content)) !== null) {
    // Find nearest preceding heading for a caption basis.
    const before = content.slice(0, m.index);
    const headingMatches = [...before.matchAll(/^#{1,3}\s+(.+)$/gm)];
    const heading = headingMatches.length ? headingMatches[headingMatches.length - 1][1].trim() : path.basename(content, '.md');
    blocks.push({ full: m[0], code: m[1], heading, index: m.index });
  }
  return blocks;
}

async function renderMermaid(page, code) {
  await page.evaluate(async (src) => {
    const { svg } = await window.mermaid.render('diagram-' + Math.random().toString(36).slice(2), src);
    document.body.innerHTML = svg;
  }, code);
  const svgHandle = await page.$('svg');
  if (!svgHandle) throw new Error('No SVG produced');
  // Give the SVG an explicit white background rectangle behind it so the
  // PNG isn't transparent (transparent renders as black in most PDF/DOCX
  // viewers against a dark page background otherwise).
  await page.evaluate(() => {
    const svg = document.querySelector('svg');
    svg.style.background = 'white';
  });
  const box = await svgHandle.boundingBox();
  return { svgHandle, box };
}

async function main() {
  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  const browser = await puppeteer.launch({ executablePath: execPath, headless: 'new' });
  const page = await browser.newPage();
  await page.setContent('<!doctype html><html><body></body></html>');
  await page.addScriptTag({ path: MERMAID_JS });
  await page.evaluate(() => {
    window.mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });
  });

  const files = fs.readdirSync(SOURCE_DIR).filter((f) => /^(tech|user|dev|backend)-\d+.*\.md$/.test(f));
  console.log('Scanning files:', files);

  const manifest = [];

  for (const file of files) {
    const fullPath = path.join(SOURCE_DIR, file);
    let content = fs.readFileSync(fullPath, 'utf8');
    const blocks = findMermaidBlocks(content);
    if (blocks.length === 0) continue;
    console.log(`\n${file}: ${blocks.length} diagram(s)`);

    const base = file.replace(/\.md$/, '');
    let newContent = content;
    for (let i = 0; i < blocks.length; i++) {
      const b = blocks[i];
      const diagramFile = `${base}-diagram-${i + 1}.png`;
      const diagramPath = path.join(DIAGRAMS_DIR, diagramFile);
      try {
        const { svgHandle, box } = await renderMermaid(page, b.code);
        await page.setViewport({
          width: Math.ceil(box.width) + 40,
          height: Math.ceil(box.height) + 40,
        });
        await svgHandle.screenshot({ path: diagramPath, omitBackground: false });
        console.log(`  rendered: ${diagramFile} (${Math.ceil(box.width)}x${Math.ceil(box.height)})`);
        manifest.push({ file, heading: b.heading, diagramFile, ok: true });
        const placeholder = `[FIGURE: ${diagramFile} | Diagram: ${b.heading}]`;
        newContent = newContent.replace(b.full, placeholder);
      } catch (err) {
        console.error(`  FAILED to render diagram ${i + 1} in ${file}:`, err.message);
        manifest.push({ file, heading: b.heading, diagramFile: null, ok: false, error: err.message });
      }
    }
    fs.writeFileSync(fullPath, newContent, 'utf8');
  }

  fs.writeFileSync(path.join(DIAGRAMS_DIR, '_manifest.json'), JSON.stringify(manifest, null, 2));
  console.log('\nDone. Manifest:', JSON.stringify(manifest, null, 2));

  await browser.close();
}

main().catch((e) => { console.error('FATAL:', e); process.exit(1); });
