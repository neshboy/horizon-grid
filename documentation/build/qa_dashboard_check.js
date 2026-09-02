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

    // Login
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

    await page.goto('http://localhost:3000/dashboard', { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForTimeout ? await page.waitForTimeout(3000) : await new Promise(r => setTimeout(r, 3000));

    const bodyText = await page.evaluate(() => document.body.innerText);
    console.log('=== PAGE TEXT ===');
    console.log(bodyText);

    await page.screenshot({ path: 'C:\\Users\\User\\ioc-intel-platform\\documentation\\build\\qa_dashboard_screenshot.png', fullPage: true });
    console.log('Screenshot saved.');
  } catch (e) {
    console.error('ERROR:', e);
  } finally {
    await browser.close();
  }
})();
