// @ts-check
/**
 * Patcher 2 — Emulated active-window state (Q2 / Q1=B).
 *
 * Выставляет `data-window-active="true|false"` на <html> в зависимости
 * от document.hasFocus(). При `=false` (неактивное окно) CSS притухает
 * материалы (toolbar, modal) — см. style.css:
 *
 *     :root[data-window-active="false"] .toolbar,
 *     :root[data-window-active="false"] .modal { filter: saturate(0.94); }
 *
 * Работает и в Chrome, и в pywebview (hasFocus есть в обоих).
 */

function _currentActiveState() {
  try {
    return document.hasFocus() ? 'true' : 'false';
  } catch (_e) {
    return 'true';
  }
}

function apply() {
  try {
    document.documentElement.dataset.windowActive = _currentActiveState();
  } catch (_e) {
    // no-op: атрибут декоративный, ошибка не должна ломать UI
  }
}

export function installWindowChrome() {
  const w = /** @type {any} */ (window);
  if (w.__pdbWindowChromeInstalled) return;
  w.__pdbWindowChromeInstalled = true;
  window.addEventListener('focus', apply);
  window.addEventListener('blur', apply);
  document.addEventListener('visibilitychange', apply);
  apply();
}
