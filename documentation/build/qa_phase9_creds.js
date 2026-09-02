// Phase 9 "Credential Management" QA -- real browser walkthrough against the
// LIVE app stack (localhost:3000 / :8000). Reproduces the type-then-clear
// silent-wipe bug through the actual Settings > Manage Providers UI, and
// captures the real network request/response bodies to confirm the raw
// credential value never appears anywhere in the browser.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'raw-screenshots');
fs.mkdirSync(OUT, { recursive: true });

const FRONTEND = 'http://localhost:3000';
const ADMIN_EMAIL = 'fuck@fuck.com';
const ADMIN_PASSWORD = 'Reset12345!';

const CHROME_PATHS = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

let shotCounter = 0;
async function shot(page, name) {
  shotCounter += 1;
  const fname = `${String(shotCounter).padStart(2, '0')}-phase9-${name}.png`;
  await page.screenshot({ path: path.join(OUT, fname), fullPage: true });
  console.log('screenshot:', fname);
}

async function clickByText(page, selector, text) {
  const handles = await page.$$(selector);
  for (const h of handles) {
    const t = await page.evaluate((el) => el.textContent?.trim(), h);
    if (t && t.includes(text)) {
      await h.click();
      return true;
    }
  }
  return false;
}

async function main() {
  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  if (!execPath) throw new Error('No Chrome/Edge executable found');

  const browser = await puppeteer.launch({
    executablePath: execPath,
    headless: 'new',
    defaultViewport: { width: 1440, height: 1000 },
  });
  const page = await browser.newPage();

  const networkLog = [];
  page.on('requestfinished', async (req) => {
    const url = req.url();
    if (!url.includes('/api/v1/runtime/ioc-providers')) return;
    try {
      const resp = req.response();
      let reqBody = req.postData() || '';
      let resBody = '';
      try { resBody = await resp.text(); } catch (e) { resBody = `<err:${e.message}>`; }
      networkLog.push({ method: req.method(), url, status: resp.status(), reqBody, resBody });
    } catch (e) {
      networkLog.push({ method: req.method(), url, error: e.message });
    }
  });

  const consoleLog = [];
  page.on('console', (msg) => consoleLog.push(`${msg.type()}: ${msg.text()}`));

  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await sleep(500);
  await clickByText(page, 'button', 'Sign in');
  await page.waitForSelector('input[type="email"]', { timeout: 10000 });
  await page.type('input[type="email"]', ADMIN_EMAIL, { delay: 20 });
  await page.type('input[type="password"]', ADMIN_PASSWORD, { delay: 20 });
  await shot(page, 'login-filled');
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle2' }),
    clickByText(page, 'button', 'Sign in'),
  ]);
  await sleep(1000);

  await page.goto(`${FRONTEND}/providers`, { waitUntil: 'networkidle2' });
  await sleep(1000);
  await shot(page, 'providers-page');

  // Switch to IOC Providers tab
  await clickByText(page, 'button', 'IOC Providers');
  await sleep(500);
  await shot(page, 'ioc-tab');

  // Expand URLhaus row (already configured via API with a real key)
  const expanded = await clickByText(page, 'button', 'URLhaus');
  console.log('expanded URLhaus row:', expanded);
  await sleep(500);
  await shot(page, 'urlhaus-expanded');

  // Find the auth_key input inside the expanded row and read its placeholder
  // (should show the masked value, never the real one).
  const placeholderInfo = await page.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll('input[type="password"]'));
    return inputs.map((i) => ({ placeholder: i.placeholder, value: i.value }));
  });
  console.log('password input(s) found:', JSON.stringify(placeholderInfo));

  // Type into the auth_key field, then delete it (simulating a user who
  // starts to retype the key, changes their mind, and clears the field --
  // exactly the interaction the backend's own code comment warns about).
  const pwInput = await page.$('input[type="password"]');
  if (!pwInput) throw new Error('Could not find password input for URLhaus auth_key field');
  await pwInput.click();
  await pwInput.type('temp-typo-then-cleared');
  await shot(page, 'urlhaus-typed');
  // Select all and delete to leave the field explicitly empty (not just untouched)
  await page.keyboard.down('Control');
  await page.keyboard.press('KeyA');
  await page.keyboard.up('Control');
  await page.keyboard.press('Backspace');
  await shot(page, 'urlhaus-cleared');

  const valueAfterClear = await page.evaluate(() => {
    const i = document.querySelector('input[type="password"]');
    return i ? i.value : null;
  });
  console.log('input value after clear (should be empty string):', JSON.stringify(valueAfterClear));

  // Click Save
  await clickByText(page, 'button', 'Save');
  await sleep(1500);
  await shot(page, 'urlhaus-after-save');

  // Re-expand / refresh to see resulting configured state
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(1000);
  await clickByText(page, 'button', 'IOC Providers');
  await sleep(500);
  await clickByText(page, 'button', 'URLhaus');
  await sleep(500);
  await shot(page, 'urlhaus-after-reload');

  const statusText = await page.evaluate(() => {
    const spans = Array.from(document.querySelectorAll('span'));
    const hit = spans.find((s) => s.textContent?.includes('URLhaus'));
    return hit ? hit.closest('button')?.textContent : null;
  });
  console.log('URLhaus row status text after reload:', statusText);

  fs.writeFileSync(
    path.join(__dirname, 'phase9-network-log.json'),
    JSON.stringify(networkLog, null, 2)
  );
  fs.writeFileSync(
    path.join(__dirname, 'phase9-console-log.json'),
    JSON.stringify(consoleLog, null, 2)
  );
  console.log('Wrote network log with', networkLog.length, 'entries.');

  await browser.close();
}

main().catch((err) => {
  console.error('FATAL:', err);
  process.exit(1);
});
