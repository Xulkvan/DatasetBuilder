// @ts-check
// V11.6.0: Extracted UI Components (Modals, Dialogs, Tooltips)
import { haptic } from './utils.js';

/* Patcher 4 (F-11): exit-анимация перед dialog.close() */
function _prefersReducedMotion() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch (e) {
    return false;
  }
}


/* ===== Modal stack ===== */
export const MODAL_STACK = [];
let _skipFocusReturnOnce = false;

// Stage 3.8: queue modals opened before auth has loaded.
const _pendingModals = [];
const _AUTH_BYPASS_MODALS = new Set([
  'loginModal', 'setupWizardModal', 'versionsModal', 'guideModal',
]);
window.addEventListener('pdb-auth-loaded', () => {
  const _queue = _pendingModals.splice(0);
  for (const _mid of _queue) {
    try { openModal(_mid); } catch (e) { console.warn('openModal(queue) failed:', _mid, e); }
  }
});

export function openModal(id) {
  if (window.AUTH_STATE && window.AUTH_STATE.loaded === false && !_AUTH_BYPASS_MODALS.has(id)) {
    _pendingModals.push(id);
    return;
  }
  if (window.AUTH_STATE && window.AUTH_STATE.mode === 'team' && !window.AUTH_STATE.is_authenticated) {
    if (!_AUTH_BYPASS_MODALS.has(id)) {
      if (window.setError) window.setError(window.t('error.unauthorized'));
      return;
    }
  }
  const el = document.getElementById(id);
  if (!el) {
    console.error(`[openModal] Element #${id} not found in DOM. DOM corrupted?`);
    return;
  }
  if (el.classList.contains('closing')) el.classList.remove('closing');
  if (MODAL_STACK.includes(id)) return;
  if (el.hasAttribute('open')) return;
  if (el.__focusTimer) { clearTimeout(el.__focusTimer); el.__focusTimer = null; }
  el.__returnFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement : null;
  el.classList.add('open');
  const _modalAnimBox = el.querySelector(':scope > .modal')
                     || el.querySelector(':scope > .command-palette');
  if (_modalAnimBox) {
    _modalAnimBox.classList.add('modal-animating');
    _modalAnimBox.addEventListener('animationend', () => {
      _modalAnimBox.classList.remove('modal-animating');
      _modalAnimBox.style.willChange = '';
    }, { once: true });
    _modalAnimBox.style.willChange = 'transform, opacity';
  }
  MODAL_STACK.push(id);
  if (typeof el.showModal === 'function') {
    try {
      el.showModal();
    } catch (e) {
      try { el.close(); el.showModal(); }
      catch (e2) { el.setAttribute('open', ''); }
    }
  } else {
    el.setAttribute('open', '');
  }
  if (!el.__dialogCloseInstalled) {
    el.__dialogCloseInstalled = true;
    // Backdrop click closes the dialog (native ESC handled by browser).
    el.addEventListener('click', (e) => {
      if (e.target === el) closeModal(id);
    });
    // Keep MODAL_STACK and focus-return consistent across ESC / backdrop.
    el.addEventListener('close', () => {
      const idx = MODAL_STACK.indexOf(id);
      if (idx >= 0) MODAL_STACK.splice(idx, 1);
      el.classList.remove('open');
      const returnFocus = el.__returnFocus;
      el.__returnFocus = null;
      if (returnFocus && document.contains(returnFocus)) {
        _skipFocusReturnOnce = true;
        try { returnFocus.focus({ preventScroll: true }); } catch (e) {}
      }
    });
  }
  const _isVisible = (n) => n && n.offsetParent !== null;
  const _candidates = [
    el.querySelector('[data-autofocus]:not([disabled])'),
    el.querySelector('[autofocus]:not([disabled])'),
    el.querySelector('input:not([type="hidden"]):not([disabled]), textarea:not([disabled])'),
    el.querySelector('.btn-primary:not([disabled])'),
    el.querySelector('button:not([disabled])'),
  ];
  const target = _candidates.find(_isVisible) || null;
  if (target) {
    el.__focusTimer = setTimeout(() => {
      el.__focusTimer = null;
      if (!el.hasAttribute('open')) return;
      try {
        target.focus({ preventScroll: true });
        if (target.select) target.select();
      } catch (e) {}
    }, 80);
  }
}

export function closeModal(id) {
  const el = document.getElementById(id);
  if (!el) {
    const i = MODAL_STACK.indexOf(id);
    if (i >= 0) MODAL_STACK.splice(i, 1);
    return;
  }
  if (document.activeElement && el.contains(document.activeElement)) {
    document.activeElement.blur();
  }
  if (typeof el.close === 'function' && el.hasAttribute('open')) {
    hideTooltip();
    // Patcher 4 (F-11): exit-анимация перед close()
    if (_prefersReducedMotion()) {
      try { el.close(); } catch (e) {}
      return;
    }
    const modalBox = el.querySelector(':scope > .modal') || el.querySelector(':scope > .command-palette');
    const target = modalBox || el;
    if (target.classList.contains('closing')) return;  // уже закрывается
    target.classList.add('modal-animating');
    target.style.willChange = 'transform, opacity';
    target.addEventListener('transitionend', () => {
      target.classList.remove('modal-animating');
      target.style.willChange = '';
    }, { once: true });
    target.classList.add('closing');
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      target.classList.remove('closing');
      try { el.close(); } catch (e) {}
    };
    target.addEventListener('animationend', finish, { once: true });
    setTimeout(finish, 250);  // fallback если animationend не выстрелит
    return;
  }
  const i = MODAL_STACK.indexOf(id);
  if (i >= 0) MODAL_STACK.splice(i, 1);
  el.classList.remove('open');
  el.removeAttribute('open');
}

