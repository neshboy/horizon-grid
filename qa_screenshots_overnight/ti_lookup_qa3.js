const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const OUT = __dirname;
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

let shotCounter = 24;
async function shot(page, name, full = true) {
  shotCounter += 1;
  const fname = `${String(shotCounter).padStart(2, '0')}-${name}.png`;
  await page.screenshot({ path: path.join(OUT, fname), fullPage: full });
  console.log('screenshot:', fname);
}

async function waitForComplete(page, timeoutMs = 150000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const done = await page.evaluate(() =>
      Array.from(document.querySelectorAll('span.text-success')).some((el) => el.textContent?.trim() === 'complete')
    );
    if (done) return true;
    await sleep(1500);
  }
  return false;
}

async function main() {
  const execPath = CHROME_PATHS.find((p) => fs.existsSync(p));
  const token = mintToken();
  const browser = await puppeteer.launch({ executablePath: execPath, headless: 'new', defaultViewport: { width: 1440, height: 900 } });
  const page = await browser.newPage();
  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(500);

  const goodHash = '275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f';
  await page.goto(`${FRONTEND}/lookup/new?value=${encodeURIComponent(goodHash)}`, { waitUntil: 'networkidle2' });
  await sleep(1000);
  const finished = await waitForComplete(page, 150000);
  console.log('finished:', finished);
  await sleep(1500);
  await shot(page, 'hash-v3-complete-top', false);
  await shot(page, 'hash-v3-complete-full');
  console.log('final url:', page.url());

  await browser.close();
}

main().catch((e) => { console.error('FATAL', e); process.exit(1); });
