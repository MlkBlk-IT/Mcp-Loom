const { chromium } = require('C:/Users/Tech/AppData/Roaming/npm/node_modules/@playwright/mcp/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/Tech/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe',
    headless: true
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push(err.message));

  // wait for data to flow
  await page.goto('http://127.0.0.1:8765/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000); // let SSE populate charts

  const sections = ['overview','storage','audit','tools','invariants','sessions'];
  for (const sec of sections) {
    await page.evaluate(s => {
      const btn = document.querySelector(`.nav-item[data-section="${s}"]`);
      if (btn) btn.click();
    }, sec);
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `D:/Loom/dash/shot-v4-${sec}.png` });
    console.log(`shot-v4-${sec}.png captured`);
  }

  console.log('JS errors:', errors.length ? errors.join(' | ') : 'none');
  await browser.close();
})();
