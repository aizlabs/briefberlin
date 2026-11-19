// Run with NODE_PATH pointing to an installed Playwright package: node --test tests/js/*.browser.cjs
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
let server, browser, origin;
const words = [
  { id: 'one', term: 'die Genehmigung', english: 'permission', explanation: 'Eine Erlaubnis.', defaultGlossary: true },
  { id: 'two', term: 'beantragen', english: 'to apply', explanation: 'Einen Antrag stellen.', defaultGlossary: false },
  { id: 'three', term: 'beantragen', english: 'to apply', explanation: 'Einen Antrag stellen.', defaultGlossary: false },
  { id: 'four', term: 'verborgen', english: 'hidden', explanation: 'Nicht sichtbar.', defaultGlossary: false }
];
function article(noGlossary) {
  return `<!doctype html><html lang="de"><head><meta name="briefberlin-base-path" content=""><style>.article-glossary-popup{position:fixed;background:white;border:1px solid;padding:12px;width:300px}[hidden]{display:none!important}button{min-height:44px}</style><script defer src="/assets/js/my-words-store.js"></script><script defer src="/assets/js/glossary-popup.js"></script></head><body><article class="page" data-article-title="Testartikel" data-article-url="/articles/test/" data-my-words-url="/meine-woerter/"><section class="page__content"><p>${words.map(w => `<button class="article-term ${!noGlossary && w.defaultGlossary ? 'article-term--default' : ''}" data-term-id="${w.id}">${w.term}</button>`).join(' ')}</p>${noGlossary ? '' : '<h2 id="vokabeln">Vokabeln</h2><ul><li><strong>die Genehmigung</strong> - permission - Eine Erlaubnis.</li></ul>'}<script type="application/json" class="article-glossary-data">${JSON.stringify(noGlossary ? words.map(w => ({ ...w, defaultGlossary: false })) : words)}</script></section></article></body></html>`;
}
before(async () => {
  server = http.createServer((req, res) => {
    if (/^\/assets\/js\/[a-z-]+\.js$/.test(req.url)) {
      res.setHeader('Content-Type', 'text/javascript; charset=utf-8'); res.end(fs.readFileSync(path.join('output', req.url))); return;
    }
    res.setHeader('Content-Type', 'text/html; charset=utf-8'); let markup = article(req.url.includes('empty'));
    if (req.url.includes('mixed-hints')) markup = markup.replace(JSON.stringify(words), JSON.stringify([null, ...words, { id: 'invalid', term: 2 }]));
    if (req.url.includes('invalid-locale')) markup = markup.replace('class="article-glossary-data"', 'class="article-glossary-data" data-glossary-locale="invalid_locale!"');
    if (req.url.includes('missing-original-row')) markup = markup.replace('<li><strong>die Genehmigung</strong> - permission - Eine Erlaubnis.</li>', '');
    if (req.url.includes('invalid-url')) markup = markup.replace('data-article-url="/articles/test/"', 'data-article-url="http://["');
    res.end(markup);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, headless: true } : { headless: true });
});
after(async () => { if (browser) await browser.close(); if (server) await new Promise(resolve => server.close(resolve)); });
async function setup(url = '/articles/test/') { const context = await browser.newContext(); const page = await context.newPage(); page.setDefaultTimeout(5000); page.on('pageerror', error => console.error('PAGE ERROR', error)); await page.goto(origin + url); return { context, page }; }
async function open(page, id) { await page.locator(`[data-term-id="${id}"]`).click(); }
async function saved(page) { return page.evaluate(() => BriefBerlin.words.read().entries); }
test('save, reload, deduplicate, remove and undo additional word', async () => {
  const { context, page } = await setup();
  try {
    assert.equal((await saved(page)).length, 0);
    await open(page, 'two'); await page.getByRole('button', { name: 'beantragen speichern', exact: true }).click();
    assert.equal((await saved(page)).length, 1);
    assert.equal(await page.locator('li[data-my-words-added]').count(), 1);
    assert.equal(await page.locator('.article-term--default').count(), 3);
    await page.reload(); assert.equal(await page.locator('li[data-my-words-added]').count(), 1);
    await open(page, 'three'); await page.getByRole('button', { name: 'beantragen entfernen', exact: true }).click();
    assert.equal((await saved(page)).length, 0); assert.equal(await page.locator('li[data-my-words-added]').count(), 0);
    assert.equal(await page.locator('.article-term--default').count(), 1);
    await page.locator('.article-glossary-popup').getByRole('button', { name: 'Rückgängig' }).click();
    assert.equal((await saved(page)).length, 1);
  } finally { await context.close(); }
});
test('bulk saves visible glossary only; removing original retains editorial row', async () => {
  const { context, page } = await setup();
  try {
    await page.getByRole('button', { name: 'Alle Wörter speichern', exact: true }).click();
    assert.deepEqual((await saved(page)).map(e => e.term), ['die Genehmigung']);
    assert.equal(await page.getByRole('button', { name: 'Alle gespeichert ✓' }).isDisabled(), true);
    await open(page, 'one'); await page.getByRole('button', { name: 'die Genehmigung entfernen', exact: true }).click();
    assert.equal(await page.locator('li').count(), 1); assert.equal(await page.locator('.article-term--default').count(), 1);
    assert.equal(await page.getByRole('button', { name: 'Alle Wörter speichern', exact: true }).isEnabled(), true);
  } finally { await context.close(); }
});
test('dynamic empty glossary is removed; write failures never change presentation', async () => {
  const { context, page } = await setup('/articles/empty/');
  try {
    await open(page, 'two'); await page.getByRole('button', { name: 'beantragen speichern', exact: true }).click();
    assert.equal(await page.locator('h2').count(), 1);
    await page.getByRole('button', { name: 'beantragen entfernen', exact: true }).click(); assert.equal(await page.locator('h2').count(), 0);
    await page.evaluate(() => { Storage.prototype.setItem = () => { throw new Error('quota'); }; });
    await page.getByRole('button', { name: 'beantragen speichern', exact: true }).click();
    assert.equal((await saved(page)).length, 0); assert.equal(await page.locator('h2').count(), 0);
    assert.match(await page.locator('.article-glossary-popup').innerText(), /nicht gespeichert/);
  } finally { await context.close(); }
});

