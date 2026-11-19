(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector("[data-my-words-page]");
    const store = window.BriefBerlin && window.BriefBerlin.words;
    if (!root || !store) return;
    const list = root.querySelector("[data-words-list]");
    const count = root.querySelector("[data-words-count]");
    const toolbar = root.querySelector("[data-words-toolbar]");
    const empty = root.querySelector("[data-words-empty]");
    const sort = root.querySelector("[data-words-sort]");
    const status = root.querySelector("[data-words-status]");
    const undo = root.querySelector("[data-words-undo]");
    const retry = root.querySelector("[data-words-retry]");
    const collator = new Intl.Collator("de");
    let entries = [], readable = false, lastRemovedKey = null;
    function ordered() {
      return entries.slice().sort(function (a, b) {
        const alphabetic = collator.compare(a.term, b.term) || a.key.localeCompare(b.key);
        return sort.value === "newest" ? Date.parse(b.savedAt) - Date.parse(a.savedAt) || alphabetic : alphabetic;
      });
    }
    function textElement(tag, text, className) {
      const node = document.createElement(tag); node.textContent = text;
      if (className) node.className = className;
      return node;
    }
    function message(text) { status.textContent = text; undo.hidden = !store.canUndo(); }
    function render() {
      const active = document.activeElement;
      const focusedToolbar = toolbar.contains(active);
      const activeRow = active && active.closest(".my-words-entry");
      const focusedKey = activeRow && list.contains(activeRow) ? activeRow.dataset.wordKey : null;
      const focusedIndex = activeRow ? Array.from(list.children).indexOf(activeRow) : -1;
      const focusedControl = active && active.tagName === "A" ? "a" : "button";
      list.replaceChildren();
      ordered().forEach(function (entry) {
        const row = document.createElement("li"); row.className = "my-words-entry";
        row.dataset.wordKey = entry.key;
        const heading = document.createElement("div"); heading.className = "my-words-entry__heading";
        const remove = textElement("button", "Entfernen", "my-words-text-button"); remove.type = "button";
        remove.dataset.wordKey = entry.key; remove.disabled = !readable;
        remove.setAttribute("aria-label", entry.term + " entfernen");
        heading.append(textElement("strong", entry.term), remove); row.append(heading);
        if (entry.translation) row.append(textElement("p", entry.translation, "my-words-entry__translation"));
        if (entry.explanation) row.append(textElement("p", entry.explanation));
        const source = textElement("p", "Artikel: ", "my-words-entry__source");
        const link = textElement("a", entry.articleTitle); link.href = entry.articleUrl; source.append(link); row.append(source);
        list.append(row);
        remove.addEventListener("click", function () {
          const index = ordered().findIndex(function (item) { return item.key === entry.key; });
          const result = store.remove(entry.key);
          if (!result.ok) { mutationFailed(); return; }
          // The list was already re-rendered through the store subscription.
          lastRemovedKey = entry.key; message("Wort entfernt. ");
          const buttons = list.querySelectorAll("button");
          const next = buttons[Math.min(index, buttons.length - 1)] || root.querySelector("[data-words-articles]");
          next.focus();
        });
      });
      count.hidden = false;
      count.textContent = entries.length + (entries.length === 1 ? " gespeichertes Wort" : " gespeicherte Wörter");
      empty.hidden = entries.length !== 0;
      toolbar.hidden = !entries.length || !readable;
      if (!entries.length && focusedToolbar) root.querySelector("[data-words-articles]").focus();
      if (focusedKey) {
        const rows = Array.from(list.children);
        const targetRow = rows.find(function (node) { return node.dataset.wordKey === focusedKey; }) || rows[Math.min(focusedIndex, rows.length - 1)];
        const target = targetRow ? targetRow.querySelector(focusedControl) : root.querySelector("[data-words-articles]");
        target.focus();
      }
    }
    function refresh(state) {
      readable = state.ok;
      retry.hidden = state.ok;
      if (!state.ok) {
        const focusedToolbar = toolbar.contains(document.activeElement);
        toolbar.hidden = true;
        const focusedRemoval = list.contains(document.activeElement) && document.activeElement.tagName === "BUTTON";
        list.querySelectorAll("button").forEach(function (node) { node.disabled = true; });
        if (focusedRemoval || focusedToolbar) retry.focus();
        message("Deine gespeicherten Wörter konnten nicht geladen werden. Deine Daten wurden nicht verändert.");
        return;
      }
      entries = state.entries; render(); message(store.canUndo() ? "Wort entfernt. " : "");
    }
    function mutationFailed() {
      const state = store.read();
      if (!state.ok) refresh(state);
      else message("Die Änderung konnte nicht gespeichert werden. Bitte versuche es erneut.");
    }
    undo.addEventListener("click", function () {
      const result = store.undo();
      if (!result.ok) { mutationFailed(); return; }
      message("Wort wiederhergestellt.");
      // Return focus to the restored word, not the top of the list.
      const restored = Array.from(list.children).find(function (row) { return row.dataset.wordKey === lastRemovedKey; });
      const target = (restored && restored.querySelector("button")) || list.querySelector("button") || root.querySelector("[data-words-articles]");
      target.focus();
    });
    retry.addEventListener("click", function () {
      refresh(store.read());
      if (readable) (list.querySelector("button") || root.querySelector("[data-words-articles]")).focus();
    });
    sort.addEventListener("change", render);
    root.querySelectorAll("[data-words-download]").forEach(function (button) {
      button.addEventListener("click", function () {
        const state = store.read();
        refresh(state);
        if (!state.ok || !entries.length) return;
        try {
          window.BriefBerlin.wordExport.download(ordered(), button.dataset.wordsDownload);
          const details = root.querySelector("[data-words-export]");
          details.open = false; details.querySelector("summary").focus();
        } catch (_) { message("Die Datei konnte nicht erstellt werden. Bitte versuche es erneut."); }
      });
    });
    store.subscribe(refresh); refresh(store.read());
  });
}());
