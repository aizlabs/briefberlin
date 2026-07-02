(function () {
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
      return new Map(items.map(function (item) {
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
    return configuredLocale || document.documentElement.lang || "de";
  }

  function normalizedHeading(text, locale) {
    return text.trim().toLocaleLowerCase(locale);
  }

  function getOrCreatePopup() {
    let popup = document.querySelector(".article-glossary-popup");
    if (popup) {
      return popup;
    }

    popup = document.createElement("div");
    popup.className = "article-glossary-popup";
    popup.hidden = true;
    popup.innerHTML = [
      '<div class="article-glossary-popup__inner" role="dialog" aria-modal="false" aria-live="polite">',
      '  <button class="article-glossary-popup__close" type="button" aria-label="Schließen">',
      '    <i class="fas fa-xmark" aria-hidden="true"></i>',
      '  </button>',
      '  <div class="article-glossary-popup__term"></div>',
      '  <div class="article-glossary-popup__english"></div>',
      '  <div class="article-glossary-popup__explanation"></div>',
      '  <button class="article-glossary-popup__add" type="button">Zur Vokabelliste hinzufügen</button>',
      '</div>',
    ].join("");
    document.body.appendChild(popup);
    return popup;
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

  function createGlossaryList(pageContent) {
    const heading = document.createElement("h2");
    heading.textContent = glossaryHeadingText(pageContent);
    const list = document.createElement("ul");
    const divider = pageContent.querySelector("hr");

    if (divider) {
      pageContent.insertBefore(heading, divider);
      pageContent.insertBefore(list, divider);
    } else {
      pageContent.appendChild(heading);
      pageContent.appendChild(list);
    }

    return list;
  }

  function glossaryDefinition(item) {
    return [item.english, item.explanation].filter(Boolean).join(" - ");
  }

  function glossaryKey(term, locale) {
    return term.toLocaleLowerCase(locale);
  }

  function findGlossaryRow(list, item, locale) {
    if (!list) {
      return null;
    }

    const key = glossaryKey(item.term, locale);
    return Array.from(list.querySelectorAll("li")).find(function (row) {
      if (row.dataset.termId === item.id) {
        return true;
      }

      const term = row.querySelector("strong");
      return term && glossaryKey(term.textContent.trim(), locale) === key;
    }) || null;
  }

  function setArticleTermSelected(pageContent, item, selected) {
    pageContent.querySelectorAll('.article-term[data-term-id="' + item.id + '"]').forEach(function (term) {
      term.classList.toggle("article-term--default", selected);
    });
  }

  function addToGlossary(pageContent, item, selectedTerms, locale) {
    const key = glossaryKey(item.term, locale);
    if (selectedTerms.has(key)) {
      return false;
    }

    const list = findGlossaryList(pageContent, locale) || createGlossaryList(pageContent);
    const row = document.createElement("li");
    row.dataset.termId = item.id;

    const term = document.createElement("strong");
    term.textContent = item.term;
    row.appendChild(term);
    row.appendChild(document.createTextNode(" - " + glossaryDefinition(item)));
    list.appendChild(row);

    selectedTerms.add(key);
    setArticleTermSelected(pageContent, item, true);
    return true;
  }

  function removeFromGlossary(pageContent, item, selectedTerms, locale) {
    const key = glossaryKey(item.term, locale);
    if (!selectedTerms.has(key)) {
      return false;
    }

    const row = findGlossaryRow(findGlossaryList(pageContent, locale), item, locale);
    if (row) {
      row.remove();
    }

    selectedTerms.delete(key);
    setArticleTermSelected(pageContent, item, false);
    return true;
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

    popup.style.left = left + "px";
    popup.style.top = top + "px";
  }

  function setPopupContent(popup, item, pageContent, selectedTerms, locale) {
    popup.querySelector(".article-glossary-popup__term").textContent = item.term;
    popup.querySelector(".article-glossary-popup__english").textContent = item.english || "";
    popup.querySelector(".article-glossary-popup__explanation").textContent = item.explanation || "";

    const addButton = popup.querySelector(".article-glossary-popup__add");
    const key = glossaryKey(item.term, locale);
    const selected = selectedTerms.has(key);
    addButton.disabled = false;
    addButton.textContent = selected ? "Aus Vokabelliste entfernen" : "Zur Vokabelliste hinzufügen";
    addButton.onclick = function () {
      if (selectedTerms.has(key)) {
        removeFromGlossary(pageContent, item, selectedTerms, locale);
      } else {
        addToGlossary(pageContent, item, selectedTerms, locale);
      }
      setPopupContent(popup, item, pageContent, selectedTerms, locale);
    };
  }

  function initArticleGlossary(root) {
    const pageContent = root.querySelector(".page__content");
    if (!pageContent) {
      return;
    }

    const itemsById = parseGlossaryData(root);
    if (!itemsById.size) {
      return;
    }

    const popup = getOrCreatePopup();
    const locale = glossaryLocale(pageContent);
    const selectedTerms = new Set(
      Array.from(itemsById.values())
        .filter(function (item) {
          return item.defaultGlossary;
        })
        .map(function (item) {
          return glossaryKey(item.term, locale);
        })
    );

    pageContent.addEventListener("click", function (event) {
      const target = event.target.closest(".article-term");
      if (!target || !pageContent.contains(target)) {
        return;
      }

      const item = itemsById.get(target.dataset.termId);
      if (!item) {
        return;
      }

      setPopupContent(popup, item, pageContent, selectedTerms, locale);
      positionPopup(popup, target);
    });

    popup.querySelector(".article-glossary-popup__close").addEventListener("click", function () {
      popup.hidden = true;
    });

    document.addEventListener("click", function (event) {
      if (popup.hidden) {
        return;
      }
      if (event.target.closest(".article-glossary-popup") || event.target.closest(".article-term")) {
        return;
      }
      popup.hidden = true;
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        popup.hidden = true;
      }
    });

    window.addEventListener("resize", function () {
      popup.hidden = true;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("article.page").forEach(initArticleGlossary);
  });
}());