test('inline undo returns focus to the article after popup dismissal', async () => {
  const { context, page } = await setup();
  try {
    await open(page, 'two'); await page.getByRole('button', { name: 'beantragen speichern', exact: true }).click();
    await page.getByRole('button', { name: 'beantragen entfernen', exact: true }).click();
    await page.keyboard.press('Escape');
    await page.locator('.page__content .my-words-status').getByRole('button', { name: 'Rückgängig' }).click();
    assert.equal((await saved(page)).length, 1);
    assert.equal(await page.locator('[data-term-id="two"]').evaluate(el => document.activeElement === el), true);
  } finally { await context.close(); }
});
test('another tab reconciles added rows, original rows, and open popup state', async () => {
  const { context, page } = await setup(); const other = await context.newPage();
  try {
    await other.goto(origin + '/articles/test/'); await open(other, 'two');
    await open(page, 'two'); await page.getByRole('button', { name: 'beantragen speichern', exact: true }).click();
    await other.getByRole('button', { name: 'beantragen entfernen', exact: true }).waitFor();
    assert.equal(await other.locator('li[data-my-words-added]').count(), 1);
    await page.getByRole('button', { name: 'beantragen entfernen', exact: true }).click();
    await other.getByRole('button', { name: 'beantragen speichern', exact: true }).waitFor();
    assert.equal(await other.locator('li[data-my-words-added]').count(), 0);
    assert.equal(await other.locator('li').count(), 1);
  } finally { await context.close(); }
});
test('corrupt storage does not erase editorial content or overwrite saved bytes', async () => {
  const { context, page } = await setup();
  try {
    await page.evaluate(() => localStorage.setItem('briefberlin.myWords.v1', '{bad'));
    await page.reload(); await open(page, 'two');
    await page.getByRole('button', { name: 'beantragen speichern', exact: true }).click();
    assert.equal(await page.evaluate(() => localStorage.getItem('briefberlin.myWords.v1')), '{bad');
    assert.equal(await page.locator('li').count(), 1);
    assert.equal(await page.locator('li[data-my-words-added]').count(), 0);
    assert.match(await page.locator('.article-glossary-popup').innerText(), /nicht gespeichert/);
  } finally { await context.close(); }
});
test('malformed hints and locale do not break valid word controls; invalid URL reports failure', async () => {
  for (const route of ['mixed-hints', 'invalid-locale', 'invalid-url']) {
    const { context, page } = await setup('/articles/' + route + '/');
    try {
      await open(page, 'two'); await page.getByRole('button', { name: 'beantragen speichern', exact: true }).click();
      assert.equal((await saved(page)).length, route === 'invalid-url' ? 0 : 1);
      if (route === 'invalid-url') assert.match(await page.locator('.article-glossary-popup').innerText(), /nicht gespeichert/);
    } finally { await context.close(); }
  }
});

test('an original metadata word restored into a missing row survives personal removal', async () => {
  const { context, page } = await setup('/articles/missing-original-row/');
  try {
    await open(page, 'one'); await page.getByRole('button', { name: 'die Genehmigung speichern', exact: true }).click();
    await page.getByRole('button', { name: 'die Genehmigung entfernen', exact: true }).click();
    assert.equal((await saved(page)).length, 0);
    assert.equal(await page.locator('li').count(), 1);
    assert.equal(await page.locator('[data-term-id="one"]').evaluate(el => el.classList.contains('article-term--default')), true);
  } finally { await context.close(); }
});
test('popup remains in the mobile viewport when a save error expands its content', async () => {
  const { context, page } = await setup();
  try {
    await page.setViewportSize({ width: 375, height: 420 });
    await open(page, 'two');
    const popup = page.locator('.article-glossary-popup');
    const height = (await popup.boundingBox()).height;
    await page.keyboard.press('Escape');
    await page.evaluate(popupHeight => {
      const target = document.querySelector('[data-term-id="two"]');
      target.style.position = 'fixed'; target.style.top = (innerHeight - popupHeight - 44 - 12 - 14) + 'px'; target.style.left = '10px';
      Storage.prototype.setItem = () => { throw new Error('quota'); };
    }, height);
    await open(page, 'two');
    await page.getByRole('button', { name: 'beantragen speichern', exact: true }).click();
    const box = await popup.boundingBox();
    assert.ok(box.y >= 0 && box.y + box.height <= 420, `expanded popup is outside viewport: ${JSON.stringify(box)}`);
  } finally { await context.close(); }
});
