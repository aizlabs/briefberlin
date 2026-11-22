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
    if (req.url.includes('no-store')) markup = markup.replace('<script defer src="/assets/js/my-words-store.js"></script>', '');
    if (req.url.includes('case-variant-row')) markup = markup.replace('<strong>die Genehmigung</strong>', '<strong>Die Genehmigung</strong>');
    if (req.url.includes('ambiguous-case-row')) {
      const extra = [...words, { id: 'sie-lower', term: 'sie', english: 'she', explanation: 'Eine Frau.' }, { id: 'sie-formal', term: 'Sie', english: 'you (formal)', explanation: 'Höfliche Anrede.' }];
      markup = markup.replace(JSON.stringify(words), JSON.stringify(extra)).replace('<li><strong>die Genehmigung</strong> - permission - Eine Erlaubnis.</li>', '<li><strong>die Genehmigung</strong> - permission - Eine Erlaubnis.</li><li><strong>SIE</strong> - she / you</li>');
    }
    if (req.url.includes('inflected-row')) markup = markup.replace('<li><strong>die Genehmigung</strong> - permission - Eine Erlaubnis.</li>', '<li><strong>die Genehmigung</strong> - permission - Eine Erlaubnis.</li><li><strong>beantragt</strong> - applied</li>');
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
test('save, reload and unmark without deleting the saved word', async () => {
  const { context, page } = await setup();
  try {
    assert.equal((await saved(page)).length, 0);
    await open(page, 'two'); await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: beantragen', exact: true }).click();
    assert.equal((await saved(page)).length, 1);
    assert.equal(await page.locator('li[data-my-words-added]').count(), 1);
    assert.equal(await page.locator('.article-term--default').count(), 3);
    await page.reload(); assert.equal(await page.locator('li[data-my-words-added]').count(), 1);
    await open(page, 'three'); await page.getByRole('button', { name: 'Aus Glossar entfernen: beantragen', exact: true }).click();
    assert.equal((await saved(page)).length, 1); assert.equal(await page.locator('li[data-my-words-added]').count(), 0);
    assert.equal(await page.locator('.article-term--default').count(), 1);
    assert.equal(await page.locator('.article-glossary-popup').isHidden(), true);
    assert.equal(await page.locator('[data-term-id="three"]').evaluate(el => document.activeElement === el), true);
    assert.equal(await page.getByRole('button', { name: 'Rückgängig' }).count(), 0);
    assert.equal(await page.locator('.page__content .my-words-status').innerText(), 'Aus Glossar entfernt.');
  } finally { await context.close(); }
});
test('popup still explains words when the store script is missing', async () => {
  const { context, page } = await setup('/articles/no-store/');
  try {
    await open(page, 'two');
    const popup = page.locator('.article-glossary-popup');
    assert.equal(await popup.isVisible(), true);
    assert.match(await popup.innerText(), /to apply/);
    assert.equal(await popup.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: beantragen' }).count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Alle Wörter speichern' }).count(), 0);
  } finally { await context.close(); }
});
test('blocked storage stays quiet while reading definitions and reports a save attempt', async () => {
  const { context, page } = await setup();
  try {
    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('blocked', 'SecurityError'); } });
    });
    await page.reload();
    const status = page.locator('.page__content .my-words-status');
    const popup = page.locator('.article-glossary-popup');
    assert.equal((await status.innerText()).trim(), '');
    await open(page, 'two');
    assert.match(await popup.innerText(), /to apply/);
    assert.equal((await status.innerText()).trim(), '');
    assert.doesNotMatch(await popup.innerText(), /nicht geladen/);
    await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: beantragen', exact: true }).click();
    assert.match(await status.innerText(), /nicht geladen/);
    assert.match(await popup.innerText(), /nicht geladen/);
  } finally { await context.close(); }
});
test('a case-variant vocabulary row still matches its hint', async () => {
  const { context, page } = await setup('/articles/case-variant-row/');
  try {
    await page.getByRole('button', { name: 'Alle Wörter speichern', exact: true }).click();
    assert.deepEqual((await saved(page)).map(e => e.term), ['die Genehmigung']);
    assert.equal(await page.locator('li').count(), 1);
  } finally { await context.close(); }
});
test('ambiguous capitalization and distinct German forms are not guessed', async () => {
  for (const route of ['ambiguous-case-row', 'inflected-row']) {
    const { context, page } = await setup('/articles/' + route + '/');
    try {
      // An unmatched row means "save all" cannot know what it would save.
      assert.equal(await page.getByRole('button', { name: 'Alle Wörter speichern' }).count(), 0, route);
      assert.equal((await saved(page)).length, 0, route);
    } finally { await context.close(); }
  }
});
test('saved state is quiet and unmarking keeps collection data and stays unmarked on reopen', async () => {
  const { context, page } = await setup();
  try {
    await open(page, 'two');
    assert.equal(await page.locator('.article-glossary-popup__remove').isVisible(), false);
    await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: beantragen', exact: true }).click();
    assert.equal(await page.locator('.article-glossary-popup__add').isVisible(), false);
    assert.equal(await page.locator('.my-words-saved').innerText(), '✓ In meinen Wörtern');
    await page.getByRole('button', { name: 'Aus Glossar entfernen: beantragen', exact: true }).click();
    await open(page, 'three');
    assert.equal(await page.locator('.article-glossary-popup__add').isVisible(), false);
    assert.equal(await page.locator('.article-glossary-popup__remove').isVisible(), false);
    assert.equal(await page.locator('li[data-my-words-added]').count(), 0);
    assert.equal((await saved(page)).length, 1);
  } finally { await context.close(); }
});
test('preselected words can be unmarked and excluded from bulk save', async () => {
  const { context, page } = await setup();
  try {
    await open(page, 'one');
    await page.getByRole('button', { name: 'Aus Glossar entfernen: die Genehmigung', exact: true }).click();
    assert.equal(await page.locator('li').count(), 0);
    assert.equal(await page.locator('.article-term--default').count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Alle Wörter speichern', exact: true }).isEnabled(), false);
    assert.equal((await saved(page)).length, 0);
    await open(page, 'two'); await page.locator('.article-glossary-popup__add').click();
    assert.deepEqual((await saved(page)).map(e => e.term), ['beantragen']);
    assert.equal(await page.locator('li').count(), 1);
    await open(page, 'one'); await page.locator('.article-glossary-popup__add').click();
    assert.equal(await page.locator('li').count(), 2);
    assert.equal(await page.locator('.article-term--default').count(), 3);
  } finally { await context.close(); }
});
test('dynamic empty glossary is removed; write failures never change presentation', async () => {
  const { context, page } = await setup('/articles/empty/');
  try {
    await open(page, 'two'); await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: beantragen', exact: true }).click();
    assert.equal(await page.locator('h2').count(), 1);
    await page.getByRole('button', { name: 'Aus Glossar entfernen: beantragen', exact: true }).click(); assert.equal(await page.locator('h2').count(), 0);
    await open(page, 'four');
    await page.evaluate(() => { Storage.prototype.setItem = () => { throw new Error('quota'); }; });
    await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: verborgen', exact: true }).click();
    assert.equal((await saved(page)).length, 1); assert.equal(await page.locator('h2').count(), 0);
    assert.match(await page.locator('.article-glossary-popup').innerText(), /nicht gespeichert/);
  } finally { await context.close(); }
});

test('cross-tab collection updates respect local unmarking', async () => {
  const { context, page } = await setup(); const other = await context.newPage();
  try {
    await other.goto(origin + '/articles/test/'); await open(other, 'two');
    await open(page, 'two'); await page.locator('.article-glossary-popup__add').click();
    await other.locator('.my-words-saved').waitFor({ state: 'visible' });
    await other.locator('.article-glossary-popup__remove').click();
    await open(page, 'four'); await page.locator('.article-glossary-popup__add').click();
    await other.locator('li[data-my-words-term-id="four"]').waitFor();
    assert.equal(await other.locator('li[data-my-words-term-id="two"]').count(), 0);
    assert.equal((await saved(other)).length, 2);
    await open(other, 'two');
    // Collection deletion is available on Meine Wörter, not in the article popup.
    await page.evaluate(() => BriefBerlin.words.remove(BriefBerlin.words.wordKey('de', 'beantragen')));
    await other.locator('.article-glossary-popup__add').waitFor({ state: 'visible' });
    assert.equal(await other.locator('li[data-my-words-term-id="two"]').count(), 0);
  } finally { await context.close(); }
});
test('corrupt storage does not erase editorial content or overwrite saved bytes', async () => {
  const { context, page } = await setup();
  try {
    await page.evaluate(() => localStorage.setItem('briefberlin.myWords.v1', '{bad'));
    await page.reload(); await open(page, 'two');
    await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: beantragen', exact: true }).click();
    assert.equal(await page.evaluate(() => localStorage.getItem('briefberlin.myWords.v1')), '{bad');
    assert.equal(await page.locator('li').count(), 1);
    assert.equal(await page.locator('li[data-my-words-added]').count(), 0);
    assert.match(await page.locator('.article-glossary-popup').innerText(), /nicht geladen/);
  } finally { await context.close(); }
});
test('malformed hints and locale do not break valid word controls; invalid URL reports failure', async () => {
  for (const route of ['mixed-hints', 'invalid-locale', 'invalid-url']) {
    const { context, page } = await setup('/articles/' + route + '/');
    try {
      await open(page, 'two'); await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: beantragen', exact: true }).click();
      assert.equal((await saved(page)).length, route === 'invalid-url' ? 0 : 1);
      if (route === 'invalid-url') assert.match(await page.locator('.article-glossary-popup').innerText(), /nicht gespeichert/);
    } finally { await context.close(); }
  }
});

test('a restored metadata row can be unmarked without deleting the saved word', async () => {
  const { context, page } = await setup('/articles/missing-original-row/');
  try {
    await open(page, 'one'); await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: die Genehmigung', exact: true }).click();
    await page.getByRole('button', { name: 'Aus Glossar entfernen: die Genehmigung', exact: true }).click();
    assert.equal((await saved(page)).length, 1);
    assert.equal(await page.locator('li').count(), 0);
    assert.equal(await page.locator('[data-term-id="one"]').evaluate(el => el.classList.contains('article-term--default')), false);
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
    await page.getByRole('button', { name: 'Zu meinen Wörtern hinzufügen: beantragen', exact: true }).click();
    const box = await popup.boundingBox();
    assert.ok(box.y >= 0 && box.y + box.height <= 420, `expanded popup is outside viewport: ${JSON.stringify(box)}`);
  } finally { await context.close(); }
});

test('unmarking remains available with blocked storage and reload resets article choices', async () => {
  const { context, page } = await setup();
  try {
    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('blocked', 'SecurityError'); } });
    });
    await page.reload(); await open(page, 'one');
    await page.locator('.article-glossary-popup__remove').click();
    assert.equal(await page.locator('li').count(), 0);
    assert.equal(await page.locator('.article-glossary-popup').isHidden(), true);
    await page.reload();
    assert.equal(await page.locator('li').count(), 1);
    assert.equal(await page.locator('.article-term--default').count(), 1);
  } finally { await context.close(); }
});
