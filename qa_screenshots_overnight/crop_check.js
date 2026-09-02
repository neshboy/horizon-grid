const puppeteer = require('puppeteer-core');
const { execSync } = require('child_process');

const FRONTEND = 'http://localhost:3000';
const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function mintToken() {
  const out = execSync(
    'docker exec app-backend-1 python -c "from app.auth.security import create_access_token; print(create_access_token(\'fuck@fuck.com\', \'admin\', 0))"',
    { encoding: 'utf-8' }
  );
  return out.trim();
}

async function main() {
  const token = mintToken();
  const browser = await puppeteer.launch({ executablePath: CHROME_PATH, headless: 'new', defaultViewport: { width: 1440, height: 900 } });
  const page = await browser.newPage();
  await page.goto(FRONTEND, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('access_token', t), token);
  const hash = '275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f';
  await page.goto(`${FRONTEND}/lookup/new?value=${encodeURIComponent(hash)}`, { waitUntil: 'networkidle2' });
  await sleep(15000);
  const heights = await page.evaluate(() => {
    const grids = document.querySelectorAll('main .grid');
    let cardGrid = null;
    for (const g of grids) {
      if (g.className.includes('sm:grid-cols-2') && g.className.includes('lg:grid-cols-3')) { cardGrid = g; break; }
    }
    const otxCard = cardGrid.children[0]; // AlienVault OTX
    const out = [];
    const details = otxCard.querySelector('details');
    out.push({ what: 'details.open', v: details ? details.open : null });
    const pre = otxCard.querySelector('pre');
    if (pre) {
      const cs = getComputedStyle(pre);
      out.push({ what: 'pre rect', h: Math.round(pre.getBoundingClientRect().height), maxHeight: cs.maxHeight, overflow: cs.overflowY, textLen: pre.textContent.length });
    }
    const content = otxCard.querySelector('.p-4.pt-0.flex.flex-1.flex-col');
    const divide = content.querySelector('.divide-y');
    const rows = [];
    if (divide) {
      for (const row of divide.children) {
        rows.push({ h: Math.round(row.getBoundingClientRect().height), text: row.textContent.slice(0, 60) });
      }
    }
    out.push({ what: 'DataField rows', rows });

    const tagsRow = divide.children[5];
    const span = tagsRow.querySelectorAll('span')[1];
    const cs = getComputedStyle(span);
    out.push({
      what: 'tags span diagnostics',
      textLength: span.textContent.length,
      commaCount: (span.textContent.match(/,/g) || []).length,
      whiteSpace: cs.whiteSpace,
      wordBreak: cs.wordBreak,
      display: cs.display,
      width: Math.round(span.getBoundingClientRect().width),
      parentWidth: Math.round(tagsRow.getBoundingClientRect().width),
    });
    return out;
  });
  console.log(JSON.stringify(heights, null, 2));
  await browser.close();
}
main().catch((e) => { console.error(e); process.exit(1); });
