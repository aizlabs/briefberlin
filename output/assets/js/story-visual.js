for (const details of document.querySelectorAll(".story-visual__info details")) {
  const button = details.querySelector("summary");
  let hovering = false;

  details.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "mouse" && !details.open) {
      hovering = true;
      details.open = true;
    }
  });
  details.addEventListener("pointerleave", () => {
    if (hovering && !details.contains(document.activeElement)) details.open = false;
    hovering = false;
  });
  button.addEventListener("click", (event) => {
    if (hovering) event.preventDefault();
    hovering = false;
  });
  document.addEventListener("pointerdown", (event) => {
    if (!details.contains(event.target)) details.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && details.open) {
      if (details.contains(document.activeElement)) button.focus();
      details.open = false;
      hovering = false;
    }
  });
}
