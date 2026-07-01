(function () {
  function parseGlossaryData(root) {
    const dataElement = root.querySelector(".article-glossary-data");
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

  function findGlossaryList(pageContent) {
    const headings = Array.from(pageContent.querySelectorAll("h2"));
    const glossaryHeading = headings.find(function (heading) {
      const text = heading.textContent.trim().toLowerCase();
      return heading.id === "vokabeln" || text === "vokabeln" || text.startsWith("vokabeln ");
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
    heading.textContent = "Vokabeln";
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

  function addToGlossary(pageContent, item, addedTerms) {
    const key = item.term.toLocaleLowerCase("de");
    if (addedTerms.has(key)) {
      return false;
    }

    const list = findGlossaryList(pageContent) || createGlossaryList(pageContent);
    const row = document.createElement("li");
    row.dataset.termId = item.id;

    const term = document.createElement("strong");
    term.textContent = item.term;
    row.appendChild(term);
    row.appendChild(document.createTextNode(" - " + glossaryDefinition(item)));
    list.appendChild(row);

    addedTerms.add(key);
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

  function setPopupContent(popup, item, pageContent, addedTerms) {
    popup.querySelector(".article-glossary-popup__term").textContent = item.term;
    popup.querySelector(".article-glossary-popup__english").textContent = item.english || "";
    popup.querySelector(".article-glossary-popup__explanation").textContent = item.explanation || "";

    const addButton = popup.querySelector(".article-glossary-popup__add");
    const key = item.term.toLocaleLowerCase("de");
    addButton.disabled = addedTerms.has(key);
    addButton.textContent = addButton.disabled ? "Schon in der Vokabelliste" : "Zur Vokabelliste hinzufügen";
    addButton.onclick = function () {
      if (addToGlossary(pageContent, item, addedTerms)) {
        addButton.disabled = true;
        addButton.textContent = "Hinzugefügt";
      }
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
    const addedTerms = new Set(
      Array.from(itemsById.values())
        .filter(function (item) {
          return item.defaultGlossary;
        })
        .map(function (item) {
          return item.term.toLocaleLowerCase("de");
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

      setPopupContent(popup, item, pageContent, addedTerms);
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
