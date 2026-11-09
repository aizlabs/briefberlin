/** Article text size, shared across stories and reader languages. */
(function () {
  "use strict";

  var STORAGE_KEY = "briefberlin:reading-size";
  var SIZES = [100, 125, 150, 175, 200];

  document.querySelectorAll("[data-reading-size]").forEach(function (controls) {
    var article = controls.closest("article");
    if (!article) return;

    var decrease = controls.querySelector("[data-reading-size-decrease]");
    var increase = controls.querySelector("[data-reading-size-increase]");
    var reset = controls.querySelector("[data-reading-size-reset]");
    var value = controls.querySelector("[data-reading-size-value]");
    var index = 0;

    try {
      var storedIndex = SIZES.indexOf(Number(localStorage.getItem(STORAGE_KEY)));
      if (storedIndex !== -1) index = storedIndex;
    } catch (error) {
      // Storage may be blocked; the controls still work for this visit.
    }

    function render() {
      article.style.setProperty("--reading-scale", SIZES[index] / 100);
      value.textContent = SIZES[index] + "%";
      // Keep focus on the button at the limit, including for keyboard users.
      decrease.setAttribute("aria-disabled", String(index === 0));
      increase.setAttribute("aria-disabled", String(index === SIZES.length - 1));
      // Reset disappears at the default size; keep keyboard focus on a control.
      if (index === 0 && document.activeElement === reset) increase.focus();
      reset.setAttribute("aria-disabled", String(index === 0));
    }

    function change(nextIndex) {
      if (nextIndex === index) return;
      index = nextIndex;
      render();
      try {
        localStorage.setItem(STORAGE_KEY, String(SIZES[index]));
      } catch (error) {
        // An unavailable preference store must never prevent resizing.
      }
    }

    decrease.addEventListener("click", function () {
      change(Math.max(0, index - 1));
    });
    increase.addEventListener("click", function () {
      change(Math.min(SIZES.length - 1, index + 1));
    });
    reset.addEventListener("click", function () {
      change(0);
    });

    render();
    controls.hidden = false;
  });
}());
