// js/a11y_listbox.js — Patcher 6: roving tabindex helper for ARIA listbox/menu.
//
// A11Y-01/02, F-14, F-15: keyboard and VoiceOver navigation for lists and menus.
//
// Roving tabindex: только один item в DOM имеет tabIndex=0 (tab stop),
// остальные — tabIndex=-1. Стрелки перемещают «активный» (tabIndex=0) item
// и фокусируют его. Enter/Space активирует (по умолчанию — el.click()).
// Esc (если передан onEscape) закрывает меню с возвратом фокуса на trigger.

/**
 * @param {HTMLElement | null} container
 * @param {{
 *   itemSelector?: string,
 *   onActivate?: (el: HTMLElement) => void,
 *   onEscape?: () => void,
 * }} [options]
 */
export function installRovingTabindex(container, options = {}) {
  if (!container) return;
  const itemSelector = options.itemSelector || '[role="option"]';

  // Idempotency: если уже установлен — только обновить tabIndex у
  // текущих items (контейнер мог перерисоваться с новыми детьми).
  if (/** @type {any} */ (container).__pdbRovingInstalled) {
    const list = Array.from(container.querySelectorAll(itemSelector))
      .filter((el) => !(/** @type {HTMLButtonElement} */ (el).disabled));
    list.forEach((el, i) => { (/** @type {HTMLElement} */ (el)).tabIndex = (i === 0 ? 0 : -1); });
    return;
  }
  /** @type {any} */ (container).__pdbRovingInstalled = true;

  const onActivate = options.onActivate || ((el) => el.click());
  const onEscape = options.onEscape || null;

  function items() {
    return Array.from(container.querySelectorAll(itemSelector))
      .filter((el) => !(/** @type {HTMLButtonElement} */ (el).disabled));
  }

  function setActive(idx) {
    const list = items();
    if (idx < 0 || idx >= list.length) return;
    list.forEach((el, i) => {
      (/** @type {HTMLElement} */ (el)).tabIndex = (i === idx ? 0 : -1);
      // aria-selected только для options (listbox), не для menuitem
      const role = el.getAttribute('role');
      if (role === 'option' || el.hasAttribute('aria-selected')) {
        el.setAttribute('aria-selected', i === idx ? 'true' : 'false');
      }
    });
    try { (/** @type {HTMLElement} */ (list[idx])).focus({ preventScroll: false }); }
    catch (e) { /* noop */ }
  }

  container.addEventListener('keydown', (e) => {
    const list = items();
    const idx = list.indexOf(/** @type {HTMLElement} */ (document.activeElement));
    if (idx < 0) return;
    const k = (/** @type {KeyboardEvent} */ (e)).key;
    if (k === 'ArrowDown') {
      e.preventDefault();
      setActive(Math.min(idx + 1, list.length - 1));
    } else if (k === 'ArrowUp') {
      e.preventDefault();
      setActive(Math.max(idx - 1, 0));
    } else if (k === 'Home') {
      e.preventDefault();
      setActive(0);
    } else if (k === 'End') {
      e.preventDefault();
      setActive(list.length - 1);
    } else if (k === 'Enter' || k === ' ') {
      e.preventDefault();
      onActivate(/** @type {HTMLElement} */ (list[idx]));
    } else if (k === 'Escape' && onEscape) {
      e.preventDefault();
      e.stopPropagation();
      onEscape();
    }
  });

  // Initial: первый item focusable, остальные — нет
  const list = items();
  list.forEach((el, i) => { (/** @type {HTMLElement} */ (el)).tabIndex = (i === 0 ? 0 : -1); });
}

if (typeof window !== 'undefined') {
  /** @type {any} */ (window).installRovingTabindex = installRovingTabindex;
}
