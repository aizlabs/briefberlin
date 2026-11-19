(function (root) {
  "use strict";
  const STORAGE_KEY = "briefberlin.myWords.v1";
  const ENTRY_FIELDS = ["key", "language", "term", "translation", "explanation", "articleTitle", "articleUrl", "savedAt"];
  function wordKey(language, term) {
    return JSON.stringify([language, term.normalize("NFC").trim().replace(/\s+/gu, " ")]);
  }
  function createStore(options) {
    const origin = options.origin;
    const articlePath = (options.basePath || "").replace(/\/$/, "") + "/articles/";
    const listeners = new Set();
    let undoEntry = null;
    // A record is readable vocabulary when its own fields are intact. Its
    // source link is checked separately: a link that no longer matches the
    // current site (for example after a base-path change) must not hide the word.
    function validRecord(entry) {
      if (!entry || typeof entry !== "object") return false;
      if (!ENTRY_FIELDS.every(function (field) { return typeof entry[field] === "string"; })) return false;
      if (!entry.term.trim() || !entry.language || !entry.articleTitle.trim()) return false;
      if (entry.key !== wordKey(entry.language, entry.term)) return false;
      const savedTime = Date.parse(entry.savedAt);
      return Number.isFinite(savedTime) && new Date(savedTime).toISOString() === entry.savedAt;
    }
    function linkable(articleUrl) {
      try {
        const url = new URL(articleUrl);
        // A path prefix is insufficient if an encoded separator or traversal
        // segment is interpreted differently by the server or a later consumer.
        const safeSegments = url.pathname.split("/").every(function (segment) {
          const decoded = decodeURIComponent(segment);
          return decoded !== "." && decoded !== ".." && !/[\\/%]/.test(decoded);
        });
        return safeSegments && url.origin === origin && /^https?:$/.test(url.protocol) &&
          !url.username && !url.password && !url.search && !url.hash &&
          url.pathname.startsWith(articlePath) && url.pathname.length > articlePath.length;
      } catch (_) { return false; }
    }
    // Stored records fall into three groups:
    // - entries: readable words, the first record per key;
    // - duplicates: later readable records for a key already listed;
    // - malformed: records that cannot be shown. They are counted in `hidden`
    //   and written back untouched on every commit.
    function snapshot(entries, duplicates, malformed) {
      return { ok: true, entries: entries, duplicates: duplicates, malformed: malformed, hidden: malformed.length };
    }
    function read() {
      try {
        const raw = options.storage().getItem(STORAGE_KEY);
        if (raw === null) return snapshot([], [], []);
        const data = JSON.parse(raw);
        if (!data || data.schemaVersion !== 1 || !Array.isArray(data.entries)) {
          return { ok: false, error: "invalid-data" };
        }
        const entries = [], duplicates = [], malformed = [], keys = new Set();
        data.entries.forEach(function (entry) {
          if (!validRecord(entry)) malformed.push(entry);
          else if (keys.has(entry.key)) duplicates.push(entry);
          else { entries.push(entry); keys.add(entry.key); }
        });
        return snapshot(entries, duplicates, malformed);
      } catch (_) { return { ok: false, error: "storage-read" }; }
    }
    function notify(state) {
      // A rendering failure must not change the result of an already committed
      // write or prevent another view from receiving its notification.
      const current = state || read();
      listeners.forEach(function (listener) {
        try { listener(current); }
        catch (error) { if (root.console) root.console.error("Meine Wörter subscriber failed", error); }
      });
    }
    function commit(entries, duplicates, malformed, removed) {
      try {
        options.storage().setItem(STORAGE_KEY, JSON.stringify({ schemaVersion: 1, entries: entries.concat(duplicates, malformed) }));
      } catch (_) { return { ok: false, error: "storage-write" }; }
      undoEntry = removed || null;
      const state = snapshot(entries, duplicates, malformed);
      notify(state);
      return state;
    }
    function addMany(candidates) {
      if (!Array.isArray(candidates)) return { ok: false, error: "invalid-entry" };
      const state = read();
      if (!state.ok) return state;
      const entries = state.entries.slice();
      const keys = new Set(entries.map(function (e) { return e.key; }));
      const timestamp = (options.now || function () { return new Date().toISOString(); })();
      for (const candidate of candidates) {
        if (!candidate || typeof candidate.term !== "string" || typeof candidate.language !== "string") return { ok: false, error: "invalid-entry" };
        // Persist only the public vocabulary contract, never unrelated metadata
        // carried by a caller's article object.
        const entry = {};
        ENTRY_FIELDS.forEach(function (field) { entry[field] = candidate[field]; });
        entry.key = wordKey(candidate.language, candidate.term);
        entry.savedAt = timestamp;
        // New saves must also carry a current, safe article link.
        if (!validRecord(entry) || !linkable(entry.articleUrl)) return { ok: false, error: "invalid-entry" };
        if (!keys.has(entry.key)) { entries.push(entry); keys.add(entry.key); }
      }
      return entries.length === state.entries.length ? state : commit(entries, state.duplicates, state.malformed);
    }
    function remove(key) {
      const state = read();
      if (!state.ok) return state;
      const entry = state.entries.find(function (e) { return e.key === key; });
      if (!entry) return state;
      // Readable duplicates of the word go too, or the next read would promote
      // one and the word would reappear; undo restores them all. Malformed
      // records are never touched by a removal.
      const dropped = state.duplicates.filter(function (e) { return e.key === key; });
      return commit(state.entries.filter(function (e) { return e.key !== key; }),
        state.duplicates.filter(function (e) { return e.key !== key; }), state.malformed,
        { entry: entry, duplicates: dropped });
    }
    function undo() {
      const state = read();
      if (!state.ok || !undoEntry) return state;
      const pending = undoEntry;
      if (state.entries.some(function (e) { return e.key === pending.entry.key; })) {
        undoEntry = null;
        notify(state);
        return state;
      }
      return commit(state.entries.concat([pending.entry]), state.duplicates.concat(pending.duplicates), state.malformed);
    }
    if (options.events) {
      options.events.addEventListener("storage", function (event) {
        // sessionStorage uses the same event type but is not this collection.
        try { if (event.storageArea && event.storageArea !== options.storage()) return; }
        catch (_) { notify(); return; }
        if (event.key === STORAGE_KEY || event.key === null) { undoEntry = null; notify(); }
      });
      // Only a back/forward-cache restore can show stale state; a normal load
      // already renders from its own initial read.
      options.events.addEventListener("pageshow", function (event) {
        if (event.persisted) { undoEntry = null; notify(); }
      });
    }
    return { read: read, addMany: addMany, add: function (entry) { return addMany([entry]); },
      remove: remove, undo: undo, canUndo: function () { return !!undoEntry; },
      linkable: function (entry) { return !!entry && linkable(entry.articleUrl); },
      subscribe: function (listener) { listeners.add(listener); return function () { listeners.delete(listener); }; },
      wordKey: wordKey };
  }
  const api = { createStore: createStore, wordKey: wordKey, STORAGE_KEY: STORAGE_KEY };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root.document) {
    root.BriefBerlin = root.BriefBerlin || {};
    const config = root.document.querySelector('meta[name="briefberlin-base-path"]');
    root.BriefBerlin.words = createStore({ storage: function () { return root.localStorage; },
      origin: root.location.origin, basePath: config ? config.content : "", events: root });
  }
})(typeof window !== "undefined" ? window : globalThis);
