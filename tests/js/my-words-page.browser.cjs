const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
let server, browser, origin;
before(async () => {
  server = http.createServer((req, res) => {
    if (/^\/assets\/(js|css)\/[a-z.-]+$/.test(req.url)) {
      res.setHeader('Content-Type', req.url.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8');
      res.end(fs.readFileSync(path.join('output', req.url))); return;
    }
    const markup = fs.readFileSync('output/_pages/meine-woerter.html', 'utf8').replace(/^---[\s\S]*?---/, '').replace(/\{\{ '\/' \| relative_url \}\}/g, '/');
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    const exporter = fs.existsSync('output/assets/js/my-words-export.js') ? '<script defer src="/assets/js/my-words-export.js"></script>' : '';
    res.end(`<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/assets/css/custom.css"><script defer src="/assets/js/my-words-store.js"></script>${exporter}<script defer src="/assets/js/my-words-page.js"></script></head><body><main><h1>Meine Wörter</h1>${markup}</main></body></html>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve)); origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, headless: true } : { headless: true });
});
after(async () => { if (browser) await browser.close(); if (server) await new Promise(resolve => server.close(resolve)); });
async function setup(options = {}) {
  const context = await browser.newContext(options); const page = await context.newPage(); page.setDefaultTimeout(5000);
  await page.goto(origin + '/meine-woerter/'); return { context, page };
}
async function seed(page) {
  await page.evaluate(() => {
    for (const term of ['Zug', 'Änderung', 'beantragen']) BriefBerlin.words.add({ language: 'de', term, translation: 'meaning', explanation: 'Eine Erklärung.', articleTitle: 'Testartikel', articleUrl: location.origin + '/articles/test/' });
  });
}
test('empty, list content, German sorting and original article links', async () => {
  const { context, page } = await setup();
  try {
    assert.equal(await page.locator('[data-words-empty]').isVisible(), true);
    assert.equal(await page.locator('[data-words-toolbar]').isVisible(), false);
    await seed(page);
    assert.equal(await page.locator('[data-words-count]').innerText(), '3 gespeicherte Wörter');
    assert.deepEqual(await page.locator('.my-words-entry strong').allTextContents(), ['Änderung', 'beantragen', 'Zug']);
    await page.getByRole('button', { name: 'Neueste zuerst' }).click();
    assert.equal(await page.getByRole('button', { name: 'Neueste zuerst' }).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.getByRole('button', { name: 'A–Z: alphabetisch sortieren' }).getAttribute('aria-pressed'), 'false');
    const entries = await page.evaluate(() => BriefBerlin.words.read().entries);
    const expected = entries.slice().sort((a,b) => Date.parse(b.savedAt)-Date.parse(a.savedAt) || new Intl.Collator('de').compare(a.term,b.term)).map(e=>e.term);
    assert.deepEqual(await page.locator('.my-words-entry strong').allTextContents(), expected);
    assert.equal(await page.locator('.my-words-entry__source a').first().getAttribute('href'), origin + '/articles/test/');
  } finally { await context.close(); }
});
test('remove focuses next row, undo restores record and sorting preserves undo', async () => {
  const { context, page } = await setup();
  try {
    await seed(page); const original = await page.evaluate(() => BriefBerlin.words.read().entries.find(e => e.term === 'Änderung'));
    await page.getByRole('button', { name: 'Änderung entfernen', exact: true }).click();
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-label')), 'beantragen entfernen');
    await page.getByRole('button', { name: 'Neueste zuerst' }).click();
    assert.equal(await page.getByRole('button', { name: 'Neueste zuerst' }).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.getByRole('button', { name: 'A–Z: alphabetisch sortieren' }).getAttribute('aria-pressed'), 'false');
    await page.getByRole('button', { name: 'Rückgängig', exact: true }).click();
    assert.deepEqual(await page.evaluate(() => BriefBerlin.words.read().entries.find(e => e.term === 'Änderung')), original);
    for (const word of ['Änderung','beantragen','Zug']) await page.getByRole('button', { name: word + ' entfernen', exact: true }).click();
    assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Zu den Artikeln');
    assert.equal(await page.locator('[data-words-empty]').isVisible(), true);
  } finally { await context.close(); }
});
test('malformed storage retains last rendered list and offers retry', async () => {
  const { context, page } = await setup();
  try {
    await seed(page);
    await page.evaluate(() => { localStorage.setItem('briefberlin.myWords.v1', '{'); window.dispatchEvent(new StorageEvent('storage', { key: 'briefberlin.myWords.v1' })); });
    assert.equal(await page.locator('.my-words-entry').count(), 3);
    assert.equal(await page.locator('.my-words-entry button').first().isDisabled(), true);
    assert.equal(await page.locator('[data-words-toolbar]').isVisible(), false);
    assert.match(await page.locator('[data-words-status]').innerText(), /nicht geladen/);
    await page.evaluate(() => localStorage.removeItem('briefberlin.myWords.v1'));
    await page.getByRole('button', { name: 'Erneut versuchen' }).click();
    assert.equal(await page.locator('[data-words-empty]').isVisible(), true);
  } finally { await context.close(); }
});
test('narrow mobile layout fits and saved text is not executed as HTML', async () => {
  const { context, page } = await setup({ viewport: { width: 320, height: 740 } });
  try {
    await page.evaluate(() => BriefBerlin.words.add({ language: 'de', term: '<img src=x onerror="window.injected=true">', translation: 'x'.repeat(180), explanation: 'Erklärung', articleTitle: 'a'.repeat(180), articleUrl: location.origin + '/articles/test/' }));
    assert.equal(await page.locator('[data-words-list] img').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const box = await page.locator('.my-words-entry button').boundingBox(); assert.ok(box.height >= 44);
  } finally { await context.close(); }
});
test('no-JavaScript view explains requirement without exposing broken controls', async () => {
  const { context, page } = await setup({ javaScriptEnabled: false });
  try {
    assert.match(await page.locator('noscript').innerText(), /brauchst du JavaScript/);
    assert.equal(await page.locator('[data-words-toolbar]').isVisible(), false);
  } finally { await context.close(); }
});
test('cross-tab refresh preserves link focus and recovers when focused row is removed', async () => {
  const { context, page } = await setup();
  try {
    await seed(page);
    const other = await context.newPage(); await other.goto(origin + '/meine-woerter/');
    await page.locator('.my-words-entry__source a').first().focus();
    await other.evaluate(() => BriefBerlin.words.add({ language: 'de', term: 'neu', translation: '', explanation: '', articleTitle: 'Testartikel', articleUrl: location.origin + '/articles/test/' }));
    await page.waitForFunction(() => document.querySelectorAll('.my-words-entry').length === 4);
    assert.equal(await page.evaluate(() => document.activeElement.tagName), 'A');
    assert.equal(await page.evaluate(() => document.activeElement.closest('.my-words-entry').querySelector('strong').textContent), 'Änderung');
    await other.getByRole('button', { name: 'Änderung entfernen', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('.my-words-entry').length === 3);
    assert.equal(await page.evaluate(() => document.activeElement.tagName), 'A');
    assert.equal(await page.evaluate(() => document.activeElement.closest('.my-words-entry').querySelector('strong').textContent), 'beantragen');
  } finally { await context.close(); }
});
test('read failure during removal preserves data and gives retry usable focus', async () => {
  const { context, page } = await setup();
  try {
    await seed(page);
    await page.evaluate(() => localStorage.setItem('briefberlin.myWords.v1', '{'));
    await page.getByRole('button', { name: 'Änderung entfernen', exact: true }).click();
    assert.equal(await page.evaluate(() => localStorage.getItem('briefberlin.myWords.v1')), '{');
    assert.equal(await page.locator('.my-words-entry').count(), 3);
    assert.match(await page.locator('[data-words-status]').innerText(), /nicht geladen/);
    assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Erneut versuchen');
    await page.evaluate(() => localStorage.removeItem('briefberlin.myWords.v1'));
    await page.getByRole('button', { name: 'Erneut versuchen' }).click();
    assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Zu den Artikeln');
  } finally { await context.close(); }
});
test('CSV and Anki downloads contain all words in displayed order and preserve undo', async () => {
  const { context, page } = await setup();
  try {
    await seed(page); await page.getByRole('button', { name: 'Zug entfernen', exact: true }).click();
    const before = await page.evaluate(() => JSON.stringify(BriefBerlin.words.read().entries));
    for (const [format, label] of [['csv','CSV herunterladen'],['anki','Für Anki herunterladen']]) {
      await page.locator('[data-words-export] > summary').click();
      const downloadPromise = page.waitForEvent('download'); await page.getByRole('button', { name: label, exact: true }).click();
      const download = await downloadPromise; const text = fs.readFileSync(await download.path(), 'utf8');
      assert.ok(text.indexOf('Änderung') < text.indexOf('beantragen')); assert.ok(!text.includes('Zug'));
      assert.match(download.suggestedFilename(), format === 'csv' ? /\.csv$/ : /-anki\.txt$/);
      assert.equal(await page.evaluate(() => JSON.stringify(BriefBerlin.words.read().entries)), before);
      assert.equal(await page.locator('[data-words-undo]').isVisible(), true);
    }
  } finally { await context.close(); }
});
test('export rechecks current storage and restores focus when it becomes unreadable or empty', async () => {
  const { context, page } = await setup();
  try {
    await seed(page);
    await page.locator('[data-words-export] > summary').click();
    await page.evaluate(() => localStorage.setItem('briefberlin.myWords.v1', '{'));
    await page.getByRole('button', { name: 'CSV herunterladen', exact: true }).click();
    assert.equal(await page.locator('[data-words-toolbar]').isVisible(), false);
    assert.equal(await page.locator('[data-words-retry]').evaluate(el => el === document.activeElement), true);
    await page.evaluate(() => localStorage.removeItem('briefberlin.myWords.v1'));
    await page.getByRole('button', { name: 'Erneut versuchen', exact: true }).click();
    await seed(page);
    await page.locator('[data-words-export]').evaluate(el => el.open = true);
    await page.evaluate(() => localStorage.removeItem('briefberlin.myWords.v1'));
    await page.getByRole('button', { name: 'Für Anki herunterladen', exact: true }).click();
    assert.equal(await page.locator('[data-words-empty]').isVisible(), true);
    assert.equal(await page.locator('[data-words-articles]').evaluate(el => el === document.activeElement), true);
  } finally { await context.close(); }
});
test('outdated links stay listed without a link; unreadable records are reported', async () => {
  const { context, page } = await setup();
  try {
    await seed(page);
    await page.evaluate(() => {
      const data = JSON.parse(localStorage.getItem('briefberlin.myWords.v1'));
      // Simulate a base-path change: every saved link now points elsewhere.
      data.entries.forEach(e => { e.articleUrl = location.origin + '/old-base/articles/test/'; });
      data.entries.push({ term: 'kaputt' });
      localStorage.setItem('briefberlin.myWords.v1', JSON.stringify(data));
    });
    await page.reload();
    assert.equal(await page.locator('[data-words-count]').innerText(), '3 gespeicherte Wörter');
    assert.equal(await page.locator('.my-words-entry__source a').count(), 0);
    assert.equal(await page.locator('.my-words-entry__source').first().innerText(), 'Artikel: Testartikel');
    assert.equal(await page.locator('[data-words-toolbar]').isVisible(), true);
    assert.match(await page.locator('[data-words-hidden]').innerText(), /^1 gespeicherter Eintrag kann nicht angezeigt werden/);
    await page.getByRole('button', { name: 'Zug entfernen', exact: true }).click();
    assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('briefberlin.myWords.v1')).entries.some(e => e.term === 'kaputt')), true);
  } finally { await context.close(); }
});

test('export keeps guidance optional and dismisses with Escape or outside interaction', async () => {
  const { context, page } = await setup();
  try {
    await seed(page);
    const summary = page.locator('[data-words-export] > summary');
    const panel = page.locator('[data-words-export]');
    await summary.click();
    assert.equal(await page.locator('.my-words-export__help').getAttribute('open'), null);
    await page.locator('.my-words-export__help summary').click();
    assert.equal(await page.locator('.my-words-export__help p').first().isVisible(), true);
    await page.keyboard.press('Escape');
    assert.equal(await panel.getAttribute('open'), null);
    assert.equal(await summary.evaluate(el => el === document.activeElement), true);
    await summary.click();
    await page.getByRole('button', { name: 'Neueste zuerst' }).click();
    assert.equal(await panel.getAttribute('open'), null);
    assert.equal(await page.getByRole('button', { name: 'Neueste zuerst' }).getAttribute('aria-pressed'), 'true');
  } finally { await context.close(); }
});
