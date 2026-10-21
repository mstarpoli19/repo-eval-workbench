// Maintainer-only visual QA helper. Not required by the Python application.
// Usage: node tools/preview-report.cjs PATH_TO_PLAYWRIGHT OUTPUT_PNG
const { chromium } = require(process.argv[2]);
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 650}, deviceScaleFactor: 1});
    await page.goto('file://' + path.resolve('reports/example-evaluation.html'));
    await page.screenshot({path: process.argv[3], fullPage: false});
    const overflows = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    console.log(JSON.stringify({title: await page.title(), horizontalOverflow: overflows}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