export function isModalOpen(id) { return MODAL_STACK.includes(id); }


/* ===== Dialog ===== */
let _dialogResolver = null;

export function _openDialog({ title, text, showInput, defaultValue, hint, okText, cancelText, danger, hideCancel }) {
  return new Promise((resolve) => {
    _dialogResolver = resolve;
    document.getElementById('dialogTitle').textContent = title || '';
    const textEl = document.getElementById('dialogText');
    if (text) { textEl.textContent = text; textEl.style.display = ''; }
    else { textEl.textContent = ''; textEl.style.display = 'none'; }
    const inputWrap = document.getElementById('dialogInputWrap');
    const input = document.getElementById('dialogInput');
    const hintEl = document.getElementById('dialogHint');

    const okBtn = document.getElementById('dialogOk');
    const cancelBtn = document.getElementById('dialogCancel');

    if (showInput) {
      inputWrap.style.display = 'block';
      input.value = defaultValue || '';
      hintEl.textContent = hint || '';
      input.setAttribute('data-autofocus', '');
      okBtn.removeAttribute('data-autofocus');
    } else {
      inputWrap.style.display = 'none';
      input.value = '';
      hintEl.textContent = '';
      input.removeAttribute('data-autofocus');
      okBtn.setAttribute('data-autofocus', '');
    }

    okBtn.textContent = okText || window.t('dialog.okText');
    okBtn.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
    okBtn.onclick = () => _closeDialog(showInput ? input.value : true);

    const hide = hideCancel === true;
    cancelBtn.style.display = hide ? 'none' : '';
    cancelBtn.textContent = cancelText || window.t('dialog.cancelText');
    cancelBtn.onclick = () => _closeDialog(null);

    input.onkeydown = (e) => {
      if (showInput && e.key === 'Enter') { e.preventDefault(); _closeDialog(input.value); }
    };
    openModal('dialogModal');
    if (showInput) setTimeout(() => { try { input.focus(); input.select(); } catch (e) {} }, 80);
  });
}

export function _closeDialog(value) {
  const r = _dialogResolver;
  _dialogResolver = null;
  closeModal('dialogModal');
  if (r) r(value);
}

// Ensure `#dialogModal` resolves its Promise on native close (ESC / backdrop).
if (typeof document !== 'undefined') {
  const _installDialogResolver = () => {
    const dl = document.getElementById('dialogModal');
    if (!dl || dl.__resolverCloseInstalled) return;
    dl.__resolverCloseInstalled = true;
    dl.addEventListener('close', () => {
      if (_dialogResolver) {
        const r = _dialogResolver;
        _dialogResolver = null;
        r(null);
      }
    });
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _installDialogResolver);
  } else {
    _installDialogResolver();
  }
}


export function showAlert(title, text) {
  return _openDialog({ title, text, showInput: false, okText: window.t('dialog.okText'), hideCancel: true });
}

export function showConfirm(title, text, opts = {}) {
  return _openDialog({
    title, text, showInput: false,
    okText: opts.okText || window.t('dialog.okText'),
    cancelText: window.t('dialog.cancelText'),
    danger: !!opts.danger,
  }).then(v => v === true);
}

export function showPrompt(title, opts = {}) {
  return _openDialog({
    title,
    text: opts.text || '',
    showInput: true,
    defaultValue: opts.defaultValue || '',
    hint: opts.hint || '',
    okText: opts.okText || window.t('dialog.okText'),
    cancelText: window.t('dialog.cancelText'),
  });
}

export function _openCustomDialog({ title, bodyText, selectorEl, okText }) {
  return new Promise((resolve) => {
    _dialogResolver = (v) => resolve(v);
    document.getElementById('dialogTitle').textContent = title || '';
    const textEl = document.getElementById('dialogText');
    textEl.textContent = '';
    textEl.style.display = '';
    textEl.className = '';
    textEl.innerHTML = '';
    if (bodyText) {
      const p = document.createElement('div');
      p.style.marginBottom = '10px';
      p.textContent = bodyText;
      textEl.appendChild(p);
    }
    if (selectorEl) textEl.appendChild(selectorEl);
    document.getElementById('dialogInputWrap').style.display = 'none';
    const okBtn = document.getElementById('dialogOk');
    okBtn.textContent = okText || 'OK';
    okBtn.className = 'btn btn-primary';
    okBtn.onclick = () => _closeDialog(true);
    const cancelBtn = document.getElementById('dialogCancel');
    cancelBtn.style.display = '';
    cancelBtn.textContent = 'Отмена';
    cancelBtn.onclick = () => _closeDialog(null);
    openModal('dialogModal');
  });
}

