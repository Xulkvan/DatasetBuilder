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
    const args = el.dataset.args ? JSON.parse(`[${el.dataset.args}]`) : [];

    if (typeof window[action] === 'function') {
      // Передаем event последним аргументом (как было в onclick="fn(event)")
      window[action](...args, e);
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
