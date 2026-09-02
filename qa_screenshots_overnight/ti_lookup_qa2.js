// Follow-up pass: (1) redo the hash IOC test with a correctly-computed
// 64-char SHA256 (the first attempt used a mistyped 63-char string -- that
// was tester error, confirmed separately, not an app bug), and (2) test
// CSV/PDF export on the already-completed 8.8.8.8 lookup via /lookup/{id}
// (the first attempt navigated to /lookup/new without its ?value= param by
// mistake, which is a different, real page state, not the export UI).
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const OUT = __dirname;
const DOWNLOAD_DIR = path.join(OUT, 'downloads');
fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });

const FRONTEND = 'http://localhost:3000';
const CHROME_PATHS = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function mintToken() {
  const out = execSync(
    'docker exec app-backend-1 python -c "from app.auth.security import create_access_token; print(create_access_token(\'fuck@fuck.com\', \'admin\', 0))"',
    { encoding: 'utf-8' }
  );
  return out.trim();
}

let shotCounter = 18; // continue numbering after the first pass (01-18)
async function shot(page, name, full = true) {
  shotCounter += 1;
  const fname = `${String(shotCounter).padStart(2, '0')}-${name}.png`;
  await page.screenshot({ path: path.join(OUT, fname), fullPage: full });
  console.log('screenshot:', fname);
  return fname;
}

async function clickByText(page, selector, text) {
  const handles = await page.$$(selector);
  for (const h of handles) {
    const t = await page.evaluate((el) => el.textContent?.trim(), h);
    if (t && t.trim() === text) { await h.click(); return true; }
  }
  return false;
}

async function waitForLookupDone(page, timeoutMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const status = await page.evaluate(() => {
      const spans = Array.from(document.querySelectorAll('span'));
      const hit = spans.find((el) => ['complete'].includes(el.textContent?.trim()));
      const err = document.querySelector('.text-destructive');
      if (err) return 'ERROR:' + err.textContent;
      return hit ? hit.textContent.trim() : null;
    });
    if (status) return status;
    await sleep(1500);
  }
  return null;
}

async function main() {
  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  const token = mintToken();
  console.log('minted token (len):', token.length);

  const browser = await puppeteer.launch({
    executablePath: execPath,
    headless: 'new',
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();
  const client = await page.createCDPSession();
  await client.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: DOWNLOAD_DIR });

  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(500);

  // ============ Hash IOC re-test with a CORRECT 64-char SHA256 ============
  const goodHash = '275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f'; // real EICAR sha256, verified via crypto.createHash locally
  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  const input = await page.$('input[placeholder*="IOC"], input[placeholder*="IP, domain"]');
  await input.click({ clickCount: 3 });
  await input.type(goodHash, { delay: 15 });
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => window.location.pathname.startsWith('/lookup/new'), { timeout: 15000 });
  await sleep(1500);
  await shot(page, 'hash-v2-running');
  const hashStatus = await waitForLookupDone(page, 120000);
  console.log('hash v2 status:', hashStatus);
  await sleep(2000);
  await shot(page, 'hash-v2-complete-top', false);
  await shot(page, 'hash-v2-complete-full');
  const hashUrl = page.url();

  // ============ Export CSV / PDF on the already-completed 8.8.8.8 lookup ============
  const ipLookupId = 'ad8ea627-281d-42d3-81e0-be7282ab48b4';
  await page.goto(`${FRONTEND}/lookup/${ipLookupId}`, { waitUntil: 'networkidle2' });
  await sleep(2500);
  await shot(page, 'export-page-loaded');

  const before = fs.readdirSync(DOWNLOAD_DIR);
  const csvClicked = await clickByText(page, 'button', 'Export CSV');
  console.log('CSV export button clicked:', csvClicked);
  await sleep(4000);
  const afterCsv = fs.readdirSync(DOWNLOAD_DIR);
  await shot(page, 'export-after-csv-click', false);

  const pdfClicked = await clickByText(page, 'button', 'Export PDF');
  console.log('PDF export button clicked:', pdfClicked);
  await sleep(5000);
  const afterPdf = fs.readdirSync(DOWNLOAD_DIR);
  await shot(page, 'export-after-pdf-click', false);

  await browser.close();

  fs.writeFileSync(
    path.join(OUT, 'run-results-2.json'),
    JSON.stringify(
      { hashUrl, hashStatus, csvClicked, pdfClicked, before, afterCsv, afterPdf },
      null,
      2
    )
  );
  console.log('DONE.');
}

main().catch((err) => {
  console.error('FATAL:', err);
  process.exit(1);
});
