// @ts-check
/**
 * STAGE 16 — Spatial Continuity (View Transitions API).
 *
 * Обёртка над `document.startViewTransition` для морфинга поповеров
 * из своей кнопки-триггера (Apple HIG «Spatial Continuity»).
 *
 * - Если браузер не поддерживает VTA или включён prefers-reduced-motion,
 *   просто выполняет updateDOM без анимации.
 * - Иначе помечает trigger и target viewTransitionName'ами, запускает
 *   transition и снимает имена после завершения.
 *
 * Все вызовы в проекте — через эту обёртку. Прямой `document.startViewTransition`
 * из UI-кода запрещён (см. AGENTS.md → Motion & Анимации → Spatial Continuity).
 */

/**
 * @param {Element | null} triggerEl
 * @param {Element | null} targetEl
 * @param {() => void} updateDOM
 */
export function withViewTransition(triggerEl, targetEl, updateDOM) {
  if (
    typeof document.startViewTransition !== 'function' ||
    (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  ) {
    updateDOM();
    return;
  }

  if (triggerEl && triggerEl.style) {
    triggerEl.style.viewTransitionName = 'vt-trigger';
  }
  if (targetEl && targetEl.style) {
    targetEl.style.viewTransitionName = 'vt-target';
  }

  const html = document.documentElement;
  html.classList.add('vt-running');

  const cleanup = () => {
    html.classList.remove('vt-running');
    if (triggerEl && triggerEl.style) triggerEl.style.viewTransitionName = '';
    if (targetEl && targetEl.style) targetEl.style.viewTransitionName = '';
  };

  try {
    const transition = document.startViewTransition(() => {
      updateDOM();
    });
    transition.finished.finally(cleanup);
  } catch (e) {
    cleanup();
    updateDOM();
  }
}