/* ===== Tooltip ===== */
let _tooltipEl = null, _tooltipTimer = null, _tooltipCurrentEl = null, _tooltipConverting = false;
// _lastMouseX/_lastMouseY удалены.

function _getTooltipEl() {
  if (_tooltipEl) return _tooltipEl;
  _tooltipEl = document.createElement('div');
  _tooltipEl.id = 'global-tooltip';
  _tooltipEl.setAttribute('role', 'tooltip');
  _tooltipEl.setAttribute('aria-hidden', 'true');
  document.body.appendChild(_tooltipEl);
  return _tooltipEl;
}

function convertTitleToTooltip(el) {
  if (!el || el.nodeType !== 1) return;
  const t = el.getAttribute('title');
  if (!t || _tooltipConverting) return;
  _tooltipConverting = true;
  el.removeAttribute('title');
  if (!el.hasAttribute('aria-label')) el.setAttribute('aria-label', t);
  el.setAttribute('data-tooltip', t);
  _tooltipConverting = false;
}

export function convertTitlesIn(root) {
  if (!root) return;
  if (root.nodeType === 1) convertTitleToTooltip(root);
  if (root.querySelectorAll) root.querySelectorAll('[title]').forEach(convertTitleToTooltip);
}

function showTooltip(el) {
  const text = el.getAttribute('data-tooltip');
  if (!text) return;
  const t = _getTooltipEl();
  if (!t.id) t.id = 'global-tooltip';
  if (!el.hasAttribute('aria-describedby')) {
    el.setAttribute('aria-describedby', t.id);
  }
  t.textContent = text;
  t.classList.add('visible');
  t.removeAttribute('aria-hidden');
  const r = el.getBoundingClientRect();
  t.style.left = '0px'; t.style.top = '0px';
  const tr = t.getBoundingClientRect();
  let left = r.left + r.width / 2 - tr.width / 2;
  let top = r.bottom + 8;
  if (top + tr.height > window.innerHeight - 8) {
    top = r.top - tr.height - 8;
    if (top < 8) top = 8;
  }
  if (left < 8) left = 8;
  if (left + tr.width > window.innerWidth - 8) left = window.innerWidth - tr.width - 8;
  t.style.left = left + 'px';
  t.style.top = top + 'px';
}

export function hideTooltip() {
  if (_tooltipTimer) { clearTimeout(_tooltipTimer); _tooltipTimer = null; }
  _tooltipCurrentEl = null;
  if (_tooltipEl) {
    _tooltipEl.classList.remove('visible');
    _tooltipEl.setAttribute('aria-hidden', 'true');
  }
}

export function _installTooltipObserver() {
  _getTooltipEl();
  // MutationObserver на document.body слишком дорого
  // (fires on every DOM change page-wide). Вешаем на #imageList —
  // именно там динамически создаются строки. Статические тултипы
  // приходят с data-tooltip из HTML; модули, которым нужна конвертация
  // динамически добавленных title= вне #imageList, вызывают
  // convertTitlesIn(el) явно.
  const _target = document.getElementById('imageList') || document.body;
  if (_target.__pdbTooltipObserver) return;
  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'childList') m.addedNodes.forEach(node => convertTitlesIn(node));
      else if (m.type === 'attributes' && m.attributeName === 'title') convertTitleToTooltip(m.target);
    }
  });
  obs.observe(_target, { childList: true, subtree: true, attributes: true, attributeFilter: ['title'] });
  _target.__pdbTooltipObserver = obs;
}

document.addEventListener('mouseover', (e) => {
  const el = e.target.closest && e.target.closest('[data-tooltip]');
  if (!el || _tooltipCurrentEl === el) return;
  hideTooltip();
  _tooltipCurrentEl = el;
  _tooltipTimer = setTimeout(() => {
    if (_tooltipCurrentEl === el) showTooltip(el);
  }, 400);
}, true);
document.addEventListener('mouseout', (e) => {
  const el = e.target.closest && e.target.closest('[data-tooltip]');
  if (!el) return;
  const to = e.relatedTarget;
  if (to && el.contains(to)) return;
  if (_tooltipCurrentEl === el) hideTooltip();
}, true);
document.addEventListener('mousedown', () => hideTooltip(), true);
document.addEventListener('focusin', (e) => {
  if (_skipFocusReturnOnce) {
    _skipFocusReturnOnce = false;
    return;
  }
  const el = e.target && e.target.closest && e.target.closest('[data-tooltip]');
  if (!el || _tooltipCurrentEl === el) return;
  hideTooltip();
  _tooltipCurrentEl = el;
  _tooltipTimer = setTimeout(() => {
    if (_tooltipCurrentEl === el) showTooltip(el);
  }, 100);
}, true);
window.addEventListener('scroll', hideTooltip, true);
window.addEventListener('resize', hideTooltip);
// pointermove listener удалён.

