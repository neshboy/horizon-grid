const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1200 });

    page.on('console', (msg) => console.log('[console]', msg.type(), msg.text()));
    page.on('requestfailed', (req) => console.log('[requestfailed]', req.url(), req.failure()?.errorText));
    page.on('response', (res) => {
      if (res.url().includes('/api/')) {
        console.log('[response]', res.status(), res.url());
      }
    });
    page.on('pageerror', (err) => console.log('[pageerror]', err.message));

    await page.goto('http://localhost:3000/login', { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('input[type="email"], input[name="email"]', { timeout: 15000 });
    const emailSel = await page.$('input[type="email"]') ? 'input[type="email"]' : 'input[name="email"]';
    await page.type(emailSel, 'fuck@fuck.com');
    const pwSel = await page.$('input[type="password"]') ? 'input[type="password"]' : 'input[name="password"]';
    await page.type(pwSel, 'Reset12345!');
    await Promise.all([
      page.click('button[type="submit"]'),
      page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 20000 }).catch(() => {}),
    ]);

    console.log('=== URL after login ===', page.url());

    await page.goto('http://localhost:3000/dashboard', { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise(r => setTimeout(r, 3000));

    const bodyText = await page.evaluate(() => document.body.innerText);
    console.log('=== PAGE TEXT ===');
    console.log(bodyText);

    // Check localStorage for token & api base url env
    const ls = await page.evaluate(() => JSON.stringify(Object.keys(localStorage)));
    console.log('=== localStorage keys ===', ls);
  } catch (e) {
    console.error('ERROR:', e);
  } finally {
    await browser.close();
  }
})();
