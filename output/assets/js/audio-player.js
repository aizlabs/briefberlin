(function () {
  const SPEEDS = [0.5, 0.75, 1];
  const BAR_COUNT = 96;

  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) {
      return "0:00";
    }

    const wholeSeconds = Math.floor(seconds);
    const minutes = Math.floor(wholeSeconds / 60);
    const remainder = String(wholeSeconds % 60).padStart(2, "0");
    return `${minutes}:${remainder}`;
  }

  function barHeight(index) {
    const waveA = Math.sin(index * 0.47) * 15;
    const waveB = Math.sin(index * 0.19 + 1.8) * 11;
    const waveC = Math.cos(index * 0.11) * 7;
    return Math.max(18, Math.min(64, Math.round(40 + waveA + waveB + waveC)));
  }

  function clampTime(audio, time) {
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    return Math.max(0, Math.min(duration, time));
  }

  function seekFromPointer(audio, waveform, event) {
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    if (duration <= 0) {
      return;
    }

    const rect = waveform.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    audio.currentTime = duration * ratio;
  }

  function setPlayButton(playButton, isPlaying) {
    const icon = playButton.querySelector("i");
    playButton.setAttribute("aria-label", isPlaying ? "Pausar" : "Reproducir");

    if (!icon) {
      return;
    }

    icon.classList.toggle("fa-play", !isPlaying);
    icon.classList.toggle("fa-pause", isPlaying);
  }

  function updateProgress(audio, waveform, elapsed, duration) {
    const audioDuration = Number.isFinite(audio.duration) ? audio.duration : 0;
    const ratio = audioDuration > 0 ? audio.currentTime / audioDuration : 0;
    const percent = Math.max(0, Math.min(100, ratio * 100));
    const playedBars = Math.round((percent / 100) * BAR_COUNT);

    waveform.style.setProperty("--audio-progress", `${percent}%`);
    waveform.setAttribute("aria-valuenow", String(Math.round(percent)));
    waveform.querySelectorAll(".article-audio__waveform-bar").forEach(function (bar, index) {
      bar.classList.toggle("is-played", index < playedBars);
    });
    elapsed.textContent = formatTime(audio.currentTime);
    duration.textContent = formatTime(audioDuration);
  }

  function textNodes(element) {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let node = walker.nextNode();
    while (node) {
      nodes.push(node);
      node = walker.nextNode();
    }
    return nodes;
  }

  function wrapCues(target, block, cues) {
    if (!target || target.textContent !== block.text) {
      return [];
    }

    const wrapped = [];
    let blockOffset = 0;
    textNodes(target).forEach(function (node) {
      const nodeStart = blockOffset;
      const nodeEnd = nodeStart + node.nodeValue.length;
      blockOffset = nodeEnd;
      const intersections = cues.filter(function (cue) {
        return cue.text_start < nodeEnd && cue.text_end > nodeStart;
      });
      if (intersections.length === 0) {
        return;
      }

      const fragment = document.createDocumentFragment();
      let cursor = 0;
      intersections.forEach(function (cue) {
        const start = Math.max(0, cue.text_start - nodeStart);
        const end = Math.min(node.nodeValue.length, cue.text_end - nodeStart);
        if (start > cursor) {
          fragment.appendChild(document.createTextNode(node.nodeValue.slice(cursor, start)));
        }
        const span = document.createElement("span");
        span.className = "article-audio-word";
        span.dataset.cueIndex = String(cue.index);
        span.dataset.blockId = cue.block_id;
        if (cue.sentence_id !== null && cue.sentence_id !== undefined) {
          span.dataset.sentenceId = String(cue.sentence_id);
        }
        span.textContent = node.nodeValue.slice(start, end);
        fragment.appendChild(span);
        wrapped.push({ cue: cue, element: span, target: target });
        cursor = end;
      });
      if (cursor < node.nodeValue.length) {
        fragment.appendChild(document.createTextNode(node.nodeValue.slice(cursor)));
      }
      node.parentNode.replaceChild(fragment, node);
    });
    return wrapped;
  }

  function blockTargets(page, blocks) {
    const targets = new Map();
    const title = page.querySelector(".page__title");
    const paragraphs = Array.from(page.querySelectorAll(".page__content > p"));
    let paragraphIndex = 0;

    blocks.forEach(function (block) {
      if (block.kind === "title" && title && title.textContent === block.text) {
        targets.set(block.id, title);
      }
      if (block.kind === "body") {
        while (paragraphIndex < paragraphs.length) {
          const candidate = paragraphs[paragraphIndex];
          paragraphIndex += 1;
          if (candidate.textContent === block.text) {
            targets.set(block.id, candidate);
            break;
          }
        }
      }
    });
    return targets;
  }

  async function initTextHighlighting(root, audio) {
    const timingsUrl = root.dataset.timingsUrl;
    if (!timingsUrl) {
      return;
    }

    try {
      const response = await fetch(timingsUrl, { credentials: "omit" });
      if (!response.ok) {
        return;
      }
      const timings = await response.json();
      if (timings.version !== 1 || !Array.isArray(timings.blocks) || !Array.isArray(timings.cues)) {
        return;
      }

      const page = root.closest(".page");
      if (!page) {
        return;
      }
      const targets = blockTargets(page, timings.blocks);
      const indexedCues = timings.cues.map(function (cue, index) {
        return Object.assign({ index: index }, cue);
      });
      const cueElements = new Map();
      const sentenceElements = new Map();
      const cueTargets = new Map();

      timings.blocks.forEach(function (block) {
        const target = targets.get(block.id);
        const blockCues = indexedCues.filter(function (cue) {
          return cue.block_id === block.id;
        });
        wrapCues(target, block, blockCues).forEach(function (wrapped) {
          const cueList = cueElements.get(wrapped.cue.index) || [];
          cueList.push(wrapped.element);
          cueElements.set(wrapped.cue.index, cueList);
          cueTargets.set(wrapped.cue.index, wrapped.target);
          const sentenceKey = `${wrapped.cue.block_id}:${wrapped.cue.sentence_id}`;
          const sentenceList = sentenceElements.get(sentenceKey) || [];
          sentenceList.push(wrapped.element);
          sentenceElements.set(sentenceKey, sentenceList);
        });
      });

      if (cueElements.size === 0) {
        return;
      }

      const contextMode = root.dataset.highlightContext === "paragraph" ? "paragraph" : "sentence";
      let activeIndex = -1;
      let animationFrame = null;

      function clearActive() {
        page.querySelectorAll(".article-audio-word.is-active-word").forEach(function (element) {
          element.classList.remove("is-active-word");
        });
        page.querySelectorAll(".article-audio-word.is-active-context").forEach(function (element) {
          element.classList.remove("is-active-context");
        });
        page.querySelectorAll(".is-active-audio-paragraph").forEach(function (element) {
          element.classList.remove("is-active-audio-paragraph");
        });
        activeIndex = -1;
      }

      function cueAt(time) {
        let low = 0;
        let high = indexedCues.length - 1;
        let candidate = -1;
        while (low <= high) {
          const middle = Math.floor((low + high) / 2);
          if (indexedCues[middle].start <= time) {
            candidate = middle;
            low = middle + 1;
          } else {
            high = middle - 1;
          }
        }
        return candidate >= 0 && time <= indexedCues[candidate].end ? candidate : -1;
      }

      function updateHighlight() {
        const nextIndex = cueAt(audio.currentTime);
        if (nextIndex === activeIndex) {
          return;
        }
        clearActive();
        if (nextIndex < 0 || !cueElements.has(nextIndex)) {
          return;
        }
        activeIndex = nextIndex;
        cueElements.get(nextIndex).forEach(function (element) {
          element.classList.add("is-active-word");
        });
        const cue = indexedCues[nextIndex];
        if (contextMode === "paragraph") {
          const target = cueTargets.get(nextIndex);
          if (target) {
            target.classList.add("is-active-audio-paragraph");
          }
        } else {
          const sentenceKey = `${cue.block_id}:${cue.sentence_id}`;
          (sentenceElements.get(sentenceKey) || []).forEach(function (element) {
            element.classList.add("is-active-context");
          });
        }
      }

      function animate() {
        updateHighlight();
        if (!audio.paused && !audio.ended) {
          animationFrame = window.requestAnimationFrame(animate);
        }
      }

      audio.addEventListener("play", function () {
        if (animationFrame !== null) {
          window.cancelAnimationFrame(animationFrame);
        }
        animate();
      });
      audio.addEventListener("seeked", updateHighlight);
      audio.addEventListener("pause", function () {
        if (animationFrame !== null) {
          window.cancelAnimationFrame(animationFrame);
          animationFrame = null;
        }
        clearActive();
      });
      audio.addEventListener("ended", clearActive);
    } catch (_error) {
      // Audio playback remains fully functional when timing data cannot be loaded or mapped.
    }
  }

  function initPlayer(root) {
    const audio = root.querySelector(".article-audio__native");
    const player = root.querySelector(".article-audio__player");
    const playButton = root.querySelector(".article-audio__play");
    const skipBack = root.querySelector(".article-audio__skip-back");
    const skipForward = root.querySelector(".article-audio__skip-forward");
    const waveform = root.querySelector(".article-audio__waveform");
    const elapsed = root.querySelector(".article-audio__elapsed");
    const duration = root.querySelector(".article-audio__duration");
    const speedButtons = Array.from(root.querySelectorAll(".article-audio__speed button"));

    if (!audio || !player || !playButton || !skipBack || !skipForward || !waveform || !elapsed || !duration) {
      return;
    }

    waveform.innerHTML = "";
    for (let index = 0; index < BAR_COUNT; index += 1) {
      const bar = document.createElement("span");
      bar.className = "article-audio__waveform-bar";
      bar.style.setProperty("--bar-height", `${barHeight(index)}%`);
      waveform.appendChild(bar);
    }

    root.classList.add("is-enhanced");
    player.removeAttribute("aria-hidden");
    audio.playbackRate = 1;

    playButton.addEventListener("click", function () {
      if (audio.paused) {
        audio.play();
      } else {
        audio.pause();
      }
    });

    skipBack.addEventListener("click", function () {
      audio.currentTime = clampTime(audio, audio.currentTime - 10);
    });

    skipForward.addEventListener("click", function () {
      audio.currentTime = clampTime(audio, audio.currentTime + 10);
    });

    speedButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        const speed = Number(button.dataset.speed);
        if (!SPEEDS.includes(speed)) {
          return;
        }

        audio.playbackRate = speed;
        speedButtons.forEach(function (speedButton) {
          speedButton.classList.toggle("is-active", speedButton === button);
        });
      });
    });

    let isDragging = false;

    waveform.addEventListener("pointerdown", function (event) {
      isDragging = true;
      waveform.setPointerCapture(event.pointerId);
      seekFromPointer(audio, waveform, event);
    });

    waveform.addEventListener("pointermove", function (event) {
      if (isDragging) {
        seekFromPointer(audio, waveform, event);
      }
    });

    waveform.addEventListener("pointerup", function (event) {
      isDragging = false;
      if (waveform.hasPointerCapture(event.pointerId)) {
        waveform.releasePointerCapture(event.pointerId);
      }
    });

    waveform.addEventListener("pointercancel", function () {
      isDragging = false;
    });

    waveform.addEventListener("lostpointercapture", function () {
      isDragging = false;
    });

    waveform.addEventListener("keydown", function (event) {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        audio.currentTime = clampTime(audio, audio.currentTime - 5);
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        audio.currentTime = clampTime(audio, audio.currentTime + 5);
      }
    });

    audio.addEventListener("play", function () {
      setPlayButton(playButton, true);
    });
    audio.addEventListener("pause", function () {
      setPlayButton(playButton, false);
    });
    audio.addEventListener("ended", function () {
      setPlayButton(playButton, false);
    });
    audio.addEventListener("timeupdate", function () {
      updateProgress(audio, waveform, elapsed, duration);
    });
    audio.addEventListener("loadedmetadata", function () {
      updateProgress(audio, waveform, elapsed, duration);
    });
    audio.addEventListener("durationchange", function () {
      updateProgress(audio, waveform, elapsed, duration);
    });

    updateProgress(audio, waveform, elapsed, duration);
    setPlayButton(playButton, !audio.paused);
    initTextHighlighting(root, audio);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".article-audio").forEach(initPlayer);
  });
})();
