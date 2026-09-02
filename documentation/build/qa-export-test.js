const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const FRONTEND = 'http://localhost:3000';
const LOOKUP_ID = '46de368a-9eaf-48d5-91ea-00a1d5528c9b';
const TOKEN = process.argv[2];
const OUT = path.join('C:\\Users\\User\\qa_export_downloads');
fs.mkdirSync(OUT, { recursive: true });

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function main() {
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: false,
    args: ['--window-size=1400,1000'],
  });
  const page = await browser.newPage();
  const client = await page.target().createCDPSession();
  await client.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: OUT });

  await page.goto(FRONTEND, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => {
    localStorage.setItem('access_token', t);
  }, TOKEN);

  await page.goto(`${FRONTEND}/lookup/${LOOKUP_ID}`, { waitUntil: 'networkidle2', timeout: 60000 });
  await sleep(4000);

  await page.screenshot({ path: path.join(OUT, 'lookup_page.png'), fullPage: true });

  async function clickButtonByText(text) {
    const buttons = await page.$$('button');
    for (const b of buttons) {
      const t = await page.evaluate((el) => el.textContent?.trim(), b);
      if (t === text) {
        await b.click();
        return true;
      }
    }
    return false;
  }

  console.log('Export JSON click:', await clickButtonByText('Export JSON'));
  await sleep(1500);
  console.log('Export Markdown click:', await clickButtonByText('Export Markdown'));
  await sleep(1500);
  console.log('Export PDF click:', await clickButtonByText('Export PDF'));
  await sleep(3000);
  console.log('Export CSV click:', await clickButtonByText('Export CSV'));
  await sleep(3000);

  console.log('Files in download dir:', fs.readdirSync(OUT));

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
