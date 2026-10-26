// @ts-check

/**
 * @typedef {import('./types.js').BoxData} BoxData
 * @typedef {import('./types.js').AppState} AppState
 */

// V11.5.0: Reactive State Store (Zustand-like)
const listeners = new Set();
/**
 * @param {(prop: string, value: any) => void} fn
 * @returns {() => void}
 */
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
// [FIX:notify-sync] Синхронное уведомление.
// renderBoxes() зависит от локальных переменных, которые обновляются в subscribe.
// Асинхронный батчинг ломал отображение рамок при открытии фото.
function notify(prop, value) {
  listeners.forEach(fn => fn(prop, value));
}

// Обертка для массива boxes, чтобы ловить push, splice и т.д.
function createReactiveArray(arr) {
  const proxy = new Proxy(arr, {
    set(target, prop, value) {
      target[prop] = value;
      notify('boxes', target);
      return true;
    },
    deleteProperty(target, prop) {
      delete target[prop];
      notify('boxes', target);
      return true;
    }
  });
  ['push', 'pop', 'shift', 'unshift', 'splice', 'sort', 'reverse'].forEach(method => {
    proxy[method] = function(...args) {
      const result = Array.prototype[method].apply(proxy, args);
      notify('boxes', proxy);
      return result;
    };
  });
  return proxy;
}

/**
 * @type {AppState}
 */
export const State = new Proxy({
  boxes: createReactiveArray([]),
  selectedIndex: -1,
  multiSelected: new Set(),
  currentImageId: null,
  zoom: 1,
  panX: 0,
  panY: 0,
}, {
  set(target, prop, value) {
    if (target[prop] === value) return true;
    if (prop === 'boxes' && Array.isArray(value)) {
      target[prop] = createReactiveArray(value);
    } else {
      target[prop] = value;
    }
    notify(prop, target[prop]);
    return true;
  }
});
