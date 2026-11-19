(function (root) {
  "use strict";
  function quoted(value) { return '"' + String(value).replace(/"/g, '""') + '"'; }
  function spreadsheetText(value) {
    const text = String(value);
    // Quoting alone does not stop spreadsheet formula interpretation.
    return /^[\s\u0000-\u001f]*[=+@-]/u.test(text) || /^[\t\r\n]/.test(text) ? "'" + text : text;
  }
  function csv(entries) {
    const rows = [["Wort", "Übersetzung", "Erklärung", "Artikeltitel", "Artikel-URL"]];
    entries.forEach(function (entry) {
      rows.push([entry.term, entry.translation, entry.explanation, entry.articleTitle, entry.articleUrl].map(spreadsheetText));
    });
    return "\ufeff" + rows.map(function (row) { return row.map(quoted).join(","); }).join("\r\n") + "\r\n";
  }
  function html(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/\r\n|\r|\n/g, "<br>").replace(/\t/g, "&#9;");
  }
  function anki(entries) {
    // Omit localized column labels: Anki can mis-map unknown field names to tags.
    const rows = ["#separator:Tab", "#html:true"];
    entries.forEach(function (entry) {
      const back = [entry.translation, entry.explanation].filter(Boolean).map(html);
      if (!entry.articleUrl) back.push("Artikel: " + html(entry.articleTitle));
      else {
        const url = new URL(entry.articleUrl);
        if (!/^https?:$/.test(url.protocol)) throw new Error("Invalid article URL");
        back.push('Artikel: <a href="' + html(url.href) + '">' + html(entry.articleTitle) + "</a>");
      }
      rows.push([html(entry.term), back.join("<br>")].map(quoted).join("\t"));
    });
    return rows.join("\n") + "\n";
  }
  function filename(format, date) {
    const day = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
    return "briefberlin-meine-woerter-" + day + (format === "csv" ? ".csv" : "-anki.txt");
  }
  function download(entries, format) {
    if (!entries.length || !["csv", "anki"].includes(format)) return false;
    const blob = new Blob([format === "csv" ? csv(entries) : anki(entries)], { type: format === "csv" ? "text/csv;charset=utf-8" : "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    let anchor;
    try {
      anchor = root.document.createElement("a");
      anchor.href = url; anchor.download = filename(format, new Date());
      root.document.body.append(anchor); anchor.click();
    } finally {
      if (anchor) anchor.remove();
      root.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }
    return true;
  }
  const api = { csv: csv, anki: anki, filename: filename, download: download };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root.document) { root.BriefBerlin = root.BriefBerlin || {}; root.BriefBerlin.wordExport = api; }
})(typeof window !== "undefined" ? window : globalThis);
