// @ts-check
// V11.6.0: Extracted UI Components (Modals, Dialogs, Tooltips)
import { haptic } from './utils.js';

/* ===== Modal stack ===== */
export const MODAL_STACK = [];
let _skipFocusReturnOnce = false;

export function openModal(id) {
  const el = document.getElementById(id);
  if (!el) {
    console.error(`[openModal] Element #${id} not found in DOM. DOM corrupted?`);
    return;
  }
  // [STAGE3] Force cleanup of any stuck state
  if (el.classList.contains('closing')) {
    el.classList.remove('closing');
  }
  if (el.classList.contains('open') && !MODAL_STACK.includes(id)) {
    // Stuck: .open висит без MODAL_STACK — принудительно лечим
    console.warn(`[openModal] #${id} stuck in .open without MODAL_STACK — resetting`);
    el.classList.remove('open');
  }
  if (el.classList.contains('open')) return;
  if (el.__focusTimer) { clearTimeout(el.__focusTimer); el.__focusTimer = null; }
  el.__returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  el.classList.remove('closing');
  el.classList.add('open');
  MODAL_STACK.push(id);
  el.style.zIndex = String(1000 + MODAL_STACK.length * 10);
  trapFocus(el);
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
      if (!el.classList.contains('open')) return;
      try { target.focus({ preventScroll: true }); if (target.select) target.select(); }
      catch (e) {}
    }, 80);
  }
}

export function closeModal(id) {
  const i = MODAL_STACK.indexOf(id);
  if (i >= 0) MODAL_STACK.splice(i, 1);
  
  const el = document.getElementById(id);
  if (!el) return;
  
  if (document.activeElement && el.contains(document.activeElement)) {
    document.activeElement.blur();
  }
  
  if (el.classList.contains('closing')) return;
  el.classList.add('closing');
  el.classList.remove('open');
  
  const returnFocus = el.__returnFocus;
  el.__returnFocus = null;
  
  if (_skipFocusReturnOnce) {
    _skipFocusReturnOnce = false;
    if (returnFocus && typeof returnFocus.blur === 'function') {
      try { returnFocus.blur(); } catch (e) {}
    }
  } else {
    setTimeout(() => {
      if (returnFocus && document.contains(returnFocus) && !returnFocus.closest('.modal-backdrop:not(.open)')) {
        try { returnFocus.focus({ preventScroll: true }); } catch (e) {}
      }
    }, 60);
  }
  setTimeout(() => el.classList.remove('closing'), 220);
}

export function isModalOpen(id) { return MODAL_STACK.includes(id); }

export function trapFocus(modalEl) {
  if (modalEl.__focusTrapped) return;
  modalEl.__focusTrapped = true;
  modalEl.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const focusables = Array.from(
      modalEl.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), ' +
        'select:not([disabled]), textarea:not([disabled]), ' +
        '[tabindex]:not([tabindex="-1"])'
      )
    ).filter(el => el.offsetParent !== null || el === document.activeElement);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
}

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
  closeModal('dialogModal');
  const r = _dialogResolver; _dialogResolver = null;
  if (r) r(value);
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
let _lastMouseX = 0, _lastMouseY = 0;

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
  convertTitlesIn(document.body);
  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'childList') m.addedNodes.forEach(node => convertTitlesIn(node));
      else if (m.type === 'attributes' && m.attributeName === 'title') convertTitleToTooltip(m.target);
    }
  });
  obs.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['title'] });
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
document.addEventListener('focusin', () => hideTooltip(), true);
window.addEventListener('scroll', hideTooltip, true);
window.addEventListener('resize', hideTooltip);
document.addEventListener('pointermove', (e) => {
  _lastMouseX = e.clientX; _lastMouseY = e.clientY;
}, { passive: true });
