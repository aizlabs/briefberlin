const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createStore, wordKey, STORAGE_KEY } = require('../../output/assets/js/my-words-store.js');
function fixture(overrides = {}) {
  let raw = null, writes = 0;
  const storage = { getItem: () => raw, setItem: (_, value) => { raw = value; writes++; } };
  const store = createStore({ storage: () => storage, origin: 'https://briefberlin.de', now: () => '2026-11-19T10:00:00.000Z', ...overrides });
  return { store, storage, raw: () => raw, setRaw: value => raw = value, writes: () => writes };
}
function entry(term = 'die Genehmigung', overrides = {}) {
  return { term, language: 'de', translation: 'permission', explanation: 'Eine Erlaubnis.', articleTitle: 'Neue Regeln', articleUrl: 'https://briefberlin.de/articles/neue-regeln/', ...overrides };
}
test('normalizes identity without merging capitalization or inflections', () => {
  assert.equal(wordKey('de', '  scho\u0308n   sein '), wordKey('de', 'schön sein'));
  assert.notEqual(wordKey('de', 'sie'), wordKey('de', 'Sie'));
  assert.notEqual(wordKey('de', 'beantragen'), wordKey('de', 'beantragt'));
});
test('starts empty, saves exact content, deduplicates and preserves first save', () => {
  const f = fixture();
  assert.deepEqual(f.store.read().entries, []);
  assert.equal(f.store.add(entry()).ok, true);
  const first = f.raw();
  f.store.add(entry('die Genehmigung', { explanation: 'Different', articleUrl: 'https://briefberlin.de/articles/other/' }));
  assert.equal(f.raw(), first);
  assert.equal(f.writes(), 1);
  assert.equal(JSON.parse(first).schemaVersion, 1);
  assert.equal(f.store.read().entries[0].savedAt, '2026-11-19T10:00:00.000Z');
});
test('batch is deduplicated, atomic and emits one change', () => {
  const f = fixture(); let events = 0;
  f.store.subscribe(() => events++);
  f.store.addMany([entry(), entry(), entry('beantragen')]);
  assert.equal(f.writes(), 1); assert.equal(events, 1);
  assert.equal(f.store.read().entries.length, 2);
  const original = f.raw();
  assert.equal(f.store.addMany([entry('neu'), entry('bad', { articleUrl: 'https://evil.test/articles/x/' })]).ok, false);
  assert.equal(f.raw(), original);
});
test('remove and undo restore full entry; new mutation clears undo', () => {
  const f = fixture(); f.store.add(entry());
  const saved = f.store.read().entries[0];
  f.store.remove(saved.key); assert.equal(f.store.canUndo(), true);
  f.store.undo(); assert.deepEqual(f.store.read().entries, [saved]);
  f.store.remove(saved.key); f.store.add(entry('neu')); assert.equal(f.store.canUndo(), false);
});
test('undo does not overwrite an entry already restored elsewhere', () => {
  const f = fixture(); f.store.add(entry()); const saved = f.store.read().entries[0]; f.store.remove(saved.key);
  f.setRaw(JSON.stringify({ schemaVersion: 1, entries: [{ ...saved, explanation: 'Other tab' }] }));
  f.store.undo(); assert.equal(f.store.read().entries[0].explanation, 'Other tab');
});
test('corrupt and unsupported collections are preserved and reported unreadable', () => {
  const f = fixture();
  for (const raw of ['{', JSON.stringify({ schemaVersion: 2, entries: [] })]) {
    f.setRaw(raw); assert.equal(f.store.read().ok, false); assert.equal(f.store.add(entry()).ok, false); assert.equal(f.raw(), raw);
  }
});
test('invalid entries and duplicate keys are skipped but kept verbatim on write', () => {
  const f = fixture(); f.store.add(entry()); const saved = f.store.read().entries[0];
  const invalid = { ...saved, term: 'kaputt', key: wordKey('de', 'kaputt'), savedAt: 'no' };
  f.setRaw(JSON.stringify({ schemaVersion: 1, entries: [saved, invalid, saved] }));
  assert.deepEqual(f.store.read().entries, [saved]);
  assert.equal(f.store.add(entry('neu')).ok, true);
  const written = JSON.parse(f.raw()).entries;
  assert.deepEqual(written.map(e => e.term), ['die Genehmigung', 'neu', 'die Genehmigung', 'kaputt']);
  assert.deepEqual(written[3], invalid);
  assert.equal(f.store.read().hidden, 1);
});
test('a word whose saved link no longer matches the site stays readable', () => {
  const old = fixture(); old.store.add(entry()); old.store.add(entry('beantragen'));
  // Same data, read after the configured base path changed.
  const f = fixture({ basePath: '/preview' }); f.setRaw(old.raw());
  const state = f.store.read();
  assert.deepEqual(state.entries.map(e => e.term), ['die Genehmigung', 'beantragen']);
  assert.equal(state.hidden, 0);
  assert.equal(f.store.linkable(state.entries[0]), false);
  assert.equal(old.store.linkable(state.entries[0]), true);
  // Existing records are not rewritten, but new saves still need a current link.
  assert.equal(f.store.add(entry('neu')).ok, false);
  assert.equal(f.store.add(entry('neu', { articleUrl: 'https://briefberlin.de/preview/articles/x/' })).ok, true);
  assert.equal(JSON.parse(f.raw()).entries[0].articleUrl, 'https://briefberlin.de/articles/neue-regeln/');
});
test('removing a word drops its duplicates, undo restores them, malformed records stay', () => {
  const f = fixture(); f.store.add(entry()); const saved = f.store.read().entries[0];
  const duplicate = { ...saved, explanation: 'Eine andere Fassung.' };
  const malformed = { ...saved, savedAt: 'kaputt' };
  f.setRaw(JSON.stringify({ schemaVersion: 1, entries: [saved, duplicate, malformed] }));
  assert.equal(f.store.remove(saved.key).ok, true);
  assert.deepEqual(f.store.read().entries, []);
  assert.deepEqual(JSON.parse(f.raw()).entries, [malformed]);
  assert.equal(f.store.undo().ok, true);
  assert.deepEqual(JSON.parse(f.raw()).entries, [saved, duplicate, malformed]);
});
test('subscribers receive the committed state without another storage read', () => {
  const f = fixture(); let reads = 0; const getItem = f.storage.getItem;
  f.storage.getItem = (...args) => { reads++; return getItem(...args); };
  let received = null; f.store.subscribe(state => { received = state; });
  f.store.add(entry());
  assert.equal(reads, 1);
  assert.deepEqual(received.entries.map(e => e.term), ['die Genehmigung']);
});
test('access and quota failures do not report success or emit changes', () => {
  const denied = fixture({ storage: () => { throw Error('blocked'); } });
  assert.equal(denied.store.add(entry()).ok, false);
  const f = fixture(); let events = 0; f.store.subscribe(() => events++);
  f.storage.setItem = () => { throw Error('quota'); };
  assert.equal(f.store.add(entry()).ok, false); assert.equal(events, 0); assert.equal(f.raw(), null);
});
test('validates same-origin public URLs and configured base path', () => {
  const f = fixture({ basePath: '/preview' });
  for (const url of ['https://briefberlin.de/articles/a/', 'https://briefberlin.de/private-input/a', 'javascript:alert(1)', 'https://briefberlin.de/preview/articles/a/#secret', 'https://briefberlin.de/preview/articles/a/?secret=x']) {
    assert.equal(f.store.add(entry('word', { articleUrl: url })).ok, false);
  }
  assert.equal(f.store.add(entry('word', { articleUrl: 'https://briefberlin.de/preview/articles/a/' })).ok, true);
});
test('refresh events and mutations read latest storage', () => {
  const events = new EventTarget(); const f = fixture({ events }); let changes = 0;
  f.store.subscribe(() => changes++); f.store.add(entry());
  const other = { ...entry('other'), key: wordKey('de', 'other'), savedAt: '2026-11-18T10:00:00.000Z' };
  f.setRaw(JSON.stringify({ schemaVersion: 1, entries: [other] })); f.store.add(entry('new'));
  assert.deepEqual(f.store.read().entries.map(e => e.term), ['other', 'new']);
  const event = new Event('storage'); event.key = STORAGE_KEY; events.dispatchEvent(event);
  events.dispatchEvent(new Event('pageshow')); assert.equal(changes, 3, 'a normal load pageshow does not re-render');
  const restored = new Event('pageshow'); restored.persisted = true; events.dispatchEvent(restored);
  assert.equal(changes, 4);
});

