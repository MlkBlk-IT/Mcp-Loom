const { chromium } = require('C:/Users/Tech/AppData/Roaming/npm/node_modules/@playwright/mcp/node_modules/playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/Tech/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle', timeout: 10000 });
  await page.waitForTimeout(2500);

  // Click Upgrade nav
  const navBtn = await page.$('[data-section="upgrade"]');
  if (navBtn) await navBtn.click();
  await page.waitForTimeout(1500);

  // Full page screenshot (captures everything including the table)
  const outPath = path.resolve('D:/Loom/dash/shot-upgrade-full.png');
  await page.screenshot({ path: outPath, fullPage: true });
  console.log('Full screenshot: ' + outPath);

  await browser.close();
})();
