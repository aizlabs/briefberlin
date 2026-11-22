(function () {
  "use strict";
  function glossaryDataElement(root) {
    if (!root || !root.querySelector) {
      return null;
    }
    return root.querySelector(".article-glossary-data");
  }

  function parseGlossaryData(root) {
    const dataElement = glossaryDataElement(root);
    if (!dataElement) {
      return new Map();
    }

    try {
      const items = JSON.parse(dataElement.textContent || "[]");
      if (!Array.isArray(items)) return new Map();
      return new Map(items.filter(function (item) {
        return item && typeof item === "object" && typeof item.id === "string" &&
          typeof item.term === "string" && item.term.trim() !== "" &&
          typeof item.english === "string" && typeof item.explanation === "string";
      }).map(function (item) {
        return [item.id, item];
      }));
    } catch (error) {
      return new Map();
    }
  }

  function glossaryHeadingText(pageContent) {
    const article = pageContent.closest ? pageContent.closest("article.page") : null;
    const dataElement = glossaryDataElement(article);
    const configuredHeading = dataElement && dataElement.dataset.glossaryHeading;
    return (configuredHeading || "Vokabeln").trim() || "Vokabeln";
  }

  function glossaryLocale(pageContent) {
    const article = pageContent.closest ? pageContent.closest("article.page") : null;
    const dataElement = glossaryDataElement(article);
    const configuredLocale = dataElement && dataElement.dataset.glossaryLocale;
    const locale = configuredLocale || document.documentElement.lang || "de";
    try { return Intl.getCanonicalLocales(locale)[0] || "de"; }
    catch (_) { return "de"; }
  }

  function normalizedHeading(text, locale) {
    return text.trim().toLocaleLowerCase(locale);
  }

  function findGlossaryList(pageContent, locale) {
    const configuredHeading = normalizedHeading(glossaryHeadingText(pageContent), locale);
    const headings = Array.from(pageContent.querySelectorAll("h2"));
    const glossaryHeading = headings.find(function (heading) {
      const text = normalizedHeading(heading.textContent, locale);
      return (
        text === configuredHeading ||
        text.startsWith(configuredHeading + " ") ||
        heading.id === configuredHeading ||
        heading.id === "vokabeln" ||
        text === "vokabeln" ||
        text.startsWith("vokabeln ")
      );
    });

    if (!glossaryHeading) {
      return null;
    }

    let sibling = glossaryHeading.nextElementSibling;
    while (sibling && sibling.tagName !== "UL" && sibling.tagName !== "H2") {
      sibling = sibling.nextElementSibling;
    }
    return sibling && sibling.tagName === "UL" ? sibling : null;
  }

  function positionPopup(popup, target) {
    const rect = target.getBoundingClientRect();
    const margin = 12;
    popup.hidden = false;

    const popupRect = popup.getBoundingClientRect();
    let left = rect.left + rect.width / 2 - popupRect.width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - popupRect.width - margin));

    let top = rect.bottom + margin;
    if (top + popupRect.height > window.innerHeight - margin) {
      top = Math.max(margin, rect.top - popupRect.height - margin);
    }

    // The anchor can have scrolled out of view while this non-modal popup is open.
    top = Math.max(margin, Math.min(top, window.innerHeight - popupRect.height - margin));
    popup.style.left = left + "px";
    popup.style.top = top + "px";
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  function button(text, className) {
    const node = element("button", className, text);
    node.type = "button";
    return node;
  }
  // Used when my-words-store.js is missing or failed to load: the popup still
  // explains words, it just offers no saving.
  function readOnlyStore() {
    return {
      read: function () { return { ok: true, entries: [] }; },
      canUndo: function () { return false; },
      subscribe: function () {},
      wordKey: function (language, term) {
        return JSON.stringify([language, term.normalize("NFC").trim().replace(/\s+/gu, " ")]);
      },
    };
  }
  function initArticleGlossary(root) {
    const sharedStore = window.BriefBerlin && window.BriefBerlin.words;
    const canSave = !!sharedStore;
    const store = sharedStore || readOnlyStore();
    const pageContent = root.querySelector(".page__content");
    if (!pageContent) return;
    const itemsById = parseGlossaryData(root);
    if (!itemsById.size) return;
    const locale = glossaryLocale(pageContent);
    const language = locale.split(/[-_]/)[0];
    const keyOf = function (item) { return store.wordKey(language, item.term); };
    const itemsByKey = new Map();
    itemsById.forEach(function (item) { if (!itemsByKey.has(keyOf(item))) itemsByKey.set(keyOf(item), item); });
    // Saved-word identity stays case-sensitive (sie/Sie), but list rows are
    // matched to hints by term id, then exact term, then a case-insensitive
    // term only when exactly one hint fits. Ambiguous rows (SIE for sie and
    // Sie) stay unmatched rather than guessing.
    function folded(text) { return text.normalize("NFC").trim().replace(/\s+/gu, " ").toLocaleLowerCase(locale); }
    const keysByFoldedTerm = new Map();
    itemsByKey.forEach(function (item, key) {
      const fold = folded(item.term);
      keysByFoldedTerm.set(fold, keysByFoldedTerm.has(fold) ? null : key);
    });
    let list = findGlossaryList(pageContent, locale);
    let dynamicHeading = null;
    const originalKeys = new Set();
    // Article-only choices last for this page visit, independently of saved words.
    const unmarkedKeys = new Set();
    function rowKey(row) {
      const id = row.dataset.myWordsTermId || row.dataset.termId;
      const byId = id && itemsById.get(id);
      if (byId) return keyOf(byId);
      const term = row.querySelector("strong");
      if (!term) return null;
      const exact = store.wordKey(language, term.textContent);
      return itemsByKey.has(exact) ? exact : keysByFoldedTerm.get(folded(term.textContent)) || exact;
    }
    if (list) Array.from(list.children).forEach(function (row) { if (rowKey(row)) originalKeys.add(rowKey(row)); });
    itemsById.forEach(function (item) { if (item.defaultGlossary) originalKeys.add(keyOf(item)); });
    const status = element("div", "my-words-status");
    status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    pageContent.append(status);
    const popup = element("div", "article-glossary-popup"); popup.hidden = true;
    const inner = element("div", "article-glossary-popup__inner");
    inner.setAttribute("role", "dialog"); inner.setAttribute("aria-label", "Worterklärung");
    const close = button("×", "article-glossary-popup__close"); close.setAttribute("aria-label", "Schließen");
    const term = element("div", "article-glossary-popup__term");
    const translation = element("div", "article-glossary-popup__english");
    const explanation = element("div", "article-glossary-popup__explanation");
    const savedLabel = element("span", "my-words-saved", "✓ In meinen Wörtern");
    const action = button("Zu meinen Wörtern hinzufügen", "article-glossary-popup__add");
    const unmark = button("Aus Glossar entfernen", "article-glossary-popup__remove");
    const popupStatus = element("div", "my-words-status"); popupStatus.setAttribute("role", "status");
    inner.append(close, term, translation, explanation, savedLabel, action, unmark, popupStatus); popup.append(inner); document.body.append(popup);
    let activeItem = null, activeTarget = null;
    let saved = new Set(), readable = true, controls = null, bulk = null;
    // Storage errors are reported only after the reader tries to change their
    // collection (save or save all). Reading a definition is the
    // core reading aid and stays quiet even when storage is unavailable.
    let engaged = false;
    const LOAD_ERROR = "Deine gespeicherten Wörter konnten nicht geladen werden. Deine Daten wurden nicht verändert.";
    function failed() {
      engaged = true;
      message(store.read().ok ? "Die Änderung konnte nicht gespeichert werden. Bitte versuche es erneut." : LOAD_ERROR);
    }
    if (!canSave) { action.hidden = true; savedLabel.hidden = true; }
    function message(text, quietPopup) {
      status.textContent = text; popupStatus.textContent = quietPopup ? "" : text;
      // Status messages can change the popup height.
      if (!popup.hidden && activeTarget) positionPopup(popup, activeTarget);
    }
    function candidate(item) {
      let articleUrl = "";
      try { articleUrl = new URL(root.dataset.articleUrl || "", location.origin).href; }
      catch (_) { /* The store will reject missing/invalid public metadata. */ }
      return { language: language, term: item.term, translation: item.english, explanation: item.explanation,
        articleTitle: root.dataset.articleTitle || "", articleUrl: articleUrl };
    }
    function visibleItems() {
      if (!list) return [];
      return Array.from(list.children).map(function (row) { return itemsByKey.get(rowKey(row)); }).filter(Boolean);
    }
    function ensureList() {
      if (list) return;
      dynamicHeading = element("h2", "", glossaryHeadingText(pageContent));
      list = element("ul");
      const before = pageContent.querySelector("hr") || status;
      pageContent.insertBefore(dynamicHeading, before); pageContent.insertBefore(list, before);
    }
    function ensureControls() {
      if (!canSave || !list || controls) return;
      // An unmatched legacy row cannot be safely included in a 'save all' action.
      if (Array.from(list.children).some(function (row) { return !itemsByKey.has(rowKey(row)); })) return;
      controls = element("div", "my-words-glossary-controls");
      bulk = button("Alle Wörter speichern", "my-words-button");
      const link = element("a", "", "Meine Wörter →"); link.href = root.dataset.myWordsUrl || "/meine-woerter/";
      controls.append(bulk, link); list.before(controls);
      bulk.addEventListener("click", function () {
        // A successful write re-renders through the store subscription.
        const result = store.addMany(visibleItems().map(candidate));
        if (!result.ok) { failed(); return; }
        message("Alle Wörter gespeichert.");
      });
    }
    function updatePopup() {
      if (!activeItem) return;
      const isSaved = saved.has(keyOf(activeItem));
      term.textContent = activeItem.term; translation.textContent = activeItem.english; explanation.textContent = activeItem.explanation;
      const marked = !unmarkedKeys.has(keyOf(activeItem)) && (originalKeys.has(keyOf(activeItem)) || isSaved);
      savedLabel.hidden = !canSave || !isSaved;
      action.hidden = !canSave || isSaved;
      action.setAttribute("aria-label", "Zu meinen Wörtern hinzufügen: " + activeItem.term);
      unmark.hidden = !marked;
      unmark.setAttribute("aria-label", "Aus Glossar entfernen: " + activeItem.term);
    }

    function refresh(state) {
      readable = state.ok;
      if (!state.ok) {
        if (bulk) bulk.disabled = true;
        if (engaged) message(LOAD_ERROR);
      } else {
        saved = new Set(state.entries.map(function (entry) { return entry.key; }));
      }
      itemsByKey.forEach(function (item, key) {
        if (saved.has(key) && !unmarkedKeys.has(key)) {
          ensureList();
          if (!Array.from(list.children).some(function (row) { return rowKey(row) === key; })) {
            const row = element("li"); row.dataset.myWordsAdded = "true"; row.dataset.myWordsTermId = item.id;
            row.append(element("strong", "", item.term), document.createTextNode(" - " + [item.english, item.explanation].filter(Boolean).join(" - ")));
            list.append(row);
          }
        }
      });
      if (list) Array.from(list.children).forEach(function (row) {
        if (unmarkedKeys.has(rowKey(row)) || (row.dataset.myWordsAdded && !originalKeys.has(rowKey(row)) && !saved.has(rowKey(row)))) row.remove();
      });
      pageContent.querySelectorAll(".article-term[data-term-id]").forEach(function (node) {
        const item = itemsById.get(node.dataset.termId);
        if (item) node.classList.toggle("article-term--default", !unmarkedKeys.has(keyOf(item)) && (originalKeys.has(keyOf(item)) || saved.has(keyOf(item))));
      });
      if (list && !list.children.length && dynamicHeading) {
        list.remove(); dynamicHeading.remove(); if (controls) controls.remove();
        list = dynamicHeading = controls = bulk = null;
      }
      ensureControls();
      if (bulk) {
        const visible = visibleItems();
        const complete = visible.length > 0 && visible.every(function (item) { return saved.has(keyOf(item)); });
        bulk.textContent = complete ? "Alle gespeichert ✓" : "Alle Wörter speichern";
        bulk.disabled = !readable || !visible.length || complete;
      }
      updatePopup();
      if (readable || !engaged) message("");
    }
    action.addEventListener("click", function () {
      if (!activeItem) return;
      if (saved.has(keyOf(activeItem))) return;
      const key = keyOf(activeItem);
      const wasUnmarked = unmarkedKeys.delete(key);
      const result = store.add(candidate(activeItem));
      if (!result.ok) {
        if (wasUnmarked) unmarkedKeys.add(key);
        failed(); return;
      }
      message("Wort gespeichert.", true);
      close.focus();
    });
    unmark.addEventListener("click", function () {
      if (!activeItem) return;
      unmarkedKeys.add(keyOf(activeItem));
      refresh(store.read());
      hide(true);
      message("Aus Glossar entfernt.", true);
    });
    pageContent.addEventListener("click", function (event) {
      const target = event.target.closest(".article-term");
      if (!target || !pageContent.contains(target)) return;
      const item = itemsById.get(target.dataset.termId); if (!item) return;
      activeItem = item; activeTarget = target;
      refresh(store.read()); positionPopup(popup, target);
      (!action.hidden ? action : !unmark.hidden ? unmark : close).focus();
    });
    function hide(returnFocus) { popup.hidden = true; if (returnFocus && activeTarget) activeTarget.focus(); }
    close.addEventListener("click", function () { hide(true); });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape" && !popup.hidden) hide(true); });
    document.addEventListener("click", function (event) {
      if (!popup.hidden && !popup.contains(event.target) && !event.target.closest(".article-term")) hide(false);
    });
    // Mobile browsers fire resize while scrolling (address bar), so do not
    // move focus here: focusing the term would scroll the page back to it.
    window.addEventListener("resize", function () { if (!popup.hidden) hide(false); });
    store.subscribe(refresh); refresh(store.read());
  }
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("article.page").forEach(initArticleGlossary);
  });
}());
