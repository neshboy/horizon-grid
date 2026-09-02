// TI / IOC lookup end-to-end QA pass against the LIVE "app" stack
// (backend :8000, frontend :3000). Auth via a token minted server-side
// (docker exec app-backend-1 python -c "from app.auth.security import
// create_access_token ...") and injected into localStorage -- the raw
// password is never typed into this script.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const http = require('http');

const OUT = __dirname; // qa_screenshots_overnight
const DOWNLOAD_DIR = path.join(OUT, 'downloads');
fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });

const FRONTEND = 'http://localhost:3000';
const BACKEND = 'http://localhost:8000';

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

let shotCounter = 0;
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
    if (t && t.includes(text)) { await h.click(); return true; }
  }
  return false;
}

async function waitForLookupDone(page, timeoutMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const status = await page.evaluate(() => {
      const spans = Array.from(document.querySelectorAll('span'));
      const hit = spans.find((el) => ['completed', 'failed', 'complete'].includes(el.textContent?.trim()));
      return hit ? hit.textContent.trim() : null;
    });
    if (status) return status;
    await sleep(1500);
  }
  return null;
}

function apiGetJson(urlPath, token) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      BACKEND + urlPath,
      { headers: { Authorization: `Bearer ${token}` } },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          try {
            resolve({ status: res.statusCode, json: JSON.parse(data) });
          } catch (e) {
            resolve({ status: res.statusCode, raw: data });
          }
        });
      }
    );
    req.on('error', reject);
    req.end();
  });
}

async function submitLookupViaForm(page, value) {
  // Go to home, use the real search form (types the value, clicks Investigate)
  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await sleep(500);
  const input = await page.$('input[placeholder*="IOC"], input[placeholder*="IP, domain"]');
  if (!input) throw new Error('lookup input not found on home page');
  await input.click({ clickCount: 3 });
  await input.type(value, { delay: 20 });
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => window.location.pathname.startsWith('/lookup/new'), { timeout: 15000 });
  await sleep(1000);
}

async function main() {
  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  if (!execPath) throw new Error('No Chrome/Edge executable found');
  const token = mintToken();
  console.log('minted token (len):', token.length);

  const browser = await puppeteer.launch({
    executablePath: execPath,
    headless: 'new',
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();
  const client = await page.createCDPSession();
  await client.send('Page.setDownloadBehavior', {
    behavior: 'allow',
    downloadPath: DOWNLOAD_DIR,
  });

  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));

  // ---- Inject real auth ----
  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(500);
  await shot(page, 'home-logged-in');

  const results = {};

  // ============ IOC 1: IP 8.8.8.8 ============
  await submitLookupViaForm(page, '8.8.8.8');
  await shot(page, 'ip-8888-running');
  let status = await waitForLookupDone(page, 120000);
  console.log('8.8.8.8 done status:', status);
  await sleep(2000);
  const urlIp = page.url();
  const lookupIdIp = urlIp.split('/lookup/')[1]?.split('?')[0];
  await shot(page, 'ip-8888-complete-top', false);
  await shot(page, 'ip-8888-complete-full');
  results.ip = { url: urlIp, lookupId: lookupIdIp, status };

  // ============ IOC 2: domain google.com ============
  await submitLookupViaForm(page, 'google.com');
  await shot(page, 'domain-google-running');
  status = await waitForLookupDone(page, 120000);
  console.log('google.com done status:', status);
  await sleep(2000);
  const urlDomain = page.url();
  const lookupIdDomain = urlDomain.split('/lookup/')[1]?.split('?')[0];
  await shot(page, 'domain-google-complete-top', false);
  await shot(page, 'domain-google-complete-full');
  results.domain = { url: urlDomain, lookupId: lookupIdDomain, status };

  // ============ IOC 3: hash (EICAR test file SHA256, well-known benign test hash) ============
  const hash = '275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0';
  await submitLookupViaForm(page, hash);
  await shot(page, 'hash-running');
  status = await waitForLookupDone(page, 120000);
  console.log('hash done status:', status);
  await sleep(2000);
  const urlHash = page.url();
  const lookupIdHash = urlHash.split('/lookup/')[1]?.split('?')[0];
  await shot(page, 'hash-complete-top', false);
  await shot(page, 'hash-complete-full');
  results.hash = { url: urlHash, lookupId: lookupIdHash, status };

  // ============ IOC 4: CVE ============
  const cve = 'CVE-2024-3400';
  await submitLookupViaForm(page, cve);
  await shot(page, 'cve-running');
  status = await waitForLookupDone(page, 120000);
  console.log('cve done status:', status);
  await sleep(2000);
  const urlCve = page.url();
  const lookupIdCve = urlCve.split('/lookup/')[1]?.split('?')[0];
  await shot(page, 'cve-complete-top', false);
  await shot(page, 'cve-complete-full');
  results.cve = { url: urlCve, lookupId: lookupIdCve, status };

  // ============ Export CSV + PDF on the IP lookup (most likely to have real data) ============
  await page.goto(urlIp.split('?')[0], { waitUntil: 'networkidle2' });
  await sleep(2000);
  await shot(page, 'export-target-page', false);

  const csvBefore = fs.readdirSync(DOWNLOAD_DIR);
  const csvClicked = await clickByText(page, 'button', 'Export CSV');
  console.log('CSV export button clicked:', csvClicked);
  await sleep(4000);
  const csvAfter = fs.readdirSync(DOWNLOAD_DIR);
  await shot(page, 'export-csv-clicked', false);

  const pdfBefore = fs.readdirSync(DOWNLOAD_DIR);
  const pdfClicked = await clickByText(page, 'button', 'Export PDF');
  console.log('PDF export button clicked:', pdfClicked);
  await sleep(5000);
  const pdfAfter = fs.readdirSync(DOWNLOAD_DIR);
  await shot(page, 'export-pdf-clicked', false);

  // ============ Executive Dashboard ============
  await page.goto(`${FRONTEND}/dashboard`, { waitUntil: 'networkidle2' });
  await sleep(3000);
  await shot(page, 'executive-dashboard');

  // ============ Provider Health ============
  await page.goto(`${FRONTEND}/dashboard/provider-health`, { waitUntil: 'networkidle2' });
  await sleep(2500);
  await shot(page, 'provider-health');

  await browser.close();

  // Dump final state + API cross-check info as JSON for the report step
  fs.writeFileSync(
    path.join(OUT, 'run-results.json'),
    JSON.stringify(
      {
        results,
        consoleErrors,
        downloadDirListingAfterCsv: csvAfter,
        downloadDirListingBeforeCsv: csvBefore,
        downloadDirListingAfterPdf: pdfAfter,
        downloadDirListingBeforePdf: pdfBefore,
        csvClicked,
        pdfClicked,
        token,
      },
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
