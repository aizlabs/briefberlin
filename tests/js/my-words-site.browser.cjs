const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const siteDir = process.env.BRIEFBERLIN_SITE_DIR;
let server, browser, origin, articleUrl;
before(async () => {
  if (!siteDir) return;
  const { chromium } = require('playwright');
  for (const name of fs.readdirSync(path.join(siteDir, 'articles'))) {
    const file = path.join(siteDir, 'articles', name, 'index.html');
    if (!fs.existsSync(file)) continue;
    const html = fs.readFileSync(file, 'utf8');
    const payload = html.match(/<script[^>]*class="article-glossary-data"[^>]*>(.*?)<\/script>/s);
    if (payload && JSON.parse(payload[1]).some(w => !w.defaultGlossary) && JSON.parse(payload[1]).some(w => w.defaultGlossary)) {
      articleUrl = '/articles/' + name + '/'; break;
    }
  }
  assert.ok(articleUrl, 'built site needs a generated article with both default and extra vocabulary');
  server = http.createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const file = path.resolve(siteDir, '.' + pathname + (pathname.endsWith('/') ? 'index.html' : ''));
    if (!file.startsWith(path.resolve(siteDir) + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.statusCode = 404; res.end(); return; }
    const mime = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.xml':'application/xml' }[path.extname(file)] || 'application/octet-stream';
    res.setHeader('Content-Type', mime + '; charset=utf-8'); res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve)); origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, headless: true } : { headless: true });
});
after(async () => { if (browser) await browser.close(); if (server) await new Promise(resolve => server.close(resolve)); });
async function contextFor(options = {}) {
  const context = await browser.newContext(options);
  // Keep test browsing local: optional hosted fonts/icons and unrelated tracking do not affect the feature.
  await context.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort());
  return context;
}
const run = (name, fn) => test(name, { skip: !siteDir }, fn);
run('built article to collection journey, keyboard popup, back navigation and downloads', async () => {
  const context = await contextFor({ viewport: { width: 1280, height: 900 } }); const page = await context.newPage(); const errors = [];
  page.on('pageerror', error => errors.push(error.message)); page.setDefaultTimeout(8000);
  try {
    await page.goto(origin + articleUrl);
    const item = await page.evaluate(() => {
      const items=JSON.parse(document.querySelector('.article-glossary-data').textContent);
      return items.find(w => !w.defaultGlossary && Array.from(document.querySelectorAll('.article-term')).some(el=>el.dataset.termId === w.id));
    });
    assert.ok(item); const word = page.locator(`[data-term-id="${item.id}"]`).first();
    await word.focus(); await page.keyboard.press('Enter');
    if (process.env.BRIEFBERLIN_SCREENSHOT_DIR) {
      fs.mkdirSync(process.env.BRIEFBERLIN_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.BRIEFBERLIN_SCREENSHOT_DIR, 'glossary-desktop.png') });
    }
    await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: ' + item.term, exact: true }).click();
    await page.keyboard.press('Escape');
    assert.equal(await word.evaluate(el=>el===document.activeElement), true);
    assert.ok((await word.getAttribute('class')).includes('article-term--default'));
    await page.locator('.my-words-glossary-controls a').click();
    await page.waitForURL('**/meine-woerter/');
    assert.equal(await page.locator('.my-words-entry strong').innerText(), item.term);
    assert.equal(await page.locator('.my-words-entry__source a').getAttribute('href'), origin + articleUrl);
    await page.reload(); assert.equal(await page.locator('.my-words-entry').count(), 1);
    for (const label of ['CSV herunterladen', 'Für Anki herunterladen']) {
      await page.locator('[data-words-export] > summary').click();
      const promise = page.waitForEvent('download'); await page.getByRole('button', { name: label, exact: true }).click();
      const download = await promise; assert.ok(fs.readFileSync(await download.path(), 'utf8').includes(item.term));
    }
    await page.locator('.my-words-entry__source a').click();
    // The click can resolve at navigation commit, before deferred scripts restore saved styling.
    await page.waitForURL(origin + articleUrl, { waitUntil: 'domcontentloaded' });
    await page.locator(`.article-term--default[data-term-id="${item.id}"]`).first().waitFor();
    assert.ok((await page.locator(`[data-term-id="${item.id}"]`).first().getAttribute('class')).includes('article-term--default'));
    await page.goBack(); assert.equal(await page.locator('.my-words-entry').count(), 1);
    if (process.env.BRIEFBERLIN_SCREENSHOT_DIR) {
      fs.mkdirSync(process.env.BRIEFBERLIN_SCREENSHOT_DIR, { recursive: true });
      await page.evaluate(() => document.fonts.ready); await page.screenshot({ path: path.join(process.env.BRIEFBERLIN_SCREENSHOT_DIR, 'my-words-desktop.png'), fullPage: true, animations: 'disabled' });
    }
    assert.deepEqual(errors, []);
  } finally { await context.close(); }
});
run('built mobile layouts fit and popup remains in viewport', async () => {
  const context = await contextFor({ viewport: { width: 375, height: 812 } }); const page = await context.newPage();
  try {
    await page.goto(origin + articleUrl);
    await page.locator('.article-term').first().click();
    const popup = page.locator('.article-glossary-popup'); const box = await popup.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= 375 && box.y >= 0 && box.y + box.height <= 812);
    if (process.env.BRIEFBERLIN_SCREENSHOT_DIR) {
      fs.mkdirSync(process.env.BRIEFBERLIN_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.BRIEFBERLIN_SCREENSHOT_DIR, 'glossary-mobile.png') });
    }
    await popup.locator('.article-glossary-popup__add').click(); await page.keyboard.press('Escape');
    await page.locator('.my-words-glossary-controls a').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('[data-words-export] > summary').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (process.env.BRIEFBERLIN_SCREENSHOT_DIR) { await page.evaluate(() => document.fonts.ready); await page.screenshot({ path: path.join(process.env.BRIEFBERLIN_SCREENSHOT_DIR, 'my-words-mobile.png'), fullPage: true, animations: 'disabled' }); }
  } finally { await context.close(); }
});
run('built metadata and translated navigation retain German feature label', async () => {
  const context = await contextFor(); const page = await context.newPage();
  try {
    await page.goto(origin + '/meine-woerter/');
    assert.equal(await page.locator('html').getAttribute('lang'), 'de-DE');
    assert.ok(await page.locator('meta[name="robots"][content="noindex"]').count());
    assert.ok(!fs.readFileSync(path.join(siteDir, 'sitemap.xml'), 'utf8').includes('/meine-woerter/'));
    await page.goto(origin + '/en/');
    assert.equal((await page.locator('#site-nav a[href="/meine-woerter/"]').textContent()).trim(), 'Meine Wörter');
    assert.equal(await page.locator('script[src*="my-words-page"]').count(), 0);
  } finally { await context.close(); }
});
run('saved words coexist with the upstream reading-size preference', async () => {
  const context = await contextFor(); const page = await context.newPage();
  try {
    await page.goto(origin + articleUrl);
    await page.locator('[data-reading-size-increase]').click();
    assert.equal(await page.locator('[data-reading-size-value]').innerText(), '125%');
    await page.locator('.article-term').first().click();
    await page.locator('.article-glossary-popup__add').click();
    await page.reload();
    assert.equal(await page.locator('[data-reading-size-value]').innerText(), '125%');
    assert.equal(await page.evaluate(() => BriefBerlin.words.read().entries.length), 1);
    await page.locator('[data-reading-size-reset]').click();
    assert.equal(await page.locator('[data-reading-size-value]').innerText(), '100%');
    assert.equal(await page.evaluate(() => BriefBerlin.words.read().entries.length), 1);
  } finally { await context.close(); }
});
