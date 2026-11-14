// @ts-check
// F-33: ResizeObserver для .toolbar → CSS-переменная --toolbar-h.
// Заменяет hardcoded `top: 86px` на .status-bar.
//
// Значение пишется в :root как px. Если ResizeObserver недоступен —
// fallback на resize-listener. Первый замер — синхронный (до первого paint).

/**
 * Наблюдает за .toolbar и обновляет --toolbar-h.
 * Идемпотентно: повторный вызов не создаёт второй observer.
 */
export function installLayoutMeasure() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (/** @type {any} */ (window).__pdbLayoutMeasureInstalled) return;
  /** @type {any} */ (window).__pdbLayoutMeasureInstalled = true;

  const toolbar = document.querySelector('.toolbar');
  if (!toolbar) return;

  const root = document.documentElement;
  /** @type {number | null} */
  let last = null;

  const update = () => {
    try {
      const h = Math.round(toolbar.getBoundingClientRect().height);
      if (h > 0 && h !== last) {
        last = h;
        root.style.setProperty('--toolbar-h', h + 'px');
      }
    } catch (e) {
      // no-op: layout_measure не должен ломать UI
    }
  };

  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(update);
    ro.observe(toolbar);
  } else {
    window.addEventListener('resize', update, { passive: true });
    window.addEventListener('orientationchange', update, { passive: true });
  }
  update();
  // страховочный повтор после загрузки шрифтов (высота toolbar могла измениться)
  if (document.readyState !== 'complete') {
    window.addEventListener('load', update, { once: true });
  }
}

/**
 * Наблюдает за #attrBar и пишет --attr-bar-h.
 * Идемпотентно.
 */
export function installAttrBarMeasure() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (/** @type {any} */ (window).__pdbAttrBarMeasureInstalled) return;
  /** @type {any} */ (window).__pdbAttrBarMeasureInstalled = true;

  const attrBar = document.getElementById('attrBar');
  if (!attrBar) return;

  const root = document.documentElement;
  /** @type {number | null} */
  let last = null;

  const update = () => {
    try {
      const h = Math.round(attrBar.getBoundingClientRect().height);
      if (h > 0 && h !== last) {
        last = h;
        root.style.setProperty('--attr-bar-h', h + 'px');
      }
    } catch (e) {
      // no-op
    }
  };

  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(update);
    ro.observe(attrBar);
  } else {
    window.addEventListener('resize', update, { passive: true });
    window.addEventListener('orientationchange', update, { passive: true });
  }
  update();
  if (document.readyState !== 'complete') {
    window.addEventListener('load', update, { once: true });
  }
}

