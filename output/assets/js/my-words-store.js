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
    function valid(entry) {
      if (!entry || typeof entry !== "object") return false;
      if (!ENTRY_FIELDS.every(function (field) { return typeof entry[field] === "string"; })) return false;
      if (!entry.term.trim() || !entry.language || !entry.articleTitle.trim()) return false;
      if (entry.key !== wordKey(entry.language, entry.term)) return false;
      const savedTime = Date.parse(entry.savedAt);
      if (!Number.isFinite(savedTime) || new Date(savedTime).toISOString() !== entry.savedAt) return false;
      try {
        const url = new URL(entry.articleUrl);
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
    // Invalid or duplicate entries are skipped, not fatal: one bad record (or a
    // later change to the article URL contract) must not lock the whole list.
    // They are kept verbatim in `preserved` and written back on every commit,
    // so stored data is never silently discarded.
    function read() {
      try {
        const raw = options.storage().getItem(STORAGE_KEY);
        if (raw === null) return { ok: true, entries: [], preserved: [] };
        const data = JSON.parse(raw);
        if (!data || data.schemaVersion !== 1 || !Array.isArray(data.entries)) {
          return { ok: false, error: "invalid-data" };
        }
        const entries = [], preserved = [], keys = new Set();
        data.entries.forEach(function (entry) {
          if (valid(entry) && !keys.has(entry.key)) { entries.push(entry); keys.add(entry.key); }
          else preserved.push(entry);
        });
        return { ok: true, entries: entries, preserved: preserved };
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
    function commit(entries, preserved, removed) {
      try {
        options.storage().setItem(STORAGE_KEY, JSON.stringify({ schemaVersion: 1, entries: entries.concat(preserved) }));
      } catch (_) { return { ok: false, error: "storage-write" }; }
      undoEntry = removed || null;
      const state = { ok: true, entries: entries, preserved: preserved };
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
        if (!valid(entry)) return { ok: false, error: "invalid-entry" };
        if (!keys.has(entry.key)) { entries.push(entry); keys.add(entry.key); }
      }
      return entries.length === state.entries.length ? state : commit(entries, state.preserved);
    }
    function remove(key) {
      const state = read();
      if (!state.ok) return state;
      const entry = state.entries.find(function (e) { return e.key === key; });
      if (!entry) return state;
      // Drop preserved duplicates of the removed word too, or the next read
      // would promote one of them and the word would reappear.
      const preserved = state.preserved.filter(function (e) { return !e || e.key !== key; });
      return commit(state.entries.filter(function (e) { return e.key !== key; }), preserved, entry);
    }
    function undo() {
      const state = read();
      if (!state.ok || !undoEntry) return state;
      if (state.entries.some(function (e) { return e.key === undoEntry.key; })) {
        undoEntry = null;
        notify(state);
        return state;
      }
      return commit(state.entries.concat([undoEntry]), state.preserved);
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