test('invalid batch inputs return explicit failure without writing', () => {
  const f = fixture();
  for (const input of [null, undefined, {}, 'word']) {
    assert.deepEqual(f.store.addMany(input), { ok: false, error: 'invalid-entry' });
  }
  assert.equal(f.writes(), 0);
});
test('invalid calendar dates are rejected rather than silently normalized', () => {
  const f = fixture(); f.store.add(entry()); const saved = f.store.read().entries[0];
  const raw = JSON.stringify({ schemaVersion: 1, entries: [{ ...saved, savedAt: '2026-02-30T10:00:00.000Z' }] });
  f.setRaw(raw);
  assert.deepEqual(f.store.read().entries, []);
  assert.equal(f.store.add(entry('new')).ok, true);
  assert.equal(JSON.parse(f.raw()).entries[1].savedAt, '2026-02-30T10:00:00.000Z');
});
test('only public vocabulary fields are persisted', () => {
  const f = fixture();
  assert.equal(f.store.add(entry('word', { privateSource: 'confidential', draft: 'unpublished' })).ok, true);
  assert.equal(f.raw().includes('confidential'), false);
  assert.equal(f.raw().includes('unpublished'), false);
});
test('subscriber failure cannot turn a committed write into a failure or block other subscribers', () => {
  const f = fixture(); let notifications = 0;
  const original = console.error;
  console.error = () => {};
  try {
    f.store.subscribe(() => { throw Error('render failed'); });
    f.store.subscribe(() => notifications++);
    assert.equal(f.store.add(entry()).ok, true);
    assert.equal(f.store.read().entries.length, 1);
    assert.equal(notifications, 1);
  } finally { console.error = original; }
});
test('unrelated session storage events do not clear pending undo', () => {
  const events = new EventTarget(); const f = fixture({ events });
  f.store.add(entry()); f.store.remove(f.store.read().entries[0].key);
  const unrelated = new Event('storage'); unrelated.key = STORAGE_KEY; unrelated.storageArea = {};
  events.dispatchEvent(unrelated);
  assert.equal(f.store.canUndo(), true);
  const matching = new Event('storage'); matching.key = STORAGE_KEY; matching.storageArea = f.storage;
  events.dispatchEvent(matching);
  assert.equal(f.store.canUndo(), false);
});
test('rejects encoded traversal and separators while allowing Unicode article slugs', () => {
  const f = fixture();
  for (const suffix of ['%2F..%2Fprivate-input%2Fsecret/', '%5C..%5Cprivate/', '%252e%252e/private/', '%ZZ/']) {
    assert.equal(f.store.add(entry('word', { articleUrl: 'https://briefberlin.de/articles/' + suffix })).ok, false);
  }
  assert.equal(f.store.add(entry('word', { articleUrl: 'https://briefberlin.de/articles/%C3%A4nderungen/' })).ok, true);
});
