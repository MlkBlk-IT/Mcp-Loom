const { chromium } = require('C:/Users/Tech/AppData/Roaming/npm/node_modules/@playwright/mcp/node_modules/playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/Tech/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle', timeout: 10000 });
  await page.waitForTimeout(2500);

  // Click the Upgrade nav item
  const navBtn = await page.$('[data-section="upgrade"]');
  if (navBtn) await navBtn.click();
  await page.waitForTimeout(1500);

  // Screenshot
  const outPath = path.resolve('D:/Loom/dash/shot-upgrade.png');
  await page.screenshot({ path: outPath, fullPage: false });
  console.log('Screenshot saved: ' + outPath);

  // Check for JS errors
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  await page.waitForTimeout(500);
  console.log('JS errors: ' + errors.length);

  await browser.close();
})();
