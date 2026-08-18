// Real screenshots of HORIZON GRID actually running, end to end, on a real
// Debian 12 Docker container (installed via the real .deb, configured by
// the real CLI wizard, hit here through a Chrome instance on the build
// host -- there is no native Linux desktop session available in this
// environment, so this captures the real application/real data rendered
// through a browser, not a native GNOME/KDE window; that distinction is
// disclosed explicitly in the Linux QA report rather than presented as a
// native desktop screenshot it isn't). Auth via the real access token
// already obtained from a genuine POST /api/v1/auth/login call against this
// instance (never hand-typed, matching this project's established
// credential-safety pattern).
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const OUT = 'C:\\Users\\User\\ioc-intel-platform\\linux\\test\\screenshots';
fs.mkdirSync(OUT, { recursive: true });

const FRONTEND = 'http://localhost:23000';
const TOKEN = fs.readFileSync('C:\\Users\\User\\AppData\\Local\\Temp\\hg-shots-token.txt', 'utf-8').trim();
const LOOKUP_ID = '92feaa66-74ec-4285-98c1-946445f88f9e';

const CHROME_PATHS = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

let shotCounter = 0;
async function shot(page, name, full = true) {
  shotCounter += 1;
  const fname = `${String(shotCounter).padStart(2, '0')}-linux-${name}.png`;
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

async function main() {
  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  if (!execPath) throw new Error('No Chrome/Edge executable found');

  const browser = await puppeteer.launch({
    executablePath: execPath,
    headless: 'new',
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();

  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await sleep(500);
  await shot(page, 'home-logged-out');

  await page.goto(`${FRONTEND}/login`, { waitUntil: 'networkidle2' });
  await sleep(500);
  await shot(page, 'login');

  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('access_token', t), TOKEN);
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(500);
  await shot(page, 'home-logged-in');

  await page.goto(`${FRONTEND}/dashboard`, { waitUntil: 'networkidle2' });
  await sleep(3000);
  await shot(page, 'executive-dashboard');

  await page.goto(`${FRONTEND}/dashboard/provider-health`, { waitUntil: 'networkidle2' });
  await sleep(2500);
  await shot(page, 'provider-health');

  await page.goto(`${FRONTEND}/providers`, { waitUntil: 'networkidle2' });
  await sleep(1500);
  await shot(page, 'ai-providers-tab');
  await clickByText(page, 'button', 'IOC Providers');
  await sleep(800);
  await shot(page, 'ioc-providers-tab');

  await page.goto(`${FRONTEND}/lookup/${LOOKUP_ID}`, { waitUntil: 'networkidle2' });
  await sleep(2500);
  await shot(page, 'investigation-8888-result');

  await browser.close();
  console.log('done -- ' + shotCounter + ' screenshots in ' + OUT);
}

main().catch((e) => { console.error(e); process.exit(1); });
