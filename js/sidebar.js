// @ts-check
// Sidebar resizer module (STAGE 2).
// Вынесен из js/main.js согласно AGENTS.md («main.js — не модульный»).

const STORAGE_KEY = "pdb_sidebar_width";
const MIN_WIDTH = 240;
const MAX_WIDTH = 560;

/**
 * @param {number} w
 * @returns {number}
 */
function clamp(w) {
  return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, w));
}

export function installSidebarResizer() {
  const resizer = document.getElementById("sidebarResizer");
  const sidebar = document.querySelector(".sidebar");
  if (!resizer || !sidebar) return;
  if (/** @type {any} */ (resizer).__pdbInstalled) return;
  /** @type {any} */ (resizer).__pdbInstalled = true;

  try {
    const saved = parseInt(localStorage.getItem(STORAGE_KEY) || "", 10);
    if (!isNaN(saved) && saved >= MIN_WIDTH && saved <= MAX_WIDTH) {
      document.documentElement.style.setProperty("--sidebar-width", saved + "px");
    }
  } catch (e) { /* ignore */ }

  let startX = 0;
  let startWidth = 0;
  let active = false;

  /** @param {PointerEvent} e */
  function onPointerDown(e) {
    if (e.button !== 0) return;
    active = true;
    startX = e.clientX;
    startWidth = sidebar.getBoundingClientRect().width;
    try { resizer.setPointerCapture(e.pointerId); } catch (_) {}
    resizer.classList.add("dragging");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  }

  /** @param {PointerEvent} e */
  function onPointerMove(e) {
    if (!active) return;
    const dx = e.clientX - startX;
    const newWidth = clamp(startWidth + dx);
    document.documentElement.style.setProperty("--sidebar-width", newWidth + "px");
  }

  /** @param {PointerEvent} e */
  function onPointerUp(e) {
    if (!active) return;
    active = false;
    try { resizer.releasePointerCapture(e.pointerId); } catch (_) {}
    resizer.classList.remove("dragging");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    try {
      localStorage.setItem(STORAGE_KEY,
        String(Math.round(sidebar.getBoundingClientRect().width)));
    } catch (_) {}
  }

  resizer.addEventListener("pointerdown", onPointerDown);
  resizer.addEventListener("pointermove", onPointerMove);
  resizer.addEventListener("pointerup", onPointerUp);
  resizer.addEventListener("pointercancel", onPointerUp);

  resizer.addEventListener("keydown", (e) => {
    let delta = 0;
    if (e.key === "ArrowLeft") delta = -16;
    else if (e.key === "ArrowRight") delta = 16;
    else return;
    e.preventDefault();
    const cur = sidebar.getBoundingClientRect().width;
    const newWidth = clamp(cur + delta);
    document.documentElement.style.setProperty("--sidebar-width", newWidth + "px");
    try {
      localStorage.setItem(STORAGE_KEY, String(Math.round(newWidth)));
    } catch (_) {}
  });

  resizer.setAttribute("aria-valuemin", String(MIN_WIDTH));
  resizer.setAttribute("aria-valuemax", String(MAX_WIDTH));
  resizer.setAttribute(
    "aria-valuenow", String(Math.round(sidebar.getBoundingClientRect().width)));
}
