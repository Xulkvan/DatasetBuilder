// @ts-check
// V11.4.0: Event Delegation
// Заменяет inline onclick/onchange на data-action/data-change-action.
export function initEventDelegation() {
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el) return;

    // Не перехватываем клики, если элемент disabled
    if (el.disabled || el.classList.contains('disabled')) return;

    const action = el.dataset.action;
    let args = [];
    if (el.dataset.args) {
      try {
        args = JSON.parse(`[${el.dataset.args}]`);
      } catch (err) {
        console.error(`[EventDelegation] Invalid data-args on action "${action}":`,
          el.dataset.args, err);
        return;
      }
    }

    if (typeof window[action] === 'function') {
      // Передаем event последним аргументом (как было в onclick="fn(event)")
      try {
        window[action](...args, e);
      } catch (err) {
        console.error(`[EventDelegation] Action "${action}" threw:`, err);
      }
    } else {
      console.warn(`[EventDelegation] Action "${action}" not found on window`);
    }
  });

  document.addEventListener('change', (e) => {
    const el = e.target.closest('[data-change-action]');
    if (!el) return;
    const action = el.dataset.changeAction;
    if (typeof window[action] === 'function') {
      window[action](e);
    } else {
      console.warn(`[EventDelegation] Change Action "${action}" not found on window`);
    }
  });
}
