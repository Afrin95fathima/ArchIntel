import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
try {
  const page = await browser.newPage();
  for (const name of ['USER-MANUAL', 'DEVELOPER-GUIDE', 'RUNTIME-USER-FLOW', 'RUNTIME-DEVELOPER-GUIDE', 'PHASE-1-USER-FLOW', 'PHASE-1-DEVELOPER-GUIDE', 'PHASE-2-USER-FLOW', 'PHASE-2-DEVELOPER-GUIDE', 'PHASE-3-USER-FLOW', 'PHASE-3-DEVELOPER-GUIDE', 'PHASE-4-USER-FLOW', 'PHASE-4-DEVELOPER-GUIDE', 'PHASE-5-USER-FLOW', 'PHASE-5-DEVELOPER-GUIDE', 'PHASE-6-USER-FLOW', 'PHASE-6-DEVELOPER-GUIDE', 'PHASE-7-USER-FLOW', 'PHASE-7-DEVELOPER-GUIDE']) {
    await page.goto(pathToFileURL(path.join(root, 'docs', `${name}.html`)).href);
    await page.pdf({ path: path.join(root, 'docs', `${name}.pdf`), format: 'A4', printBackground: true, preferCSSPageSize: true, displayHeaderFooter: true, headerTemplate: '<span></span>', footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#63786e">ArchIntel · <span class="pageNumber"></span> / <span class="totalPages"></span></div>' });
    console.log(`Generated docs/${name}.pdf`);
  }
} finally { await browser.close(); }
