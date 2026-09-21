/**
 * Wikipedia-style language selector.
 *
 * The markup is a <details>/<summary> that already opens, closes and reports
 * expanded state with zero JavaScript. This file is pure progressive
 * enhancement: it reveals the search field, filters the list, and adds keyboard
 * navigation. With JS disabled the selector degrades to a plain visible list.
 *
 * Interaction patterns (click-outside guard, Escape handling, resize-to-close,
 * viewport margin constant) intentionally mirror assets/js/glossary-popup.js.
 */
(function () {
  "use strict";

  var VIEWPORT_MARGIN = 12;

  // --- audio continuity across language switches -------------------------
  //
  // Every language of an article is its own document, so navigating tears the
  // <audio> element down. We stash position + rate + playing state and restore
  // it on the next page, keyed on the audio SRC so it only ever resumes the same
  // recording (all 8 languages of an article share the German track).
  //
  // This is resume-across-navigation, not gapless: the new document still has to
  // load. Truly uninterrupted playback would require client-side navigation.
  var AUDIO_KEY = "briefberlin:audio-position";
  var AUDIO_MAX_AGE_MS = 10 * 60 * 1000;

  function currentAudio() {
    return document.querySelector(".article-audio__native");
  }

  function saveAudioState() {
    var audio = currentAudio();
    if (!audio || !audio.currentSrc || !audio.currentTime) {
      return;
    }
    try {
      sessionStorage.setItem(AUDIO_KEY, JSON.stringify({
        src: audio.currentSrc,
        time: audio.currentTime,
        rate: audio.playbackRate,
        playing: !audio.paused && !audio.ended,
        at: Date.now()
      }));
    } catch (error) {
      /* private mode / quota - continuity is a nicety, never a hard failure */
    }
  }

  function restoreAudioState() {
    var audio = currentAudio();
    if (!audio) {
      return;
    }

    var raw;
    try {
      raw = sessionStorage.getItem(AUDIO_KEY);
    } catch (error) {
      return;
    }
    if (!raw) {
      return;
    }

    var state;
    try {
      state = JSON.parse(raw);
    } catch (error) {
      return;
    }
    if (!state || !state.src || Date.now() - state.at > AUDIO_MAX_AGE_MS) {
      return;
    }

    function apply() {
      // Only resume the same recording.
      if (audio.currentSrc !== state.src) {
        return;
      }
      // Everything below is best-effort. A throw here previously aborted the
      // function before audio.play(), silently killing the whole resume feature.
      try {
        applyState();
      } catch (error) {
        /* position/rate restore is a nicety; never block playback */
      }
      resumePlayback();
    }

    function applyState() {
      if (state.time > 0 && state.time < (audio.duration || Infinity)) {
        audio.currentTime = state.time;
      }
      if (state.rate) {
        audio.playbackRate = state.rate;
        // Compare data-speed numerically rather than building an attribute
        // selector: the stored rate is a Number, so "1" vs "1.0" string
        // mismatches would silently fail to highlight the right pill.
        document.querySelectorAll(".article-audio__speed button").forEach(function (other) {
          var rate = parseFloat(other.getAttribute("data-speed"));
          other.classList.toggle("is-active", rate === state.rate);
        });
      }
    }

    function resumePlayback() {
      if (!state.playing) {
        return;
      }
      var attempt = audio.play();
      // Autoplay policy can refuse on a fresh document. Staying paused at the
      // right position is the correct degradation - not an error.
      if (attempt && typeof attempt.catch === "function") {
        attempt.catch(function () {});
      }
    }

    if (audio.readyState >= 1) {
      apply();
    } else {
      audio.addEventListener("loadedmetadata", apply, { once: true });
    }
  }

  function initAudioContinuity() {
    restoreAudioState();
    // pagehide covers link clicks, back/forward and reloads in one hook.
    window.addEventListener("pagehide", saveAudioState);
    document.addEventListener("click", function (event) {
      if (event.target.closest && event.target.closest(".language-selector__link")) {
        saveAudioState();
      }
    });
  }

  function normalize(value) {
    if (!value) {
      return "";
    }
    var text = String(value).toLocaleLowerCase();
    // Diacritic folding is a no-op for Arabic/Cyrillic but makes "Türkçe"
    // reachable by typing "turkce" on a plain keyboard, which is the real use case.
    try {
      return text.normalize("NFD").replace(/\p{Diacritic}/gu, "");
    } catch (error) {
      return text;
    }
  }

  function setup(root) {
    var summary = root.querySelector(".language-selector__toggle");
    var panel = root.querySelector(".language-selector__panel");
    var search = root.querySelector(".language-selector__search");
    var input = root.querySelector(".language-selector__search-input");
    var empty = root.querySelector(".language-selector__empty");
    var items = Array.prototype.slice.call(
      root.querySelectorAll(".language-selector__item")
    );

    if (!summary || !panel || !items.length) {
      return;
    }

    if (search) {
      search.hidden = false;
    }

    function visibleLinks() {
      return items
        .filter(function (item) {
          return !item.hidden;
        })
        .map(function (item) {
          return item.querySelector(".language-selector__link");
        })
        .filter(Boolean);
    }

    function focusables() {
      var list = [summary];
      if (input && search && !search.hidden) {
        list.push(input);
      }
      return list.concat(visibleLinks());
    }

    function close(restoreFocus) {
      if (!root.open) {
        return;
      }
      root.open = false;
      if (restoreFocus) {
        summary.focus();
      }
    }

    function position() {
      root.classList.remove("language-selector--flip-up");
      var rect = panel.getBoundingClientRect();
      if (rect.bottom > window.innerHeight - VIEWPORT_MARGIN) {
        root.classList.add("language-selector--flip-up");
      }
    }

    function filter() {
      var query = normalize(input ? input.value : "").trim();
      var matches = 0;

      items.forEach(function (item) {
        if (!query) {
          item.hidden = false;
          matches += 1;
          return;
        }
        var haystack = [
          normalize(item.getAttribute("data-endonym")),
          normalize(item.getAttribute("data-english")),
          normalize(item.getAttribute("data-code"))
        ].join(" ");
        var hit = haystack.indexOf(query) !== -1;
        item.hidden = !hit;
        if (hit) {
          matches += 1;
        }
      });

      if (empty) {
        empty.hidden = matches !== 0;
      }
    }

    function moveFocus(links, from, delta) {
      if (!links.length) {
        return;
      }
      var index = links.indexOf(from);
      var next;
      if (index === -1) {
        next = delta > 0 ? 0 : links.length - 1;
      } else {
        next = (index + delta + links.length) % links.length;
      }
      links[next].focus();
    }

    root.addEventListener("toggle", function () {
      summary.setAttribute("aria-expanded", root.open ? "true" : "false");
      if (root.open) {
        position();
      }
    });

    if (input) {
      input.addEventListener("input", filter);
      input.addEventListener("keydown", function (event) {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          moveFocus(visibleLinks(), null, 1);
        }
      });
    }

    panel.addEventListener("keydown", function (event) {
      // Only ArrowDown/ArrowUp: the horizontal arrows swap meaning under
      // dir="rtl" and the list is vertical anyway.
      var links = visibleLinks();
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveFocus(links, document.activeElement, 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        moveFocus(links, document.activeElement, -1);
      } else if (event.key === "Home") {
        event.preventDefault();
        if (links.length) {
          links[0].focus();
        }
      } else if (event.key === "End") {
        event.preventDefault();
        if (links.length) {
          links[links.length - 1].focus();
        }
      }
    });

    root.addEventListener("keydown", function (event) {
      if (event.key !== "Tab" || !root.open) {
        return;
      }
      var order = focusables();
      if (!order.length) {
        return;
      }
      var index = order.indexOf(document.activeElement);
      if (index === -1) {
        return;
      }
      var next = event.shiftKey ? index - 1 : index + 1;
      if (next < 0 || next >= order.length) {
        event.preventDefault();
        order[next < 0 ? order.length - 1 : 0].focus();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && root.open) {
        close(true);
      }
    });

    document.addEventListener("click", function (event) {
      if (!root.open) {
        return;
      }
      if (event.target.closest && event.target.closest(".language-selector") === root) {
        return;
      }
      close(false);
    });

    // The mobile bottom sheet and the desktop dropdown position differently, so
    // a genuine resize while open would leave the panel misplaced.
    //
    // Only WIDTH changes count. Height-only resizes are fired constantly by
    // things that must not close the panel: the on-screen keyboard opening when
    // the user focuses the search field, and mobile browser chrome collapsing on
    // scroll. Closing on those made the search box unusable on a phone.
    var lastWidth = window.innerWidth;
    window.addEventListener("resize", function () {
      if (window.innerWidth === lastWidth) {
        return;
      }
      lastWidth = window.innerWidth;
      close(false);
    });
  }

  function init() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-language-selector]"),
      setup
    );
    initAudioContinuity();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
