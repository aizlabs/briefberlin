const { test } = require('node:test');
const assert = require('node:assert/strict');
const exporter = require('../../output/assets/js/my-words-export.js');
const entry = { term: 'die Änderung', translation: 'change, "revision"', explanation: 'Eine Änderung.\nДругая строка\tmehr', articleTitle: 'Regeln & <Neues>', articleUrl: 'https://briefberlin.de/articles/regeln/' };
function parseDelimited(text, separator) {
  const rows = []; let row = [], value = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') { if (quoted && text[i + 1] === '"') { value += '"'; i++; } else quoted = !quoted; }
    else if (c === separator && !quoted) { row.push(value); value = ''; }
    else if (c === '\n' && !quoted) { row.push(value.replace(/\r$/, '')); rows.push(row); row = []; value = ''; }
    else value += c;
  }
  return rows;
}
test('CSV has UTF-8 BOM, five columns and round-trips Unicode, quotes, comma and multiline content', () => {
  const output = exporter.csv([entry]); assert.ok(output.startsWith('\ufeff'));
  const rows = parseDelimited(output.slice(1), ',');
  assert.deepEqual(rows[0], ['Wort','Übersetzung','Erklärung','Artikeltitel','Artikel-URL']);
  assert.deepEqual(rows[1], Object.values(entry));
});
test('CSV protects formula-like cells without mutating inputs', () => {
  for (const value of ['=1+1', '+SUM(A1)', '-1', '@SUM(A1)', ' \t=1', '\r=1', '\nword', '\tword', '\u0001@x']) {
    const data = { ...entry, translation: value };
    assert.equal(parseDelimited(exporter.csv([data]).slice(1), ',')[1][1], "'" + value);
    assert.equal(data.translation, value);
  }
});
test('Anki is two fields per record, escaped HTML, safe linked source and no raw embedded tabs or newlines', () => {
  const output = exporter.anki([entry, { ...entry, term: '"<img src=x>"', translation: '', explanation: '' }]);
  const lines = output.trimEnd().split('\n');
  assert.deepEqual(lines.slice(0,2), ['#separator:Tab','#html:true']);
  const rows = parseDelimited(lines.slice(2).join('\n') + '\n', '\t');
  assert.equal(rows.length, 2); assert.ok(rows.every(row=>row.length===2));
  assert.equal(rows[0][0], entry.term);
  assert.match(rows[0][1], /Другая строка&#9;mehr/);
  assert.match(rows[0][1], /href="https:\/\/briefberlin.de\/articles\/regeln\/"/);
  assert.match(rows[0][1], /Regeln &amp; &lt;Neues&gt;/);
  assert.equal(rows[1][0], '&quot;&lt;img src=x&gt;&quot;');
  assert.ok(!rows[1][1].startsWith('<br>'));
});
test('Anki rejects executable URLs', () => {
  assert.throws(() => exporter.anki([{ ...entry, articleUrl: 'javascript:alert(1)' }]));
});
test('serializers preserve supplied order and original values', () => {
  const entries = [{ ...entry, term: 'Zug' }, { ...entry, term: 'Änderung' }]; const snapshot = JSON.stringify(entries);
  assert.deepEqual(parseDelimited(exporter.csv(entries).slice(1), ',').slice(1).map(row=>row[0]), ['Zug','Änderung']);
  assert.ok(exporter.anki(entries).indexOf('Zug') < exporter.anki(entries).indexOf('Änderung'));
  assert.equal(JSON.stringify(entries), snapshot);
});
test('filenames use local calendar date', () => {
  assert.equal(exporter.filename('csv', new Date(2026, 0, 2, 23)), 'briefberlin-meine-woerter-2026-01-02.csv');
  assert.equal(exporter.filename('anki', new Date(2026, 0, 2)), 'briefberlin-meine-woerter-2026-01-02-anki.txt');
});
test('download revokes object URL even when DOM setup fails', () => {
  const vm = require('node:vm'); const fs = require('node:fs');
  const source = fs.readFileSync(require.resolve('../../output/assets/js/my-words-export.js'), 'utf8');
  for (const failure of ['create', 'append', 'click', null]) {
    let removed = 0, revoked = 0, scheduled = 0;
    const anchor = { remove() { removed++; }, click() { if (failure === 'click') throw Error('blocked'); } };
    const document = {
      createElement() { if (failure === 'create') throw Error('blocked'); return anchor; },
      body: { append() { if (failure === 'append') throw Error('blocked'); } }
    };
    const window = { document, setTimeout(callback) { scheduled++; callback(); } };
    const context = vm.createContext({ window, Blob, URL: { createObjectURL() { return 'blob:test'; }, revokeObjectURL(url) { assert.equal(url, 'blob:test'); revoked++; } } });
    vm.runInContext(source, context);
    if (failure) assert.throws(() => window.BriefBerlin.wordExport.download([entry], 'csv'));
    else assert.equal(window.BriefBerlin.wordExport.download([entry], 'csv'), true);
    assert.equal(removed, failure === 'create' ? 0 : 1);
    assert.equal(revoked, 1); assert.equal(scheduled, 1);
  }
});
