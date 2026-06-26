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
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".article-audio").forEach(initPlayer);
  });
})();
