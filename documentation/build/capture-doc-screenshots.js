// Fresh screenshots of the CURRENT running HORIZON GRID application for the
// documentation package. Auth via a token minted server-side for the real
// existing admin account (test@test.com) and injected into localStorage --
// never typed/printed anywhere, matching this project's established
// credential-safety pattern.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const OUT = path.join(__dirname, '..', 'SCREENSHOTS_V023');
fs.mkdirSync(OUT, { recursive: true });

const FRONTEND = 'http://localhost:23300';

const CHROME_PATHS = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function mintToken() {
  const out = execSync(
    'docker exec hgmc-backend-1 python -c "from app.auth.security import create_access_token; print(create_access_token(\'qa-admin@hgmc-qa.com\', \'admin\', 0))"',
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
}

async function clickByText(page, selector, text) {
  const handles = await page.$$(selector);
  for (const h of handles) {
    const t = await page.evaluate((el) => el.textContent?.trim(), h);
    if (t && t.includes(text)) { await h.click(); return true; }
  }
  return false;
}

async function waitForLookupDone(page, timeoutMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const done = await page.evaluate(() =>
      Array.from(document.querySelectorAll('span')).some((el) => el.textContent?.trim() === 'complete')
    );
    if (done) return true;
    await sleep(1500);
  }
  return false;
}

async function main() {
  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  if (!execPath) throw new Error('No Chrome/Edge executable found');
  const token = mintToken();

  const browser = await puppeteer.launch({
    executablePath: execPath,
    headless: 'new',
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();

  // ---- Logged-out state ----
  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await sleep(500);
  await shot(page, 'home-logged-out');

  await page.goto(`${FRONTEND}/login`, { waitUntil: 'networkidle2' });
  await sleep(500);
  await shot(page, 'login');

  await page.goto(`${FRONTEND}/register`, { waitUntil: 'networkidle2' });
  await sleep(500);
  await shot(page, 'register');

  // ---- Inject real auth, logged-in state from here on ----
  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(500);
  await shot(page, 'home-logged-in');

  // ---- Executive Dashboard ----
  await page.goto(`${FRONTEND}/dashboard`, { waitUntil: 'networkidle2' });
  await sleep(3000);
  await shot(page, 'executive-dashboard');

  // ---- Provider Health ----
  await page.goto(`${FRONTEND}/dashboard/provider-health`, { waitUntil: 'networkidle2' });
  await sleep(2000);
  await shot(page, 'provider-health');
  // Expand one row for the per-window detail view.
  const expandBtn = await page.$('table tbody tr button, table tbody tr svg');
  if (expandBtn) {
    await page.click('table tbody tr').catch(() => {});
    await sleep(500);
    await shot(page, 'provider-health-expanded');
  }

  // ---- Providers (config) ----
  await page.goto(`${FRONTEND}/providers`, { waitUntil: 'networkidle2' });
  await sleep(1500);
  await shot(page, 'ai-providers-tab');

  await clickByText(page, 'button', 'IOC Providers');
  await sleep(800);
  await shot(page, 'ioc-providers-tab');

  await clickByText(page, 'button', 'Network Access');
  await sleep(800);
  await shot(page, 'network-access-tab');

  await clickByText(page, 'button', 'Audit Log');
  await sleep(800);
  await shot(page, 'audit-log-tab');

  // ---- Admin ----
  await page.goto(`${FRONTEND}/admin`, { waitUntil: 'networkidle2' });
  await sleep(1500);
  await shot(page, 'admin-users');

  // ---- Basket / Cases ----
  await page.goto(`${FRONTEND}/basket`, { waitUntil: 'networkidle2' });
  await sleep(1000);
  await shot(page, 'basket');

  await page.goto(`${FRONTEND}/cases`, { waitUntil: 'networkidle2' });
  await sleep(1000);
  await shot(page, 'cases');

  // ---- A real, full investigation end to end ----
  await page.goto(`${FRONTEND}/lookup/new?value=${encodeURIComponent('8.8.8.8')}`, { waitUntil: 'networkidle2' });
  await sleep(2500);
  await shot(page, 'investigation-running');
  const done = await waitForLookupDone(page, 90000);
  console.log('investigation done:', done);
  await sleep(1500);
  await shot(page, 'investigation-complete-top', false);
  await shot(page, 'investigation-complete-full');

  // Relationship Graph -- "View as list" toggle (regression-fixed this release)
  const listToggled = await clickByText(page, 'button', 'View as list');
  if (listToggled) {
    await sleep(500);
    await shot(page, 'relationship-graph-list-view', false);
    await clickByText(page, 'button', 'View as graph');
    await sleep(500);
  }

  // Export menu
  const exportOpened = await clickByText(page, 'button', 'Export');
  if (exportOpened) {
    await sleep(500);
    await shot(page, 'export-menu', false);
  }

  await browser.close();
  console.log('DONE. Screenshots in:', OUT);
}

main().catch((err) => {
  console.error('FATAL:', err);
  process.exit(1);
});
