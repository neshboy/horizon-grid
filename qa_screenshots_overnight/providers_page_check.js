const puppeteer = require('puppeteer-core');
const { execSync } = require('child_process');
const path = require('path');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const FRONTEND = 'http://localhost:3000';
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function mintToken() {
  return execSync(
    'docker exec app-backend-1 python -c "from app.auth.security import create_access_token; print(create_access_token(\'fuck@fuck.com\', \'admin\', 0))"',
    { encoding: 'utf-8' }
  ).trim();
}

let n = 26;
async function shot(page, name) {
  n += 1;
  const fname = `${String(n).padStart(2, '0')}-${name}.png`;
  await page.screenshot({ path: path.join(__dirname, fname), fullPage: true });
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

async function main() {
  const token = mintToken();
  const browser = await puppeteer.launch({ executablePath: CHROME_PATH, headless: 'new', defaultViewport: { width: 1440, height: 900 } });
  const page = await browser.newPage();
  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);
  await page.goto(`${FRONTEND}/providers`, { waitUntil: 'networkidle2' });
  await sleep(1500);
  await clickByText(page, 'button', 'IOC Providers');
  await sleep(1000);
  await shot(page, 'providers-page-ioc-tab');
  await browser.close();
}
main().catch((e) => { console.error(e); process.exit(1); });
