/* =========================================================
   Dataset Builder — JavaScript
   V7.8.0 — все наработки V7.0.0 → V7.8.0
   ========================================================= */

let APP_VERSION = "V8.8.6";

/* ===== Reduced Motion ===== */
let _reducedMotionQuery = null;
function prefersReducedMotion() {
  if (!_reducedMotionQuery) {
    try { _reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)'); }
    catch (e) { _reducedMotionQuery = { matches: false }; }
  }
  return _reducedMotionQuery.matches;
}
try {
  // V7.8.3: no-op listener удалён. MediaQueryList — live-объект,
  // его .matches всегда актуален, переприсваивать не нужно.
} catch (e) {}
/* ===== Modal stack ===== */
const MODAL_STACK = [];

let _skipFocusReturnOnce = false;
function openModal(id) {
  const el = document.getElementById(id);
  if (!el || el.classList.contains('open')) return;
  el.__returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  el.classList.remove('closing');
  el.classList.add('open');
  MODAL_STACK.push(id);
  el.style.zIndex = String(1000 + MODAL_STACK.length * 10);
  trapFocus(el);
  // V8.2.3: visible-only — пропускаем hidden-элементы,
  // иначе фокус не переходит и Enter не работает на confirm-модалках.
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
    setTimeout(() => {
      try { target.focus({ preventScroll: true }); if (target.select) target.select(); }
      catch (e) {}
    }, 80);
  }
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (!el || el.classList.contains('closing')) return;
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
      if (returnFocus && document.contains(returnFocus)
          && !returnFocus.closest('.modal-backdrop:not(.open)')) {
        try { returnFocus.focus({ preventScroll: true }); } catch (e) {}
      }
    }, 60);
  }

  setTimeout(() => el.classList.remove('closing'), 220);
  const i = MODAL_STACK.indexOf(id);
  if (i >= 0) MODAL_STACK.splice(i, 1);
}
function isModalOpen(id) { return MODAL_STACK.includes(id); }

function trapFocus(modalEl) {
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

/* ===== Popover helpers ===== */
function closeAllPopovers(exceptEl) {
  document.querySelectorAll('.sort-menu.open').forEach(m => {
    if (m !== exceptEl) {
      m.classList.remove('open');
      if (m.id === 'exportMenu') {
        const b = document.getElementById('exportBtn');
        if (b) b.setAttribute('aria-expanded', 'false');
      }
    }
  });
  document.querySelectorAll('.custom-select.open').forEach(w => {
    if (!exceptEl || !w.contains(exceptEl)) w.classList.remove('open');
  });
  document.querySelectorAll('.color-picker-menu.open').forEach(m => {
    if (m !== exceptEl) m.classList.remove('open');
  });
  document.querySelectorAll('.class-search.open').forEach(w => {
    if (!exceptEl || !w.contains(exceptEl)) {
      const api = w.__classSearchApi;
      if (api && api.close) api.close();
    }
  });
}

/* ===== Utils ===== */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;',
    '"': '&quot;', "'": '&#39;'
  }[c]));
}
function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if ([2, 3, 4].includes(m10) && ![12, 13, 14].includes(m100)) return few;
  return many;
}
function pluralImages(n) {
  if (typeof getLang === 'function' && getLang() === 'en') return n === 1 ? 'image' : 'images';
  return plural(n, 'изображение', 'изображения', 'изображений');
}
function pluralProjects(n) {
  if (typeof getLang === 'function' && getLang() === 'en') return n === 1 ? 'project' : 'projects';
  return plural(n, 'проект', 'проекта', 'проектов');
}
function pluralGroups(n) {
  if (typeof getLang === 'function' && getLang() === 'en') return n === 1 ? 'group' : 'groups';
  return plural(n, 'группа', 'группы', 'групп');
}

/* V7.8.4: единая активация по Enter/Space.
   Используется во всех местах, где раньше был ручной listener. */
function onActivate(el, handler, opts = {}) {
  el.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    if (opts.stop) e.stopPropagation();
    handler(e);
  });
}
function getExt(f) { const i = f.lastIndexOf('.'); return i >= 0 ? f.slice(i + 1).toLowerCase() : ''; }
function getStem(f) { const i = f.lastIndexOf('.'); return i >= 0 ? f.slice(0, i) : f; }
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
function _fmtBytes(n) {
  if (!n || n < 1024) return (n || 0) + ' Б';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' КБ';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' МБ';
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' ГБ';
}
function animateNumber(el, newText) {
  if (!el || el.textContent === newText) return;
  el.style.transform = 'translateY(-4px)';
  el.style.opacity = '0.4';
  setTimeout(() => {
    el.textContent = newText;
    el.style.transform = 'translateY(0)';
    el.style.opacity = '1';
  }, 100);
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
function convertTitlesIn(root) {
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
function hideTooltip() {
  if (_tooltipTimer) { clearTimeout(_tooltipTimer); _tooltipTimer = null; }
  _tooltipCurrentEl = null;
  if (_tooltipEl) {
    _tooltipEl.classList.remove('visible');
    _tooltipEl.setAttribute('aria-hidden', 'true');
  }
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

function _installTooltipObserver() {
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

/* ===== Theme ===== */
function getThemeMode() { try { return localStorage.getItem('pdb_theme') || 'auto'; } catch (e) { return 'auto'; } }
function applyTheme() {
  const mode = getThemeMode();
  let eff = mode;
  if (mode === 'auto') eff = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', eff);
  document.documentElement.setAttribute('data-theme-mode', mode);
  updateThemeSegment();
}
function setThemeMode(mode) {
  if (!['auto', 'light', 'dark'].includes(mode)) mode = 'auto';
  try { localStorage.setItem('pdb_theme', mode); } catch (e) {}
  applyTheme(); haptic('selection');
}
function updateThemeSegment() {
  const seg = document.getElementById('themeSegment');
  if (!seg) return;
  const cur = getThemeMode();
  seg.querySelectorAll('button').forEach(b => {
    const isActive = b.dataset.mode === cur;
    b.classList.toggle('active', isActive);
    b.setAttribute('aria-checked', isActive ? 'true' : 'false');
    b.setAttribute('tabindex', isActive ? '0' : '-1');
  });
}
try {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (getThemeMode() === 'auto') applyTheme();
  });
} catch (e) {}

function getHideHints() { try { return localStorage.getItem('pdb_hide_hints') === '1'; } catch (e) { return false; } }
function setHideHints(v) {
  try { localStorage.setItem('pdb_hide_hints', v ? '1' : '0'); } catch (e) {}
  document.documentElement.setAttribute('data-hide-hints', v ? '1' : '0');
  const cb = document.getElementById('hideHintsToggle');
  if (cb) cb.checked = v;
}

/* ===== Focus mode ===== */
function getFocusMode() { try { return localStorage.getItem('pdb_focus_mode') === '1'; } catch (e) { return false; } }
function setFocusMode(v) {
  try { localStorage.setItem('pdb_focus_mode', v ? '1' : '0'); } catch (e) {}
  applyFocusMode();
  haptic('selection');
}
function toggleFocusMode() { setFocusMode(!getFocusMode()); }
function applyFocusMode() {
  const on = getFocusMode();
  document.documentElement.setAttribute('data-focus-mode', on ? '1' : '0');
  const btn = document.getElementById('focusModeBtn');
  if (btn) {
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    const tt = on ? 'Выйти из focus-режима (⌘\\)' : 'Focus-режим (⌘\\)';
    btn.setAttribute('aria-label', tt);
    btn.dataset.tooltip = tt;
  }
}

/* ===== Haptics ===== */
function haptic(type = 'light') {
  if (!('vibrate' in navigator)) return;
  // V8.5.3: не вызываем vibrate до первого user-gesture,
  // иначе Chrome спамит [Intervention] warning в консоль.
  try {
    const ua = navigator.userActivation;
    if (ua && typeof ua.hasBeenActive === 'boolean' && !ua.hasBeenActive) {
      return;
    }
  } catch (e) {}
  const patterns = {
    light: [8], medium: [15], selection: [5],
    success: [10, 40, 12], error: [22, 60, 22, 60, 22], warning: [15, 40, 15],
  };
  try { navigator.vibrate(patterns[type] || patterns.light); } catch (e) {}
}

/* ===== V8.1.0: Browser Notifications ===== */
function _ensureNotificationPermission() {
  if (typeof Notification === 'undefined') return false;
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') return false;
  try { Notification.requestPermission().catch(() => {}); } catch (e) {}
  return false;
}

function _showTrainingNotification(title, body) {
  if (typeof Notification === 'undefined') return;
  if (Notification.permission !== 'granted') return;
  try {
    const n = new Notification(title, { body: body || '', tag: 'pdb-training' });
    setTimeout(() => { try { n.close(); } catch (e) {} }, 12000);
  } catch (e) { /* некоторые браузеры блокируют без HTTPS */ }
}

/* ===== Dialog ===== */
let _dialogResolver = null;

function _openDialog({ title, text, showInput, defaultValue, hint, okText, cancelText, danger, hideCancel }) {
  return new Promise((resolve) => {
    _dialogResolver = resolve;
    document.getElementById('dialogTitle').textContent = title || '';
    const textEl = document.getElementById('dialogText');
    if (text) { textEl.textContent = text; textEl.style.display = ''; }
    else { textEl.textContent = ''; textEl.style.display = 'none'; }
    const inputWrap = document.getElementById('dialogInputWrap');
    const input = document.getElementById('dialogInput');
    const hintEl = document.getElementById('dialogHint');
    if (showInput) {
      inputWrap.style.display = 'block';
      input.value = defaultValue || '';
      hintEl.textContent = hint || '';
      input.setAttribute('data-autofocus', '');    // V8.2.3
    } else {
      inputWrap.style.display = 'none';
      input.value = '';
      hintEl.textContent = '';
      input.removeAttribute('data-autofocus');      // V8.2.3
    }
    const okBtn = document.getElementById('dialogOk');
    okBtn.textContent = okText || 'OK';
    okBtn.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
    okBtn.onclick = () => _closeDialog(showInput ? input.value : true);
    const cancelBtn = document.getElementById('dialogCancel');
    const hide = hideCancel === true;
    cancelBtn.style.display = hide ? 'none' : '';
    cancelBtn.textContent = cancelText || 'Отмена';
    cancelBtn.onclick = () => _closeDialog(null);
    input.onkeydown = (e) => {
      if (showInput && e.key === 'Enter') { e.preventDefault(); _closeDialog(input.value); }
    };
    openModal('dialogModal');
    if (showInput) setTimeout(() => { try { input.focus(); input.select(); } catch (e) {} }, 80);
  });
}
function _closeDialog(value) {
  closeModal('dialogModal');
  const r = _dialogResolver; _dialogResolver = null;
  if (r) r(value);
}
function showAlert(title, text) {
  return _openDialog({ title, text, showInput: false, okText: t('dialog.okText'), hideCancel: true });
}
function showConfirm(title, text, opts = {}) {
  return _openDialog({
    title, text, showInput: false,
    okText: opts.okText || t('dialog.okText'),
    cancelText: t('dialog.cancelText'),
    danger: !!opts.danger,
  }).then(v => v === true);
}
function showPrompt(title, opts = {}) {
  return _openDialog({
    title,
    text: opts.text || '',
    showInput: true,
    defaultValue: opts.defaultValue || '',
    hint: opts.hint || '',
    okText: opts.okText || t('dialog.okText'),
    cancelText: t('dialog.cancelText'),
  });
}
function _openCustomDialog({ title, bodyText, selectorEl, okText }) {
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

/* ===== Custom Select ===== */
function upgradeSelect(selectEl) {
  if (!selectEl || selectEl.dataset.customized === '1') return;
  selectEl.dataset.customized = '1';

  const wrap = document.createElement('div');
  wrap.className = 'custom-select';
  if (selectEl.style.flex) wrap.style.flex = selectEl.style.flex;
  if (selectEl.style.width) wrap.style.width = selectEl.style.width;
  if (selectEl.style.minWidth) wrap.style.minWidth = selectEl.style.minWidth;
  if (selectEl.style.maxWidth) wrap.style.maxWidth = selectEl.style.maxWidth;

  selectEl.parentNode.insertBefore(wrap, selectEl);
  wrap.appendChild(selectEl);

  selectEl.setAttribute('aria-hidden', 'true');
  selectEl.setAttribute('tabindex', '-1');

  const menuId = 'custom-select-menu-' + Math.random().toString(36).slice(2, 9);
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'custom-select-trigger';
  trigger.setAttribute('role', 'combobox');
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.setAttribute('aria-expanded', 'false');
  trigger.setAttribute('aria-controls', menuId);
  trigger.setAttribute('aria-label', selectEl.getAttribute('aria-label') || 'Выбор');

  const triggerText = document.createElement('span');
  triggerText.className = 'custom-select-text';
  triggerText.id = menuId + '-value';
  trigger.appendChild(triggerText);

  const chev = document.createElement('span');
  chev.className = 'custom-select-chevron';
  chev.setAttribute('aria-hidden', 'true');
  chev.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
  trigger.appendChild(chev);
  wrap.appendChild(trigger);

  const menu = document.createElement('div');
  menu.className = 'custom-select-menu';
  menu.id = menuId;
  menu.setAttribute('role', 'listbox');
  menu.setAttribute('aria-labelledby', triggerText.id);
  menu.setAttribute('tabindex', '-1');

  let activeIdx = -1;

  function rebuildMenu() {
    menu.innerHTML = '';
    Array.from(selectEl.options).forEach((opt, idx) => {
      const item = document.createElement('div');
      item.className = 'custom-select-option';
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', opt.value === selectEl.value ? 'true' : 'false');
      item.setAttribute('aria-disabled', opt.disabled ? 'true' : 'false');
      item.dataset.value = opt.value;
      item.dataset.idx = idx;
      item.id = menuId + '-opt-' + idx;
      const check = document.createElement('span');
      check.className = 'custom-select-check';
      check.setAttribute('aria-hidden', 'true');
      check.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
      item.appendChild(check);
      const label = document.createElement('span');
      label.textContent = opt.textContent;
      item.appendChild(label);
      if (opt.value === selectEl.value) item.classList.add('selected');
      if (opt.disabled) item.classList.add('disabled');
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        if (opt.disabled) return;
        selectEl.value = opt.value;
        selectEl.dispatchEvent(new Event('change', { bubbles: true }));
        close(); haptic('selection'); trigger.focus();
      });
      menu.appendChild(item);
    });
  }
  function updateTriggerLabel() {
    const cur = Array.from(selectEl.options).find(o => o.value === selectEl.value);
    triggerText.textContent = cur ? cur.textContent : '';
    menu.querySelectorAll('.custom-select-option').forEach((el) => {
      const isSel = el.dataset.value === selectEl.value;
      el.classList.toggle('selected', isSel);
      el.setAttribute('aria-selected', isSel ? 'true' : 'false');
    });
  }
  function positionMenu() {
    const r = trigger.getBoundingClientRect();
    menu.style.width = 'max-content'; menu.style.maxWidth = 'none';
    const naturalWidth = menu.scrollWidth;
    const roomRight = window.innerWidth - r.left - 12;
    const roomLeft = r.left + r.width - 12;
    let w = Math.max(r.width, Math.min(naturalWidth, 360, Math.max(roomRight, roomLeft)));
    let left = r.left;
    if (left + w > window.innerWidth - 8) left = Math.max(8, r.left + r.width - w);
    menu.style.left = left + 'px';
    menu.style.width = w + 'px';
    menu.style.top = (r.bottom + 6) + 'px';
    const menuH = menu.scrollHeight;
    const spaceBelow = window.innerHeight - r.bottom - 12;
    if (menuH > spaceBelow && r.top > menuH + 12) menu.style.top = (r.top - menuH - 6) + 'px';
  }
  function open() {
    closeAllPopovers(wrap);
    if (menu.parentNode !== document.body) document.body.appendChild(menu);
    wrap.classList.add('open');
    menu.style.display = 'block';
    trigger.setAttribute('aria-expanded', 'true');
    positionMenu();
    const curIdx = Array.from(selectEl.options).findIndex(o => o.value === selectEl.value);
    activeIdx = curIdx >= 0 ? curIdx : 0;
    _updateActiveDescendant();
    haptic('selection');
  }
  function close() {
    wrap.classList.remove('open');
    menu.style.display = '';
    trigger.setAttribute('aria-expanded', 'false');
    trigger.removeAttribute('aria-activedescendant');
    activeIdx = -1;
  }
  function _updateActiveDescendant() {
    menu.querySelectorAll('.custom-select-option').forEach((el, i) => {
      el.classList.toggle('active', i === activeIdx);
    });
    const activeEl = menu.querySelectorAll('.custom-select-option')[activeIdx];
    if (activeEl) {
      trigger.setAttribute('aria-activedescendant', activeEl.id);
      activeEl.scrollIntoView({ block: 'nearest' });
    }
  }
  function _selectActive() {
    const opts = Array.from(selectEl.options);
    if (activeIdx < 0 || activeIdx >= opts.length) return;
    const opt = opts[activeIdx];
    if (opt.disabled) return;
    selectEl.value = opt.value;
    selectEl.dispatchEvent(new Event('change', { bubbles: true }));
    close(); haptic('selection'); trigger.focus();
  }
  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    if (wrap.classList.contains('open')) close(); else open();
  });
  trigger.addEventListener('keydown', (e) => {
    const isOpen = wrap.classList.contains('open');
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (!isOpen) { open(); return; }
      if (e.key === 'Enter' || e.key === ' ') { _selectActive(); return; }
      const dir = e.key === 'ArrowDown' ? 1 : -1;
      const opts = Array.from(selectEl.options);
      let n = activeIdx;
      for (let i = 0; i < opts.length; i++) {
        n = (n + dir + opts.length) % opts.length;
        if (!opts[n].disabled) break;
      }
      activeIdx = n; _updateActiveDescendant();
    } else if (e.key === 'Escape' && isOpen) {
      e.preventDefault(); close(); trigger.focus();
    } else if (e.key === 'Home' && isOpen) {
      e.preventDefault(); activeIdx = 0; _updateActiveDescendant();
    } else if (e.key === 'End' && isOpen) {
      e.preventDefault(); activeIdx = selectEl.options.length - 1; _updateActiveDescendant();
    } else if (e.key === 'Tab' && isOpen) {
      close();
    }
  });
  document.addEventListener('click', (e) => {
    if (!wrap.contains(e.target) && !menu.contains(e.target)) close();
  });
  window.addEventListener('resize', () => { if (wrap.classList.contains('open')) positionMenu(); });
  window.addEventListener('scroll', () => { if (wrap.classList.contains('open')) positionMenu(); }, true);
  selectEl.addEventListener('change', updateTriggerLabel);
  const mo = new MutationObserver(() => { rebuildMenu(); updateTriggerLabel(); });
  mo.observe(selectEl, { childList: true, subtree: true, characterData: true });
  rebuildMenu();
  updateTriggerLabel();
}
function initCustomSelects() { document.querySelectorAll('select').forEach(upgradeSelect); }

/* ===== Color Picker ===== */
const COLOR_PRESETS = [
  '#0071e3', '#0a84ff', '#34c759', '#30d158',
  '#ff9500', '#ff9f0a', '#ff3b30', '#ff453a',
  '#a55eea', '#af52de', '#5ac8fa', '#64d2ff',
  '#ff2d55', '#ff6482', '#8e8e93', '#1d1d1f',
];

function upgradeColorPicker(inputEl) {
  if (!inputEl || inputEl.dataset.colorCustomized === '1') return;
  inputEl.dataset.colorCustomized = '1';
  inputEl.style.display = 'none';

  const wrap = document.createElement('div');
  wrap.className = 'color-picker';
  inputEl.parentNode.insertBefore(wrap, inputEl);
  wrap.appendChild(inputEl);

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'color-picker-trigger';
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.setAttribute('aria-expanded', 'false');
  trigger.setAttribute('aria-label', 'Выбрать цвет');

  const swatch = document.createElement('span');
  swatch.className = 'color-picker-swatch';
  swatch.style.background = inputEl.value || '#0071e3';
  trigger.appendChild(swatch);
  wrap.appendChild(trigger);

  const menu = document.createElement('div');
  menu.className = 'color-picker-menu';
  menu.setAttribute('role', 'dialog');
  menu.setAttribute('aria-label', 'Выбор цвета');

  const presetsGrid = document.createElement('div');
  presetsGrid.className = 'color-picker-presets';
  COLOR_PRESETS.forEach(c => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'color-picker-preset';
    b.style.background = c;
    b.dataset.color = c;
    b.setAttribute('aria-label', `Цвет ${c}`);
    b.onclick = (e) => { e.stopPropagation(); _setColor(c); _close(); };
    presetsGrid.appendChild(b);
  });
  menu.appendChild(presetsGrid);

  const nativeRow = document.createElement('div');
  nativeRow.className = 'color-picker-native';
  const nativeInput = document.createElement('input');
  nativeInput.type = 'color';
  nativeInput.value = inputEl.value || '#0071e3';
  nativeInput.setAttribute('aria-label', 'Точный цвет');
  nativeInput.oninput = (e) => { e.stopPropagation(); _setColor(e.target.value); };
  nativeInput.onclick = (e) => e.stopPropagation();
  nativeRow.appendChild(nativeInput);

  const hexInput = document.createElement('input');
  hexInput.type = 'text';
  hexInput.className = 'color-picker-hex';
  hexInput.value = (inputEl.value || '#0071e3').toLowerCase();
  hexInput.maxLength = 7;
  hexInput.spellcheck = false;
  hexInput.setAttribute('aria-label', 'HEX-код цвета');
  hexInput.oninput = (e) => {
    let v = e.target.value.trim();
    if (!v.startsWith('#')) v = '#' + v;
    if (/^#[0-9a-fA-F]{6}$/.test(v)) _setColor(v.toLowerCase());
  };
  hexInput.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); _close(); }
    if (e.key === 'Escape') { e.preventDefault(); _close(); }
  };
  hexInput.onclick = (e) => e.stopPropagation();
  nativeRow.appendChild(hexInput);
  menu.appendChild(nativeRow);
  wrap.appendChild(menu);

  function _setColor(c) {
    inputEl.value = c;
    swatch.style.background = c;
    nativeInput.value = c;
    hexInput.value = c.toLowerCase();
    menu.querySelectorAll('.color-picker-preset').forEach(b => {
      b.classList.toggle('selected', b.dataset.color.toLowerCase() === c.toLowerCase());
    });
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    inputEl.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function _open() {
    closeAllPopovers(wrap);
    document.querySelectorAll('.sort-menu.open').forEach(m => m.classList.remove('open'));
    menu.classList.add('open');
    trigger.setAttribute('aria-expanded', 'true');
    menu.querySelectorAll('.color-picker-preset').forEach(b => {
      b.classList.toggle('selected',
        b.dataset.color.toLowerCase() === (inputEl.value || '').toLowerCase());
    });
    hexInput.value = (inputEl.value || '#0071e3').toLowerCase();
    setTimeout(() => { try { hexInput.focus(); hexInput.select(); } catch (e) {} }, 60);
  }
  function _close() {
    menu.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
  }
  trigger.onclick = (e) => {
    e.stopPropagation();
    if (menu.classList.contains('open')) _close(); else _open();
  };
  document.addEventListener('click', (e) => {
    if (wrap.contains(e.target)) return;
    if (menu.contains(e.target)) return;
    if (menu.classList.contains('open')) _close();
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && menu.classList.contains('open')) {
      e.preventDefault(); e.stopPropagation();
      _close();
      trigger.focus();
    }
  }, true);
  inputEl.addEventListener('change', () => {
    const v = inputEl.value || '#0071e3';
    swatch.style.background = v;
  });
}
function initColorPickers() {
  document.querySelectorAll('input[type="color"]').forEach(upgradeColorPicker);
}

/* ===================================================================
   Object class search
   =================================================================== */
let objectClassesCache = {
  source: 'empty', classes: [], activeModel: null, loaded: false, loading: null,
};

async function loadObjectClasses(force = false) {
  if (objectClassesCache.loaded && !force) return objectClassesCache;
  if (objectClassesCache.loading) return objectClassesCache.loading;
  objectClassesCache.loading = (async () => {
    try {
      const r = await api('/api/object_classes');
      objectClassesCache.source = r.source || 'empty';
      objectClassesCache.classes = Array.isArray(r.classes) ? r.classes : [];
      objectClassesCache.activeModel = r.active_model || null;
    } catch (e) {
      objectClassesCache.source = 'empty';
      objectClassesCache.classes = [];
      objectClassesCache.activeModel = null;
    } finally {
      objectClassesCache.loaded = true;
      objectClassesCache.loading = null;
    }
    return objectClassesCache;
  })();
  return objectClassesCache.loading;
}
function invalidateObjectClasses() {
  objectClassesCache.loaded = false;
  objectClassesCache.loading = null;
}

function createClassSearch(hostEl, opts = {}) {
  hostEl.innerHTML = '';
  hostEl.classList.add('class-search');

  const wrap = document.createElement('div');
  wrap.className = 'class-search-input-wrap';

  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 24 24');
  icon.setAttribute('aria-hidden', 'true');
  icon.classList.add('class-search-icon');
  icon.innerHTML = '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/>';
  wrap.appendChild(icon);

  const inputEl = document.createElement('input');
  inputEl.type = 'text';
  inputEl.className = 'class-search-input';
  inputEl.placeholder = opts.placeholder || 'Поиск класса…';
  inputEl.autocomplete = 'off';
  inputEl.spellcheck = false;
  inputEl.setAttribute('role', 'combobox');
  inputEl.setAttribute('aria-expanded', 'false');
  inputEl.setAttribute('aria-autocomplete', 'list');
  wrap.appendChild(inputEl);

  const clearBtn = document.createElement('button');
  clearBtn.type = 'button';
  clearBtn.className = 'class-search-clear';
  clearBtn.setAttribute('aria-label', 'Очистить');
  clearBtn.tabIndex = -1;
  clearBtn.innerHTML = '×';
  wrap.appendChild(clearBtn);
  hostEl.appendChild(wrap);

  const menuEl = document.createElement('div');
  menuEl.className = 'class-search-menu';
  menuEl.setAttribute('role', 'listbox');
  menuEl.hidden = true;
  hostEl.appendChild(menuEl);

  let state = {
    value: opts.initialValue || '',
    source: opts.initialSource || 'list',
    disabled: !!opts.disabled,
    isOpen: false, activeIdx: -1,
    filtered: [], hasCustom: false, query: '',
  };

  let _wasFocused = false;

  function _applyDisabled() {
    inputEl.disabled = state.disabled;
    clearBtn.disabled = state.disabled;
    hostEl.classList.toggle('class-search-disabled', state.disabled);
  }
  function _setInputValue() {
    if (state.value) {
      inputEl.value = state.value;
      inputEl.dataset.source = state.source;
      hostEl.classList.toggle('class-search-custom', state.source === 'custom');
    } else {
      inputEl.value = '';
      inputEl.dataset.source = '';
      hostEl.classList.remove('class-search-custom');
    }
    clearBtn.style.display = state.value && !state.disabled ? 'block' : 'none';
  }
  function _filterClasses(query) {
    const q = (query || '').trim().toLowerCase();
    const cls = objectClassesCache.classes || [];
    const out = [];
    if (!q) {
      const limit = Math.min(cls.length, 200);
      for (let i = 0; i < limit; i++) out.push({ value: cls[i], source: 'list' });
      return out;
    }
    for (let i = 0; i < cls.length; i++) {
      if (cls[i].toLowerCase().includes(q)) {
        out.push({ value: cls[i], source: 'list' });
        if (out.length >= 200) break;
      }
    }
    return out;
  }
  function _hasExactMatch(query) {
    if (!query) return false;
    const q = query.toLowerCase();
    return (objectClassesCache.classes || []).some(c => c.toLowerCase() === q);
  }
  function _render() {
    menuEl.innerHTML = '';
    const cls = objectClassesCache.classes || [];
    const q = state.query;

    if (!objectClassesCache.loaded) {
      const e = document.createElement('div');
      e.className = 'class-search-empty';
      e.textContent = 'Загрузка классов…';
      menuEl.appendChild(e);
      state.filtered = []; state.hasCustom = false;
      return;
    }
    if (objectClassesCache.source === 'empty') {
      const e = document.createElement('div');
      e.className = 'class-search-empty';
      e.textContent = 'Классы недоступны — модель ещё не загружена. Введи название вручную и нажми «Использовать как есть».';
      menuEl.appendChild(e);
    }
    const filtered = _filterClasses(q);
    state.filtered = filtered;
    if (filtered.length) {
      filtered.forEach((item, idx) => {
        const div = document.createElement('div');
        div.className = 'class-search-option';
        div.setAttribute('role', 'option');
        div.dataset.idx = String(idx);
        div.dataset.value = item.value;
        div.dataset.source = 'list';
        div.textContent = item.value;
        if (item.value === state.value && state.source === 'list') {
          div.classList.add('selected');
          div.setAttribute('aria-selected', 'true');
        } else {
          div.setAttribute('aria-selected', 'false');
        }
        menuEl.appendChild(div);
      });
    } else if (q && objectClassesCache.source !== 'empty') {
      const e = document.createElement('div');
      e.className = 'class-search-empty';
      e.textContent = 'Ничего не найдено';
      menuEl.appendChild(e);
    } else if (!q && objectClassesCache.source !== 'empty' && cls.length === 0) {
      const e = document.createElement('div');
      e.className = 'class-search-empty';
      e.textContent = 'Список пуст';
      menuEl.appendChild(e);
    }
    if (q) {
      const custom = document.createElement('div');
      custom.className = 'class-search-custom';
      custom.setAttribute('role', 'option');
      custom.dataset.source = 'custom';
      custom.dataset.value = q;
      custom.innerHTML = `<span class="class-search-custom-plus" aria-hidden="true">⊕</span>` +
        `<span>Использовать как есть: «${escapeHtml(q)}»</span>`;
      custom.dataset.idx = String(filtered.length);
      menuEl.appendChild(custom);
      state.hasCustom = true;
    } else {
      state.hasCustom = false;
    }
    if (objectClassesCache.source !== 'empty' && cls.length) {
      const counter = document.createElement('div');
      counter.className = 'class-search-counter';
      counter.textContent = q
        ? `Показано ${filtered.length} из ${cls.length}`
        : `Всего классов: ${cls.length}`;
      menuEl.appendChild(counter);
    }
    _setActive(Math.max(0, Math.min(state.activeIdx, filtered.length + (state.hasCustom ? 0 : -1))));
  }
  function _setActive(idx) {
    const options = menuEl.querySelectorAll('.class-search-option, .class-search-custom');
    if (!options.length) { state.activeIdx = -1; return; }
    if (idx < 0) idx = 0;
    if (idx >= options.length) idx = options.length - 1;
    state.activeIdx = idx;
    options.forEach((el, i) => el.classList.toggle('active', i === idx));
    try { options[idx].scrollIntoView({ block: 'nearest' }); } catch (e) {}
  }
  function _moveActive(delta) {
    const options = menuEl.querySelectorAll('.class-search-option, .class-search-custom');
    if (!options.length) return;
    let n = state.activeIdx + delta;
    if (n < 0) n = options.length - 1;
    if (n >= options.length) n = 0;
    _setActive(n);
  }
  function _commitSelection(value, source) {
    state.value = value;
    state.source = source;
    _setInputValue();
    if (typeof opts.onChange === 'function') {
      try { opts.onChange({ value, source }); } catch (e) { console.error(e); }
    }
  }
  function _applyActive() {
    const options = menuEl.querySelectorAll('.class-search-option, .class-search-custom');
    const el = options[state.activeIdx];
    if (!el) {
      if (state.query) _commitSelection(state.query, _hasExactMatch(state.query) ? 'list' : 'custom');
      else return;
    } else {
      _commitSelection(el.dataset.value, el.dataset.source);
    }
    _close();
    inputEl.focus();
  }
  function _open() {
    if (state.disabled) return;
    if (state.isOpen) return;
    state.isOpen = true;
    hostEl.classList.add('open');
    if (menuEl.parentNode !== document.body) document.body.appendChild(menuEl);
    menuEl.hidden = false;
    inputEl.setAttribute('aria-expanded', 'true');
    state.query = '';
    state.activeIdx = 0;
    _render();
    _positionMenu();
  }
  function _close() {
    if (!state.isOpen) return;
    state.isOpen = false;
    hostEl.classList.remove('open');
    menuEl.hidden = true;
    inputEl.setAttribute('aria-expanded', 'false');
    state.activeIdx = -1;
  }
  function _positionMenu() {
    const r = inputEl.getBoundingClientRect();
    const MARGIN = 12, GAP = 6;
    const DESIRED_H = 320, MIN_H = 140;
    const spaceBelow = window.innerHeight - r.bottom - MARGIN;
    const spaceAbove = r.top - MARGIN;
    let top, maxH;
    if (spaceBelow >= MIN_H || spaceBelow >= spaceAbove) {
      top = r.bottom + GAP;
      maxH = Math.min(DESIRED_H, Math.max(MIN_H, spaceBelow));
    } else {
      maxH = Math.min(DESIRED_H, Math.max(MIN_H, spaceAbove));
      top = r.top - maxH - GAP;
    }
    menuEl.style.position = 'fixed';
    menuEl.style.left = r.left + 'px';
    menuEl.style.top = top + 'px';
    menuEl.style.width = r.width + 'px';
    menuEl.style.maxHeight = maxH + 'px';
    menuEl.style.zIndex = '6000';
  }

  inputEl.addEventListener('focus', () => {
    if (!_wasFocused) {
      _wasFocused = true;
      setTimeout(() => { try { inputEl.select(); } catch (e) {} }, 0);
    }
    _open();
  });
  inputEl.addEventListener('blur', () => {
    _wasFocused = false;
    setTimeout(() => {
      if (!hostEl.contains(document.activeElement) && !menuEl.contains(document.activeElement)) {
        _close();
        if (inputEl.value.trim() !== state.value) inputEl.value = state.value;
      }
    }, 120);
  });
  inputEl.addEventListener('input', (e) => {
    state.query = e.target.value;
    state.activeIdx = 0;
    if (!state.isOpen) _open();
    else _render();
  });
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!state.isOpen) _open(); else _moveActive(1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (!state.isOpen) _open(); else _moveActive(-1);
    } else if (e.key === 'Enter') {
      e.preventDefault(); e.stopPropagation();
      if (!state.isOpen) { _open(); return; }
      _applyActive();
    } else if (e.key === 'Escape') {
      if (state.isOpen) {
        e.preventDefault(); e.stopPropagation();
        _close();
        inputEl.value = state.value;
        inputEl.blur();
      }
    } else if (e.key === 'Tab') {
      if (state.isOpen) { _close(); inputEl.value = state.value; }
    } else if (e.key === 'Home' && state.isOpen) {
      e.preventDefault(); _setActive(0);
    } else if (e.key === 'End' && state.isOpen) {
      e.preventDefault();
      const n = menuEl.querySelectorAll('.class-search-option, .class-search-custom').length - 1;
      _setActive(Math.max(0, n));
    }
  });
  clearBtn.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); });
  clearBtn.addEventListener('click', (e) => {
    e.preventDefault(); e.stopPropagation();
    _commitSelection('', 'list');
    inputEl.focus();
    _open();
  });
  menuEl.addEventListener('mousedown', (e) => { e.preventDefault(); });
  menuEl.addEventListener('click', (e) => {
    const opt = e.target.closest('.class-search-option, .class-search-custom');
    if (!opt) return;
    e.stopPropagation();
    _commitSelection(opt.dataset.value, opt.dataset.source);
    _close();
    inputEl.focus();
  });
  menuEl.addEventListener('mousemove', (e) => {
    const opt = e.target.closest('.class-search-option, .class-search-custom');
    if (!opt) return;
    const options = Array.from(menuEl.querySelectorAll('.class-search-option, .class-search-custom'));
    const idx = options.indexOf(opt);
    if (idx >= 0 && idx !== state.activeIdx) _setActive(idx);
  });
  document.addEventListener('click', (e) => {
    if (!hostEl.contains(e.target) && !menuEl.contains(e.target)) {
      if (state.isOpen) {
        _close();
        if (inputEl.value.trim() !== state.value) inputEl.value = state.value;
      }
    }
  }, true);
  window.addEventListener('resize', () => { if (state.isOpen) _positionMenu(); });
  window.addEventListener('scroll', () => { if (state.isOpen) _positionMenu(); }, true);

  _applyDisabled();
  _setInputValue();

  const api = {
    getValue() { return { value: state.value, source: state.source }; },
    setValue(value, source) {
      const v = value || '';
      const s = source || (v && _hasExactMatch(v) ? 'list' : (v ? 'custom' : 'list'));
      _commitSelection(v, s);
    },
    setDisabled(flag) {
      state.disabled = !!flag;
      _applyDisabled();
      if (state.disabled) _close();
    },
    focus() { inputEl.focus(); },
    close() { _close(); },
    destroy() { hostEl.innerHTML = ''; hostEl.classList.remove('class-search', 'open'); },
  };
  hostEl.__classSearchApi = api;
  return api;
}

// V8.5.1: загрузка схемы один раз при старте.
async function loadKeypointSchema() {
  if (keypointSchema) return keypointSchema;
  try {
    keypointSchema = await api('/api/keypoint_schema');
    return keypointSchema;
  } catch (e) {
    console.warn('keypoint_schema load failed:', e);
    return null;
  }
}

function _schemaName(name) {
  if (!keypointSchema) return null;
  return keypointSchema.names.find(n => n.name === name) || null;
}

function _schemaOrder() {
  if (!keypointSchema) return [];
  return keypointSchema.names.map(n => n.name);
}

function _nextUnplacedName() {
  if (!keypointSchema || !Array.isArray(keypointSchema.names)) return null;
  if (!Array.isArray(keypoints)) return _schemaOrder()[0] || null;
  const placed = new Set(keypoints.map(p => p && p.name).filter(Boolean));
  for (const nm of _schemaOrder()) {
    if (!placed.has(nm)) return nm;
  }
  return null;
}

/* ===== api() ===== */
async function api(url, opts) {
  // V8.1.0: кастомный заголовок для CSRF-middleware.
  opts = opts || {};
  const method = (opts.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    const h = new Headers(opts.headers || {});
    h.set('X-Requested-With', 'DatasetBuilder');
    opts = { ...opts, headers: h };
  }
  const res = await fetch(url, opts);
  // V8.1.0: проброс AbortError наружу (см. loadImages).
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      const d = data && data.detail;
      if (typeof d === 'string') detail = d;
      // V9.0.0: структурированный detail — {key, params, fallback}.
      else if (d && typeof d === 'object' && !Array.isArray(d) && d.key) {
        const translated = (typeof t === 'function') ? t(d.key, d.params || {}) : null;
        detail = (translated && translated !== d.key) ? translated : (d.fallback || d.key);
      }
      else if (Array.isArray(d)) {
        detail = d.map(x => {
          if (typeof x === 'string') return x;
          if (x && typeof x === 'object' && x.key) {
            const tr = (typeof t === 'function') ? t(x.key, x.params || {}) : null;
            return (tr && tr !== x.key) ? tr : (x.fallback || x.key);
          }
          if (x && typeof x === 'object') return x.msg || x.message || JSON.stringify(x);
          return String(x);
        }).join('; ');
      } else if (d && typeof d === 'object') {
        detail = d.msg || d.message || JSON.stringify(d);
      }
    } catch (e) {}
    const err = new Error(detail || res.statusText);
    err.status = res.status; err.detail = detail;
    throw err;
  }
  return res.json();
}

/* ===== Status ===== */
function setStatus(msg, ttl = 3500, variant = null, opts = {}) {
  const el = document.getElementById('status');
  const bar = document.getElementById('statusBar');
  if (!el) return;
  const asHtml = !!opts.html;
  el.classList.remove('error', 'success');
  if (variant === 'error') el.classList.add('error');
  else if (variant === 'success') el.classList.add('success');
  el.classList.add('visible');
  if (bar) bar.classList.remove('is-empty');
  if (asHtml) el.innerHTML = msg; else el.textContent = msg;
  const priority = opts.priority || (variant === 'error' ? 'assertive' : 'polite');
  el.setAttribute('aria-live', priority);
  el.setAttribute('role', priority === 'assertive' ? 'alert' : 'status');
  clearTimeout(setStatus._t);
  if (ttl > 0) {
    setStatus._t = setTimeout(() => {
      el.classList.remove('visible', 'error', 'success');
      if (bar) bar.classList.add('is-empty');
    }, ttl);
  }
}
function clearStatus() {
  const el = document.getElementById('status');
  const bar = document.getElementById('statusBar');
  clearTimeout(setStatus._t); setStatus._t = null;
  el.classList.remove('visible', 'error', 'success');
  if (bar) bar.classList.add('is-empty');
}
function setError(msg, ttl = 6000) { setStatus(String(msg), ttl, 'error'); haptic('error'); }
function setSuccess(msg, ttl = 5000) { setStatus(String(msg), ttl, 'success'); }

/* ===== State ===== */
const ROW_H = (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) ? 44 : 36;
const SECTION_H = 28;
let _collapsedSections = { un: false, ann: false };
try {
  const saved = JSON.parse(localStorage.getItem('pdb_collapsed_sections') || '{}');
  if (saved && typeof saved === 'object') {
    _collapsedSections.un = !!saved.un;
    _collapsedSections.ann = !!saved.ann;
  }
} catch (e) {}
let _cachedProjectsList = [];

// V8.5.3: выбранный проект переживает перезагрузку.
let currentProjectId = (() => {
  try {
    const s = localStorage.getItem('pdb_currentProjectId');
    return s ? parseInt(s, 10) : null;
  } catch (e) { return null; }
})();
let currentProjectMeta = null;
let currentImageId = null;
let imagesList = [];
let allImages = [];
// V7.9.3: пагинация списка изображений
const IMAGES_PAGE_SIZE = 200;
let _imagesTotalInProject = 0;
let _imagesAnnotatedInProject = 0;
let _imagesHasMore = false;
let _imagesLoadingMore = false;
let boxes = [];
let selectedIndex = -1;
let multiSelected = new Set();
let dragState = null;
let isDirty = false;
let selectedForDelete = new Set();
let viewMode = 'main';
let exportFormat = 'yolo';
let _originalTrashTtlDays = null;

let sortMode = localStorage.getItem('pdb_sortMode') || 'name_asc';
const VALID_SORTS = ['name_asc', 'name_desc', 'type_asc', 'type_desc',
                     'conf_asc', 'conf_desc',
                     'date_asc', 'date_desc', 'size_asc', 'size_desc'];
if (!VALID_SORTS.includes(sortMode)) sortMode = 'name_asc';

let activeFilter = localStorage.getItem('pdb_filter') || 'none';
if (!['none', 'unannotated', 'lowconf', 'hard', 'duplicates'].includes(activeFilter)) activeFilter = 'none';

let searchQuery = '';
let activeTagIds = new Set();
let projectTags = [];
let projectTagsMap = new Map();
let currentImageTagIds = new Set();

let zoom = 1, panX = 0, panY = 0;
const ZOOM_MIN = 0.5, ZOOM_MAX = 8;

let spacePressed = false;
let isPanning = false;
let panStart = null;

let history = []; let historyIndex = -1;
const HISTORY_LIMIT = 50;

let sessionSeen = new Set();
let trainEventSource = null;
let batchEventSource = null;
let batchRunning = false;
let bootstrapEventSource = null;
let _logsRefreshTimer = null;
// V7.9.1: не мигать live-графиками при обучении
let _lastLiveEpochs = [];
let _lastRenderedLiveEpochs = null;

let _annotatedCount = 0;

// V8.1.0: короткая история удалений изображений (undo/redo списка).
const _listUndoStack = [];
const _listRedoStack = [];
const LIST_UNDO_LIMIT = 20;
function _pushListUndo(action) {
  _listUndoStack.push(action);
  if (_listUndoStack.length > LIST_UNDO_LIMIT) _listUndoStack.shift();
  _listRedoStack.length = 0;
}
async function undoListAction() {
  const a = _listUndoStack.pop();
  if (!a) { setStatus('Нечего отменять в списке'); return; }
  try {
    if (a.type === 'delete') {
      await api('/api/images/batch_restore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(a.ids),
      });
      _listRedoStack.push(a);
      await loadImages();
      setStatus('Восстановлено из списка');
    }
  } catch (e) { setError('Undo: ' + String(e.message).slice(0, 120)); }
}
async function redoListAction() {
  const a = _listRedoStack.pop();
  if (!a) return;
  try {
    if (a.type === 'delete') {
      await api('/api/images/batch_delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(a.ids),
      });
      _listUndoStack.push(a);
      await loadImages();
    }
  } catch (e) { setError('Redo: ' + String(e.message).slice(0, 120)); }
}
let _totalCount = 0;

let _tagsLastLoadedAt = 0;
const _tagSetCache = new WeakMap();

let _projectModalMode = null;
let _projectModalTarget = null;
let _projectClassSearch = null;
let _projectThumbSize = null;
let _projectDefaultZoom = null;
let _projectTtlOverride = null;
let _projectGlobalTtl = 30;

// V8.0.0: кэш результата валидатора — не пересчитываем при каждом открытии.
let _validateCache = null;   // { projectId, data }
function _invalidateValidateCache() { _validateCache = null; }

// V8.5.1: скелет.
let skeletonMode = false;
let keypointSchema = null;    // {names:[{name,label_ru,label_en,parent}], edges:[[p,n]]}
let keypoints = [];            // текущие точки для выделенной аннотации: [{name,x,y,visibility}]
let keypointDragIdx = -1;      // индекс точки при drag
let _kpNextHintEl = null;

let samMode = false;

// V8.8.6: rAF-батчинг рендера. Любой вызов scheduleRender() склеивается
// с другими в один рендер за кадр. Убирает тройные перерисовки при операциях.
let _renderQueued = false;
let _renderFns = new Set();

function scheduleRender(fn) {
  if (typeof fn === 'function') _renderFns.add(fn);
  if (_renderQueued) return;
  _renderQueued = true;
  requestAnimationFrame(() => {
    _renderQueued = false;
    const fns = _renderFns;
    _renderFns = new Set();
    for (const f of fns) {
      try { f(); } catch (e) { console.warn('render error:', e); }
    }
  });
}

// Обёртки: ставят рендер в очередь, если повторный вызов — не дублируется.
function scheduleRenderBoxes() { scheduleRender(() => renderBoxes()); }
function scheduleRenderSkeleton() { scheduleRender(() => {
  if (typeof renderSkeleton === 'function') renderSkeleton();
}); }
function scheduleRefreshMotionVector() {
  scheduleRender(() => {
    if (typeof _refreshMotionVector === 'function') _refreshMotionVector();
  });
}

// V8.8.6: debounce для motion vector — drag рамки не должен слать N запросов.
let _motionDebounceTimer = null;
function scheduleRefreshMotionVectorDebounced(ms) {
  if (_motionDebounceTimer) clearTimeout(_motionDebounceTimer);
  _motionDebounceTimer = setTimeout(() => {
    _motionDebounceTimer = null;
    scheduleRefreshMotionVector();
  }, ms || 150);
}

let samPreview = null;
let samPointInFlight = false;
let _activeLearningDismissed = false;

// V7.7.0: видео — только извлечение кадров
let _videoCaps = null;

// V7.5.1
let _migratePollTimer = null;

function _getTagSet(img) {
  let s = _tagSetCache.get(img);
  if (s) return s;
  s = new Set(img.tag_ids || []);
  _tagSetCache.set(img, s);
  return s;
}
function _invalidateTagSet(img) { _tagSetCache.delete(img); }

// V8.2.0: режим авторазметки — «add» (по умолчанию) или «replace».
function getAutolabelMode() {
  try {
    const v = localStorage.getItem('pdb_autolabel_mode');
    return v === 'replace' ? 'replace' : 'add';
  } catch (e) { return 'add'; }
}
function setAutolabelMode(mode) {
  if (!['add', 'replace'].includes(mode)) mode = 'add';
  try { localStorage.setItem('pdb_autolabel_mode', mode); } catch (e) {}
  const seg = document.getElementById('autolabelModeSegment');
  if (seg) {
    seg.querySelectorAll('button').forEach(b => {
      const active = b.dataset.mode === mode;
      b.classList.toggle('active', active);
      b.setAttribute('aria-checked', active ? 'true' : 'false');
      b.setAttribute('tabindex', active ? '0' : '-1');
    });
  }
  haptic('selection');
}


/* ===== Helpers: sections / debug ===== */
function _isImageItem(it) { return it && !it._kind; }
function _rowH(it) { return (it && it._kind === 'section') ? SECTION_H : ROW_H; }
function _rowKeyOf(it) {
  if (!it) return '';
  if (it._kind === 'project') return 'p' + it.id;
  if (it._kind === 'section') return 's' + it.sectionKey;
  return String(it.id);
}
let _rowTops = [];
// V8.1.0: при append-only (loadMoreImages) не пересчитываем всё.
let _rowTopsLastLen = 0;
function _recomputeRowTops() {
  const n = imagesList.length;
  if (n === 0) { _rowTops = []; _rowTopsLastLen = 0; return 0; }
  // Быстрый путь: список только вырос (пагинация) — досчитываем хвост.
  if (n > _rowTopsLastLen && _rowTopsLastLen > 0) {
    _rowTops.length = _rowTopsLastLen;
    let y = _rowTops[_rowTopsLastLen - 1] + _rowH(imagesList[_rowTopsLastLen - 1]);
    for (let i = _rowTopsLastLen; i < n; i++) {
      _rowTops[i] = y;
      y += _rowH(imagesList[i]);
    }
    _rowTopsLastLen = n;
    return y;
  }
  // Полный пересчёт.
  _rowTops = new Array(n);
  let y = 0;
  for (let i = 0; i < n; i++) {
    _rowTops[i] = y;
    y += _rowH(imagesList[i]);
  }
  _rowTopsLastLen = n;
  return y;
}
function _findRowIndexAtY(y) {
  if (!_rowTops.length) return 0;
  let lo = 0, hi = _rowTops.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (_rowTops[mid] <= y) lo = mid; else hi = mid - 1;
  }
  return lo;
}
function _saveCollapsedSections() {
  try { localStorage.setItem('pdb_collapsed_sections', JSON.stringify(_collapsedSections)); } catch (e) {}
}
function toggleSection(key) {
  _collapsedSections[key] = !_collapsedSections[key];
  _saveCollapsedSections();
  applyFiltersAndRender();
  haptic('selection');
}
function _buildSectionList(sorted) {
  if (activeFilter !== 'none') return sorted;
  if (!sorted.length) return [];

  const un = sorted.filter(x => (x.annotation_count || 0) === 0);
  const ann = sorted.filter(x => (x.annotation_count || 0) > 0);
  const out = [];

  out.push({
    _kind: 'section',
    id: '__section_un__',
    sectionKey: 'un',
    title: un.length ? t('section.un.title') : t('section.un.allDone'),
    count: un.length,
    allDone: un.length === 0,
  });
  if (un.length && !_collapsedSections.un) out.push(...un);
  if (ann.length) {
    out.push({
      _kind: 'section',
      id: '__section_ann__',
      sectionKey: 'ann',
      title: t('section.ann.title'),
      count: ann.length,
    });
    if (!_collapsedSections.ann) out.push(...ann);
  }
  return out;
}

function _updateTitleProgress() {
  if (viewMode === 'trash') {
    document.title = `Корзина — Dataset Builder ${APP_VERSION}`;
    return;
  }
  if (!currentProjectId || _totalCount === 0) {
    document.title = `Dataset Builder ${APP_VERSION}`;
    return;
  }
  document.title = `${_annotatedCount}/${_totalCount} — Dataset Builder`;
}

/* ===== V7.8.0: debug-режим YOLO ===== */
function getDebugMode() {
  try { return localStorage.getItem('pdb_debug_mode') === '1'; } catch (e) { return false; }
}
function setDebugMode(v) {
  try { localStorage.setItem('pdb_debug_mode', v ? '1' : '0'); } catch (e) {}
  if (!v) _clearDebugBoxes();
  const cb = document.getElementById('debugModeToggle');
  if (cb) cb.checked = !!v;
  haptic('selection');
  setStatus(v ? 'Debug-режим включён: показываются все классы YOLO' : 'Debug-режим выключен', 3000);
}
function _clearDebugBoxes() {
  const layer = document.getElementById('debugBoxes');
  if (layer) layer.innerHTML = '';
}
function _renderDebugBoxes(detections) {
  const layer = document.getElementById('debugBoxes');
  if (!layer) return;
  layer.innerHTML = '';
  (detections || []).forEach(d => {
    const div = document.createElement('div');
    div.className = 'debug-box';
    div.style.left = (d.x * 640) + 'px';
    div.style.top = (d.y * 640) + 'px';
    div.style.width = (d.w * 640) + 'px';
    div.style.height = (d.h * 640) + 'px';
    if (d.y * 640 < 22) div.classList.add('label-below');
    const lbl = document.createElement('span');
    lbl.className = 'debug-box-label';
    const conf = d.confidence != null ? ' ' + d.confidence.toFixed(2) : '';
    lbl.textContent = (d.label || 'object') + conf;
    div.appendChild(lbl);
    layer.appendChild(div);
  });
}

/* ===== SSE bootstrap ===== */
function subscribeBootstrapEvents() {
  if (bootstrapEventSource) { try { bootstrapEventSource.close(); } catch (e) {} }
  const es = new EventSource('/api/models/bootstrap/events');
  bootstrapEventSource = es;
  es.onmessage = (ev) => {
    try {
      const s = JSON.parse(ev.data);
      renderBootstrapStatus(s);
      if (s.status !== 'downloading') {
        if (s.status === 'done') {
          invalidateObjectClasses();
          loadModelsIntoUI();
          setSuccess(s.message || t('toast.modelLoaded'));
        } else if (s.status === 'error') setError(s.message || 'Ошибка загрузки модели', 10000);
        setTimeout(() => { try { es.close(); } catch (e) {} bootstrapEventSource = null; }, 800);
      }
    } catch (e) {}
  };
  es.onerror = () => { try { es.close(); } catch (e) {} bootstrapEventSource = null; };
}
function renderBootstrapStatus(s, opts = {}) {
  const skipTerminal = !!opts.skipTerminal;
  if (s.status === 'downloading') {
    const pctTxt = (s.progress != null && s.progress > 0) ? ` ${s.progress.toFixed(1)}%` : '';
    setStatus(`<span class="status-spinner" aria-hidden="true"></span>${escapeHtml(s.message || 'Скачиваем модель…')}${pctTxt}`, 0, null, { html: true });
  }
  const el = document.getElementById('modelDownloadStatus');
  const btn = document.getElementById('downloadBtn');
  if (!el) return;
  if (renderBootstrapStatus._hideT) { clearTimeout(renderBootstrapStatus._hideT); renderBootstrapStatus._hideT = null; }
  if (s.status === 'downloading') {
    el.style.display = 'block';
    el.style.background = 'var(--accent-soft)';
    el.style.color = 'var(--accent)';
    el.innerHTML = `<span class="status-spinner" aria-hidden="true"></span>${escapeHtml(s.message || t('bootstrap.downloading'))}`;
    if (btn) { btn.disabled = true; btn.textContent = t('bootstrap.downloading'); }
  } else if (s.status === 'done') {
    if (skipTerminal) { el.style.display = 'none'; if (btn) { btn.disabled = false; btn.textContent = 'Скачать'; } }
    else {
      el.style.display = 'block';
      el.style.background = 'rgba(52,199,89,0.15)';
      el.style.color = 'var(--success)';
      el.textContent = t('bootstrap.done', { msg: s.message || t('toast.modelLoaded') });
      if (btn) { btn.disabled = false; btn.textContent = t('bootstrap.download'); }
      renderBootstrapStatus._hideT = setTimeout(() => { el.style.display = 'none'; renderBootstrapStatus._hideT = null; }, 5000);
    }
  } else if (s.status === 'error') {
    if (skipTerminal) { el.style.display = 'none'; if (btn) { btn.disabled = false; btn.textContent = 'Скачать'; } }
    else {
      el.style.display = 'block';
      el.style.background = 'rgba(255,69,58,0.14)';
      el.style.color = 'var(--danger)';
      el.textContent = t('bootstrap.error', { msg: s.message || t('train.status.error') });
      if (btn) { btn.disabled = false; btn.textContent = t('bootstrap.download'); }
      renderBootstrapStatus._hideT = setTimeout(() => { el.style.display = 'none'; renderBootstrapStatus._hideT = null; }, 8000);
    }
  } else {
    el.style.display = 'none';
    if (btn) { btn.disabled = false; btn.textContent = 'Скачать'; }
  }
}

/* ===== Projects ===== */
async function loadProjects() {
  let projects = await api('/api/projects');
  _cachedProjectsList = Array.isArray(projects) ? projects : [];
  if (!projects.length && viewMode !== 'trash') {
    try {
      await api('/api/projects', {
        method: 'POST',
        body: new URLSearchParams({ name: 'Первый проект', object_class: 'Pig', object_class_source: 'list' }),
      });
      projects = await api('/api/projects');
      _cachedProjectsList = projects;
    } catch (e) {
      setError('Не удалось создать проект: ' + String(e.message).slice(0, 120));
      return;
    }
  }
  _renderProjectsList(projects);
  // V8.5.3: если сохранённый projectId валиден — оставляем его.
  if (!currentProjectId || !projects.find(x => x.id === currentProjectId)) {
    currentProjectId = projects.length ? projects[0].id : null;
    sessionSeen = new Set();
    _rememberProjectId(currentProjectId);
  }
  _syncCurrentProjectMeta(projects);

  if (currentProjectId && viewMode !== 'trash') {
    loadTags(true).then(() => loadImages());
  } else if (viewMode === 'trash') {
    loadImages();
  }
  highlightProject(document.querySelector(`#projects > div[data-project-id="${currentProjectId}"]`)
                  || document.querySelector('#projects > div'));
  updateCurrentProjectInfo();
  updateTrashBadge();
  _refreshActiveLearningDebounced();
}

function _rememberProjectId(id) {
  // V8.5.3: сохраняем выбор пользователя между запусками.
  try {
    if (id == null) localStorage.removeItem('pdb_currentProjectId');
    else localStorage.setItem('pdb_currentProjectId', String(id));
  } catch (e) {}
}

function _syncCurrentProjectMeta(projects) {
  if (!currentProjectId) { currentProjectMeta = null; return; }
  const p = projects.find(x => x.id === currentProjectId);
  if (p) {
    currentProjectMeta = {
      id: p.id, name: p.name,
      object_class: p.object_class || 'pig',
      object_class_source: p.object_class_source || 'list',
      images_count: p.images_count || 0,
      annotations_count: p.annotations_count || 0,
      trash_ttl_days_override: p.trash_ttl_days_override ?? null,
      thumbnail_size: p.thumbnail_size ?? null,
      default_zoom: p.default_zoom ?? null,
    };
    _applyProjectVisualSettings();
  } else {
    currentProjectMeta = null;
  }
}
function _applyProjectVisualSettings() {
  const meta = currentProjectMeta || {};
  const thumb = meta.thumbnail_size;
  const root = document.documentElement;
  if (thumb && Number.isFinite(thumb)) {
    root.style.setProperty('--thumb-size-project', thumb + 'px');
    root.setAttribute('data-project-thumb-size', String(thumb));
  } else {
    root.style.removeProperty('--thumb-size-project');
    root.removeAttribute('data-project-thumb-size');
  }
}

function _renderProjectsList(projects) {
  const div = document.getElementById('projects');
  div.innerHTML = '';
  if (!projects.length) {
    const e = document.createElement('div');
    e.style.cssText = 'padding:10px 12px;font-size:0.8125rem;color:var(--text-secondary);text-align:center;';
    e.textContent = 'Нет проектов';
    div.appendChild(e);
    return;
  }
  projects.forEach(p => {
    const d = document.createElement('div');
    d.dataset.projectId = p.id;
    d.setAttribute('role', 'option');
    d.setAttribute('aria-selected', 'false');
    const cls = p.object_class || 'pig';
    d.dataset.tooltip = `${p.name} · класс: ${cls} · ${p.images_count} фото`;

    const name = document.createElement('span');
    name.className = 'proj-name';
    name.textContent = p.name;
    d.appendChild(name);

    const cnt = document.createElement('span');
    cnt.className = 'proj-count';
    cnt.textContent = p.images_count;
    d.appendChild(cnt);

    const settings = document.createElement('span');
    settings.className = 'proj-settings';
    settings.setAttribute('role', 'button');
    settings.setAttribute('tabindex', '0');
    settings.setAttribute('aria-label', `Настройки проекта «${p.name}»`);
    settings.dataset.tooltip = 'Настройки проекта';
    settings.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';
    settings.addEventListener('mousedown', (e) => { e.stopPropagation(); e.preventDefault(); });
    settings.addEventListener('click', async (e) => { e.stopPropagation(); await openProjectEdit(p.id, p); });
    onActivate(settings, () => openProjectEdit(p.id, p), { stop: true });
    d.appendChild(settings);

    const del = document.createElement('span');
    del.className = 'proj-del';
    del.setAttribute('role', 'button');
    del.setAttribute('tabindex', '0');
    del.setAttribute('aria-label', `Удалить проект «${p.name}»`);
    del.dataset.tooltip = 'Удалить проект';
    del.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
    del.addEventListener('mousedown', (e) => { e.stopPropagation(); e.preventDefault(); });
    del.addEventListener('click', async (e) => { e.stopPropagation(); await confirmDeleteProject(p.id, p.name, p.images_count); });
    onActivate(del, () => confirmDeleteProject(p.id, p.name, p.images_count), { stop: true });
    d.appendChild(del);

    d.onclick = () => {
      if (viewMode === 'trash') { setStatus(t('toast.leaveTrash')); return; }
      if (currentProjectId === p.id) return;
      currentProjectId = p.id;
      _rememberProjectId(currentProjectId);   // V8.5.3
      selectedForDelete.clear(); activeTagIds.clear(); sessionSeen = new Set();
      _lastDomIds = new Set();
      currentProjectMeta = {
        id: p.id, name: p.name,
        object_class: p.object_class || 'pig',
        object_class_source: p.object_class_source || 'list',
        images_count: p.images_count || 0,
        annotations_count: p.annotations_count || 0,
        trash_ttl_days_override: p.trash_ttl_days_override ?? null,
        thumbnail_size: p.thumbnail_size ?? null,
        default_zoom: p.default_zoom ?? null,
      };
      _applyProjectVisualSettings();
      updateSectionUI();
      loadTags(true).then(() => loadImages());
      highlightProject(d);
      updateCurrentProjectInfo();
    };
    onActivate(d, () => d.click());
    // V8.1.0: принимаем drop изображений из другого проекта.
    d.addEventListener('dragover', (e) => {
      if (e.dataTransfer && Array.from(e.dataTransfer.types).includes('application/x-pdb-images')) {
        e.preventDefault(); e.dataTransfer.dropEffect = 'move';
        d.classList.add('drag-target');
      }
    });
    d.addEventListener('dragleave', () => d.classList.remove('drag-target'));
    d.addEventListener('drop', async (e) => {
      d.classList.remove('drag-target');
      const raw = e.dataTransfer.getData('application/x-pdb-images');
      if (!raw) return;
      e.preventDefault();
      let ids; try { ids = JSON.parse(raw); } catch (er) { return; }
      if (!ids || !ids.length) return;
      if (p.id === currentProjectId) { setStatus('Уже в этом проекте'); return; }
      try {
        const r = await api('/api/images/bulk_move_to_project', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image_ids: ids, target_project_id: p.id }),
        });
        selectedForDelete.clear();
        await loadProjects();
        await loadImages();
        setStatus(`Перенесено: ${r.moved}`, 4000);
        haptic('success');
      } catch (er) { setError('Drag-n-drop: ' + String(er.message).slice(0, 160)); }
    });
    div.appendChild(d);
  });
}
function updateCurrentProjectInfo() {
  const el = document.getElementById('currentProjectInfo');
  if (!el) return;
  if (viewMode === 'trash') { el.textContent = 'Корзина'; return; }
  if (!currentProjectId || !currentProjectMeta) { el.textContent = 'Проект не выбран'; return; }
  const cls = currentProjectMeta.object_class || 'pig';
  const src = currentProjectMeta.object_class_source === 'custom' ? ' (своё)' : '';
  el.textContent = `«${currentProjectMeta.name}» · класс: ${cls}${src} · id=${currentProjectId}`;
}
function highlightProject(el) {
  document.querySelectorAll('#projects > div').forEach(d => {
    d.classList.remove('active-project');
    d.setAttribute('aria-selected', 'false');
  });
  if (el) {
    el.classList.add('active-project');
    el.setAttribute('aria-selected', 'true');
  }
}

async function createProject() { await openProjectCreate(); }

async function openProjectCreate() {
  _projectModalMode = 'create';
  _projectModalTarget = null;
  await loadObjectClasses();

  const titleEl = document.getElementById('projectModalTitle');
  const nameInput = document.getElementById('projectNameInput');
  const classHost = document.getElementById('projectClassSearchHost');
  const warnEl = document.getElementById('projectClassWarn');
  const clearBtn = document.getElementById('projectClearAnnBtn');
  const okBtn = document.getElementById('projectModalOk');
  const nameLabel = document.getElementById('projectNameLabel');
  const classLabel = document.getElementById('projectClassLabel');
  const advBlock = document.getElementById('projectAdvancedBlock');

  titleEl.textContent = 'Новый проект';
  nameLabel.textContent = 'Имя проекта';
  classLabel.textContent = 'Класс объекта';
  nameInput.disabled = false;
  nameInput.value = '';
  warnEl.style.display = 'none';
  clearBtn.style.display = 'none';
  if (advBlock) advBlock.style.display = 'none';
  okBtn.textContent = 'Создать';
  okBtn.disabled = true;
  _projectThumbSize = null;
  _projectDefaultZoom = null;
  _projectTtlOverride = null;

  if (_projectClassSearch) _projectClassSearch.destroy();
  _projectClassSearch = createClassSearch(classHost, {
    initialValue: '',
    initialSource: 'list',
    disabled: false,
    placeholder: 'Начни печатать — например, Pig',
    onChange: () => _validateProjectForm(),
  });

  nameInput.oninput = () => _validateProjectForm();
  openModal('projectModal');
  setTimeout(() => { try { nameInput.focus(); } catch (e) {} }, 100);

  const status = objectClassesCache;
  if (status.source === 'empty') {
    warnEl.style.display = 'block';
    warnEl.className = 'project-warn warn-info';
    warnEl.textContent = 'Активная модель не загружена — список классов пуст. Введи название класса вручную и нажми «Использовать как есть».';
  } else {
    warnEl.style.display = 'none';
  }
}

async function openProjectEdit(projectId, preloaded) {
  _projectModalMode = 'edit';
  _projectModalTarget = null;
  await loadObjectClasses();

  let info = null;
  try {
    info = await api(`/api/projects/${projectId}/info`);
  } catch (e) {
    setError('Не удалось получить проект: ' + String(e.message).slice(0, 120));
    return;
  }
  _projectModalTarget = info;

  const titleEl = document.getElementById('projectModalTitle');
  const nameInput = document.getElementById('projectNameInput');
  const classHost = document.getElementById('projectClassSearchHost');
  const warnEl = document.getElementById('projectClassWarn');
  const clearBtn = document.getElementById('projectClearAnnBtn');
  const okBtn = document.getElementById('projectModalOk');
  const nameLabel = document.getElementById('projectNameLabel');
  const classLabel = document.getElementById('projectClassLabel');
  const advBlock = document.getElementById('projectAdvancedBlock');

  titleEl.textContent = 'Настройки проекта';
  nameLabel.textContent = 'Имя проекта';
  classLabel.textContent = 'Класс объекта';
  nameInput.disabled = true;
  nameInput.value = info.name || '';
  okBtn.textContent = 'Сохранить';
  okBtn.disabled = true;

  const annsCount = info.annotations_count || 0;
  const isClassLocked = annsCount > 0;

  if (_projectClassSearch) _projectClassSearch.destroy();
  _projectClassSearch = createClassSearch(classHost, {
    initialValue: info.object_class || 'pig',
    initialSource: info.object_class_source === 'custom' ? 'custom' : 'list',
    disabled: isClassLocked,
    placeholder: 'Поиск класса…',
    onChange: () => _validateProjectForm(),
  });

  if (isClassLocked) {
    warnEl.style.display = 'block';
    warnEl.className = 'project-warn warn-warn';
    warnEl.innerHTML = `${t('projectModal.classLocked.pre')} <b>${annsCount}</b> ` +
      `${pluralImages(annsCount)}. ${t('projectModal.classLocked.post')}`;
  } else if (objectClassesCache.source === 'empty') {
    warnEl.style.display = 'block';
    warnEl.className = 'project-warn warn-info';
    warnEl.textContent = 'Активная модель не загружена — список классов пуст. Введи название вручную и нажми «Использовать как есть».';
  } else {
    warnEl.style.display = 'none';
  }

  if (annsCount > 0) {
    clearBtn.style.display = '';
    clearBtn.disabled = false;
    clearBtn.textContent = t('projectModal.clearAnnotationsN', { n: annsCount });
  } else {
    clearBtn.style.display = 'none';
  }

  if (advBlock) advBlock.style.display = '';
  _fillProjectAdvancedSettings(info);
  openModal('projectModal');
  _validateProjectForm();
}

function _fillProjectAdvancedSettings(info) {
  _projectGlobalTtl = info.global_trash_ttl != null ? info.global_trash_ttl : 30;
  _projectTtlOverride = info.trash_ttl_days_override ?? null;
  _projectThumbSize = info.thumbnail_size ?? null;
  _projectDefaultZoom = info.default_zoom ?? null;

  const ttlInput = document.getElementById('projectTtlInput');
  if (ttlInput) {
    ttlInput.value = _projectTtlOverride != null ? String(_projectTtlOverride) : '';
    ttlInput.placeholder = t('projectModal.ttlPlaceholder');
  }
  const ttlHint = document.getElementById('projectTtlHint');
  if (ttlHint) ttlHint.textContent = t('projectModal.ttlHint.dynamic', { n: _projectGlobalTtl });

  const thumbSel = document.getElementById('projectThumbSelect');
  if (thumbSel) thumbSel.value = _projectThumbSize != null ? String(_projectThumbSize) : '';

  const zoomSel = document.getElementById('projectZoomSelect');
  if (zoomSel) zoomSel.value = _projectDefaultZoom != null ? String(_projectDefaultZoom) : '';
}

function _validateProjectForm() {
  const nameInput = document.getElementById('projectNameInput');
  const okBtn = document.getElementById('projectModalOk');
  if (!nameInput || !okBtn) return;

  const nameOk = _projectModalMode === 'edit' || nameInput.value.trim().length > 0;
  const classVal = _projectClassSearch ? _projectClassSearch.getValue() : { value: '', source: 'list' };
  const classOk = !!classVal.value;
  okBtn.disabled = !(nameOk && classOk);

  if (_projectModalMode === 'edit' && _projectModalTarget) {
    const t = _projectModalTarget;
    const sameClass = (t.object_class || 'pig') === classVal.value &&
      ((t.object_class_source || 'list') === classVal.source);
    const sameTtl = (t.trash_ttl_days_override ?? null) === _projectTtlOverride;
    const sameThumb = (t.thumbnail_size ?? null) === _projectThumbSize;
    const sameZoom = (t.default_zoom ?? null) === _projectDefaultZoom;
    const advancedChanged = !(sameTtl && sameThumb && sameZoom);
    if (sameClass && !advancedChanged) okBtn.disabled = true;
  }
}
function closeProjectModal() {
  closeModal('projectModal');
  if (_projectClassSearch) {
    try { _projectClassSearch.destroy(); } catch (e) {}
    _projectClassSearch = null;
  }
  _projectModalMode = null;
  _projectModalTarget = null;
}
async function submitProjectModal() {
  const nameInput = document.getElementById('projectNameInput');
  const okBtn = document.getElementById('projectModalOk');
  if (!nameInput || !_projectClassSearch) return;

  const classVal = _projectClassSearch.getValue();
  if (!classVal.value) { setStatus('Выбери класс объекта'); return; }

  if (_projectModalMode === 'create') {
    const name = nameInput.value.trim();
    if (!name) { setStatus('Введи имя проекта'); return; }
    okBtn.disabled = true;
    okBtn.textContent = 'Создаём…';
    try {
      const body = new URLSearchParams({
        name: name,
        object_class: classVal.value,
        object_class_source: classVal.source,
      });
      const r = await api('/api/projects', { method: 'POST', body });
      closeProjectModal();
      if (viewMode === 'trash') { viewMode = 'main'; updateSectionUI(); }
      _rememberProjectId(r && r.id ? r.id : null);   // V8.5.3
      await loadProjects();
      if (r && r.id) {
        const el = document.querySelector(`#projects > div[data-project-id="${r.id}"]`);
        if (el) el.click();
      }
      setStatus(t('toast.projectCreated', { name }));
      haptic('success');
    } catch (e) {
      okBtn.disabled = false;
      okBtn.textContent = 'Создать';
      setError('Ошибка: ' + String(e.message).slice(0, 160));
    }
    return;
  }

  if (_projectModalMode === 'edit' && _projectModalTarget) {
    okBtn.disabled = true;
    okBtn.textContent = 'Сохраняем…';
    try {
      const t = _projectModalTarget;
      const body = {
        object_class: classVal.value,
        object_class_source: classVal.source,
      };
      if ((t.thumbnail_size ?? null) !== _projectThumbSize) {
        if (_projectThumbSize != null) body.thumbnail_size = _projectThumbSize;
        else body.clear_thumbnail_size = true;
      }
      if ((t.default_zoom ?? null) !== _projectDefaultZoom) {
        if (_projectDefaultZoom != null) body.default_zoom = _projectDefaultZoom;
        else body.clear_default_zoom = true;
      }
      if ((t.trash_ttl_days_override ?? null) !== _projectTtlOverride) {
        if (_projectTtlOverride != null) body.trash_ttl_days_override = _projectTtlOverride;
        else body.clear_ttl_override = true;
      }
      await api(`/api/projects/${_projectModalTarget.id}/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      closeProjectModal();
      await loadProjects();
      setStatus(t('toast.projectSaved'));
      haptic('success');
    } catch (e) {
      okBtn.disabled = false;
      okBtn.textContent = 'Сохранить';
      if (e.status === 409) setError('В проекте есть рамки. Сначала очисти разметку.', 6000);
      else setError('Ошибка: ' + String(e.message).slice(0, 160));
    }
  }
}

async function clearProjectAnnotations() {
  if (!_projectModalTarget) return;
  const info = _projectModalTarget;
  const n = info.annotations_count || 0;
  if (!n) { setStatus('Разметки уже нет'); return; }
  const ok = await showConfirm(
    t('confirm.clearAnnotations.title'),
    t('confirm.clearAnnotations.text', { n, m: info.images_count, name: info.name }),
    { okText: t('confirm.clearAnnotations.ok'), danger: true }
  );
  if (!ok) return;
  haptic('warning');
  const btn = document.getElementById('projectClearAnnBtn');
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Очищаем…';
  try {
    const r = await api(`/api/projects/${info.id}/clear_annotations`, { method: 'POST' });
    _projectModalTarget.annotations_count = 0;
    _invalidateValidateCache();
    if (info.id === currentProjectId) {
      if (currentImageId) {
        try { boxes = await api(`/api/images/${currentImageId}/annotations`); }
        catch (e) { boxes = []; }
        renderBoxes(); resetHistory(); markClean();
      }
      await loadImages();
    }
    await loadProjects();
    const warnEl = document.getElementById('projectClassWarn');
    const clearBtn = document.getElementById('projectClearAnnBtn');
    clearBtn.style.display = 'none';
    warnEl.style.display = 'none';
    if (_projectClassSearch) _projectClassSearch.setDisabled(false);
    setStatus(`Очищено рамок: ${r.cleared || n}`);
    haptic('success');
  } catch (e) {
    btn.disabled = false;
    btn.textContent = origText;
    setError('Ошибка очистки: ' + String(e.message).slice(0, 160));
  }
}

async function confirmDeleteProject(id, name, count) {
  const ok = await showConfirm(
    t('confirm.deleteProject.title', { name }),
    t('confirm.deleteProject.text', { n: count, word: pluralImages(count) }),
    { okText: t('confirm.toTrash.ok') }
  );
  if (!ok) return;
  haptic('warning');
  try {
    await api(`/api/projects/${id}`, { method: 'DELETE' });
    if (currentProjectId === id) {
      currentImageId = null; boxes = []; selectedIndex = -1; multiSelected.clear();
      _rememberProjectId(null);   // V8.5.3
      const imgEl = document.getElementById('image');
      if (imgEl) imgEl.removeAttribute('src');
      renderBoxes(); showCanvas(false); resetHistory(); markClean();
    }
    await loadProjects();
    setStatus(t('toast.projectDeleted', { name }));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function restoreProject(id) {
  try {
    const r = await api(`/api/projects/${id}/restore`, { method: 'POST' });
    setStatus(t('toast.projectRestored', { name: r.name }));
    haptic('success');
    if (viewMode === 'trash') await loadImages();
    await loadProjects();
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function permanentDeleteProject(id, name) {
  const ok = await showConfirm(
    t('confirm.permanentProject.title', { name }),
    t('confirm.permanentProject.text2'),
    { okText: t('confirm.deletePerm.ok'), danger: true }
  );
  if (!ok) return;
  haptic('warning');
  try {
    await api(`/api/projects/${id}/permanent`, { method: 'DELETE' });
    setStatus(t('toast.projectPurged', { name }));
    if (currentProjectId === id) {
      currentProjectId = null;
      currentImageId = null; boxes = []; selectedIndex = -1; multiSelected.clear();
      const imgEl = document.getElementById('image');
      if (imgEl) imgEl.removeAttribute('src');
      renderBoxes(); showCanvas(false); resetHistory(); markClean();
    }
    if (viewMode === 'trash') await loadImages();
    await loadProjects();
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function emptyTrashAll() {
  const ok = await showConfirm(
    t('confirm.emptyTrash.title'),
    t('confirm.emptyTrash.text'),
    { okText: t('confirm.emptyTrash.ok'), danger: true }
  );
  if (!ok) return;
  haptic('warning');
  try {
    const pRes = await api('/api/projects/trash/empty', { method: 'POST' });
    let imgDeleted = 0;
    if (currentProjectId) {
      try {
        const r = await api(`/api/projects/${currentProjectId}/trash/empty`, { method: 'POST' });
        imgDeleted = r.deleted || 0;
      } catch (e) {}
    }
    setStatus(t('confirm.emptyTrash.result', { p: pRes.deleted, i: imgDeleted }));
    if (viewMode === 'trash') await loadImages();
    await loadProjects();
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}

/* ===== Trash ===== */
async function toggleTrash() {
  if (viewMode === 'trash') {
    viewMode = 'main';
    haptic('selection');
    _lastDomIds = new Set();
    updateSectionUI();
    await loadProjects();
    return;
  }
  viewMode = 'trash';
  haptic('selection');
  selectedForDelete.clear();
  _lastDomIds = new Set();
  currentImageId = null;
  boxes = []; selectedIndex = -1; multiSelected.clear();
  _clearDebugBoxes();
  const imgEl = document.getElementById('image');
  if (imgEl) imgEl.removeAttribute('src');
  renderBoxes(); showCanvas(false); resetHistory(); markClean(); updateDelBoxBtn();
  updateSectionUI();
  await loadImages();
  await renderTagChips();
}
async function updateTrashBadge() {
  const badge = document.getElementById('trashBadge');
  if (!badge) return;
  try {
    let count = 0;
    try {
      const projects = await api('/api/projects/trash');
      count += projects.length;
    } catch (e) {}
    if (currentProjectId) {
      try {
        const imgs = await api(`/api/projects/${currentProjectId}/trash`);
        count += imgs.length;
      } catch (e) {}
    }
    if (count > 0) { badge.textContent = String(count); badge.style.display = 'block'; }
    else { badge.style.display = 'none'; }
  } catch (e) { badge.style.display = 'none'; }
}

function updateSectionUI() {
  const section = document.getElementById('imagesSection');
  const title = document.getElementById('sectionTitle');
  const trashBtn = document.getElementById('trashToggleBtn');
  const bulkBar = document.getElementById('bulkBar');
  const trashBulkBar = document.getElementById('trashBar');
  const projectsTitle = document.getElementById('projectsSectionTitle');
  const createProjectBtn = document.getElementById('createProjectBtn');
  const uploadSection = document.getElementById('uploadSection');
  const trashActionsBar = document.getElementById('trashActionsBar');

  const isTrash = viewMode === 'trash';
  if (trashBtn) {
    trashBtn.classList.toggle('active', isTrash);
    trashBtn.setAttribute('aria-pressed', isTrash ? 'true' : 'false');
  }
  // V9.0.0: i18n для динамических заголовков.
  if (projectsTitle) projectsTitle.textContent = isTrash ? t('sidebar.trash') : t('sidebar.projects');
  if (createProjectBtn) createProjectBtn.style.display = isTrash ? 'none' : '';
  if (uploadSection) uploadSection.style.display = isTrash ? 'none' : '';
  if (trashActionsBar) trashActionsBar.style.display = isTrash ? 'flex' : 'none';

  if (isTrash) {
    section.classList.add('trash-mode');
    title.textContent = t('sidebar.images.trashTitle');
    bulkBar.classList.remove('open');
    if (trashBulkBar) trashBulkBar.classList.remove('open');
  } else {
    section.classList.remove('trash-mode');
    title.textContent = t('sidebar.images');
    if (trashBulkBar) trashBulkBar.classList.remove('open');
  }
  updateBulkBar(); updateTrashBar(); updateSelectAllCheck(); updateFilterBadge();
  updateBulkTagBtn();
  updateTrashActionsBar();
}

async function loadTrashView() {
  const projects = await api('/api/projects/trash');
  const projItems = projects.map(p => ({
    _kind: 'project', id: p.id, name: p.name,
    images_count: p.images_count, days_left: p.days_left, deleted_at: p.deleted_at,
  }));
  let imgItems = [];
  if (currentProjectId) {
    try {
      const imgs = await api(`/api/projects/${currentProjectId}/trash`);
      imgItems = imgs.map(i => ({ ...i, _kind: 'image' }));
    } catch (e) { imgItems = []; }
  }
  return { projItems, imgItems };
}

/* ===== Logs ===== */
async function openLogsFromSettings() { closeSettings(); setTimeout(() => openLogs(), 80); }
function openLogs() { refreshLogs(); openModal('logsModal'); startLogsAutoRefresh(); }
function closeLogs() { stopLogsAutoRefresh(); closeModal('logsModal'); }
function startLogsAutoRefresh() {
  stopLogsAutoRefresh();
  const cb = document.getElementById('logsAutoRefresh');
  if (!cb || !cb.checked) return;
  _logsRefreshTimer = setInterval(() => { refreshLogs(true); }, 4000);
}
function stopLogsAutoRefresh() {
  if (_logsRefreshTimer) { clearInterval(_logsRefreshTimer); _logsRefreshTimer = null; }
}
async function refreshLogs(silent = false) {
  const body = document.getElementById('logsBody');
  if (!body) return;
  const level = document.getElementById('logsLevelFilter').value;
  const category = document.getElementById('logsCategoryFilter').value;
  const params = new URLSearchParams();
  params.set('limit', '500');
  if (level) params.set('level', level);
  if (category) params.set('category', category);
  try {
    const r = await api('/api/logs?' + params.toString());
    renderLogs(r.items || []);
  } catch (e) {
    if (!silent) body.innerHTML = `<div class="logs-empty">${escapeHtml(t('logs.errorLoading', { msg: String(e.message || e) }))}</div>`;
  }
}
function renderLogs(items) {
  const body = document.getElementById('logsBody');
  if (!body) return;
  if (!items.length) { body.innerHTML = `<div class="logs-empty">${t('logs.empty')}</div>`; return; }
  const scrollPos = body.scrollTop;
  const nearBottom = (body.scrollHeight - body.scrollTop - body.clientHeight) < 60;
  const frag = document.createDocumentFragment();
  items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'log-entry lv-' + (item.level || 'info');
    const ts = document.createElement('span');
    ts.className = 'log-ts'; ts.textContent = (item.ts || '').replace('T', ' ');
    const cat = document.createElement('span');
    cat.className = 'log-cat cat-' + (item.category || 'system');
    cat.textContent = item.category || 'system';
    const msg = document.createElement('span');
    msg.className = 'log-msg'; msg.textContent = item.message || '';
    div.appendChild(ts); div.appendChild(cat); div.appendChild(msg);
    frag.appendChild(div);
  });
  body.innerHTML = '';
  body.appendChild(frag);
  if (nearBottom) body.scrollTop = body.scrollHeight; else body.scrollTop = scrollPos;
}
async function clearLogs() {
  const ok = await showConfirm(
    t('confirm.clearLogs.title'),
    t('confirm.clearLogs.text'),
    { okText: t('confirm.clearLogs.ok'), danger: true }
  );
  if (!ok) return;
  try {
    await api('/api/logs', { method: 'DELETE' });
    refreshLogs(); setStatus(t('toast.logsCleared'));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}

/* ===== Backup ===== */
async function doBackup() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const btn = document.getElementById('backupBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Бэкапим…'; }
  setStatus('Создаём бэкап проекта…', 60000);
  try {
    const r = await api(`/api/projects/${currentProjectId}/backup`, { method: 'POST' });
    const sizeMb = (r.size / 1024 / 1024).toFixed(2);
    setSuccess(`Бэкап готов: ${r.filename} (${sizeMb} МБ)`, 7000);
    await showBackupResult(r);
    haptic('success');
  } catch (e) {
    setError('Ошибка бэкапа: ' + String(e.message).slice(0, 200), 8000);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Сделать бэкап';
    }
  }
}
function showBackupResult(r) {
  return new Promise((resolve) => {
    const titleEl = document.getElementById('dialogTitle');
    const textEl = document.getElementById('dialogText');
    const inputWrap = document.getElementById('dialogInputWrap');
    const cancelBtn = document.getElementById('dialogCancel');
    const okBtn = document.getElementById('dialogOk');

    titleEl.textContent = t('backup.created');
    textEl.className = 'backup-info';
    textEl.innerHTML = `
      <div class="backup-info-block">
        <div class="backup-info-label">${t('backup.file')}</div>
        <div class="backup-info-value">${escapeHtml(r.filename)}</div>
      </div>
      <div class="backup-info-grid">
        <div><div class="backup-info-label">${t('backup.images')}</div><div>${r.images_count}</div></div>
        <div><div class="backup-info-label">${t('backup.size')}</div><div>${(r.size / 1024 / 1024).toFixed(2)} MB</div></div>
        <div><div class="backup-info-label">${t('backup.boxes')}</div><div>${r.annotations_count}</div></div>
        <div><div class="backup-info-label">${t('backup.tags')}</div><div>${r.tags_count}</div></div>
      </div>`;
    textEl.style.display = '';
    inputWrap.style.display = 'none';
    cancelBtn.style.display = '';
    cancelBtn.textContent = 'Закрыть';
    okBtn.textContent = 'Скачать';
    okBtn.className = 'btn btn-primary';

    const cleanup = () => {
      okBtn.onclick = null; cancelBtn.onclick = null; textEl.className = '';
    };
    okBtn.onclick = () => {
      cleanup();
      _closeDialog(true);
      const url = `/api/projects/${currentProjectId}/backup/download/${encodeURIComponent(r.filename)}`;
      downloadFile(url, r.filename);
      resolve();
    };
    cancelBtn.onclick = () => { cleanup(); _closeDialog(null); resolve(); };

    openModal('dialogModal');
    setTimeout(() => { try { okBtn.focus(); } catch (e) {} }, 80);
  });
}

/* ===== Tags ===== */
async function loadTags(force = false) {
  if (!currentProjectId) { projectTags = []; projectTagsMap = new Map(); return; }
  const now = Date.now();
  if (!force && (now - _tagsLastLoadedAt) < 1000 && projectTags.length) {
    try { renderTagFilter(); } catch (e) { console.warn('renderTagFilter failed', e); }
    try { renderTagsManager(); } catch (e) { console.warn('renderTagsManager failed', e); }
    return;
  }
  try {
    projectTags = await api(`/api/projects/${currentProjectId}/tags`);
    projectTagsMap = new Map(projectTags.map(t => [t.id, t]));
    _tagsLastLoadedAt = now;
  } catch (e) {
    projectTags = []; projectTagsMap = new Map();
  }
  try { renderTagFilter(); } catch (e) { console.warn('renderTagFilter failed', e); }
  try { renderTagsManager(); } catch (e) { console.warn('renderTagsManager failed', e); }
}
function renderTagFilter() {
  const list = document.getElementById('tagFilterList');
  list.innerHTML = '';
  if (!projectTags.length) {
    const e = document.createElement('div');
    e.style.cssText = 'padding:6px 10px;font-size:0.75rem;color:var(--text-secondary);';
    e.textContent = t('tags.empty'); list.appendChild(e); return;
  }
  projectTags.forEach(tag => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = activeTagIds.has(tag.id);
    cb.addEventListener('change', () => {
      if (cb.checked) activeTagIds.add(tag.id); else activeTagIds.delete(tag.id);
      updateFilterBadge();
      // V7.9.3: смена фильтра по тегам — перезапрос к серверу.
      loadImages();
    });
    const dot = document.createElement('span');
    dot.className = 'tag-dot'; dot.style.background = tag.color;
    const name = document.createElement('span');
    name.style.flex = '1'; name.textContent = tag.name;
    const cnt = document.createElement('span');
    cnt.style.cssText = 'font-size:0.6875rem;color:var(--text-secondary);';
    cnt.textContent = tag.count;
    label.appendChild(cb); label.appendChild(dot); label.appendChild(name); label.appendChild(cnt);
    list.appendChild(label);
  });
}
function renderTagsManager() {
  const list = document.getElementById('tagList');
  if (!list) return;
  list.innerHTML = '';
  if (!projectTags.length) {
    const e = document.createElement('div');
    e.style.cssText = 'font-size:0.8125rem;color:var(--text-secondary);padding:8px 0;';
    e.textContent = t('tags.manager.empty');
    list.appendChild(e); return;
  }
  const frag = document.createDocumentFragment();
  projectTags.forEach(tag => {
    const row = document.createElement('div');
    row.className = 'tag-row';
    const dot = document.createElement('span');
    dot.className = 'tag-color-dot'; dot.style.background = tag.color;
    const name = document.createElement('span');
    name.className = 'tag-name'; name.textContent = tag.name;
    const cnt = document.createElement('span');
    cnt.className = 'tag-count'; cnt.textContent = t('tags.count', { n: tag.count });
    const editBtn = document.createElement('button');
    editBtn.className = 'icon-btn';
    editBtn.setAttribute('aria-label', 'Редактировать тег');
    editBtn.dataset.tooltip = t('tags.manager.edit');
    editBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>';
    editBtn.onclick = () => editTag(tag);
    const delBtn = document.createElement('button');
    delBtn.className = 'icon-btn';
    delBtn.setAttribute('aria-label', 'Удалить тег');
    delBtn.dataset.tooltip = t('tags.manager.delete');
    delBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>';
    delBtn.onclick = () => deleteTag(tag);
    row.appendChild(dot); row.appendChild(name); row.appendChild(cnt);
    row.appendChild(editBtn); row.appendChild(delBtn);
    frag.appendChild(row);
  });
  list.appendChild(frag);
}
async function createTag() {
  const name = document.getElementById('newTagName').value.trim();
  const color = document.getElementById('newTagColor').value;
  if (!name) { setStatus('Введите имя тега'); return; }
  try {
    await api(`/api/projects/${currentProjectId}/tags`, { method: 'POST', body: new URLSearchParams({ name, color }) });
    document.getElementById('newTagName').value = '';
    _tagsLastLoadedAt = 0;
    await loadTags(true); await renderTagChips();
    setStatus(t('toast.tagCreated', { name })); haptic('success');
  } catch (e) {
    if (e.status === 409) setStatus(t('toast.tagExists'));
    else setError('Ошибка: ' + String(e.message).slice(0, 120));
  }
}
async function editTag(tag) {
  const name = await showPrompt(
    t('prompt.renameTag.title'),
    { defaultValue: tag.name, okText: t('common.save') }
  );
  if (name === null) return;
  const nm = String(name).trim();
  if (!nm) return;
  try {
    await api(`/api/tags/${tag.id}`, { method: 'PATCH', body: new URLSearchParams({ name: nm }) });
    _tagsLastLoadedAt = 0;
    await loadTags(true); await renderTagChips();
    setStatus(t('toast.tagUpdated'));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function deleteTag(tag) {
  const ok = await showConfirm(
    t('confirm.deleteTag.title', { name: tag.name }),
    t('confirm.deleteTag.text'),
    { okText: t('confirm.deletePerm.ok'), danger: true }
  );
  if (!ok) return;
  haptic('warning');
  try {
    await api(`/api/tags/${tag.id}`, { method: 'DELETE' });
    activeTagIds.delete(tag.id);
    _tagsLastLoadedAt = 0;
    await loadTags(true);
    applyFiltersAndRender(); await renderTagChips();
    setStatus(t('toast.tagDeleted'));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
function openTagsManagerFromSettings() { closeSettings(); setTimeout(() => openTagsManager(), 80); }
function openTagsManager() { renderTagsManager(); openModal('tagsManagerModal'); }
function closeTagsManager() { closeModal('tagsManagerModal'); }

/* ===== Tag chips ===== */
async function renderTagChips() {
  const bar = document.getElementById('tagChipsBar');
  const list = document.getElementById('tagChipsList');
  const bulk = document.getElementById('tagChipsBulk');
  if (!currentProjectId || viewMode === 'trash') { bar.style.display = 'none'; return; }
  const hasContext = !!currentImageId || selectedForDelete.size > 0;
  if (!hasContext) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  const n = selectedForDelete.size;
  if (n > 0) { bulk.style.display = ''; bulk.textContent = t('tags.chips.applyTo', { n }) + ' ' + pluralImages(n); }
  else bulk.style.display = 'none';
  currentImageTagIds = new Set();
  if (n > 0) {
    const selectedMetas = allImages.filter(i => selectedForDelete.has(i.id));
    if (selectedMetas.length) {
      const firstTags = new Set(selectedMetas[0].tag_ids || []);
      for (let k = 1; k < selectedMetas.length; k++) {
        const mTags = new Set(selectedMetas[k].tag_ids || []);
        for (const t of Array.from(firstTags)) { if (!mTags.has(t)) firstTags.delete(t); }
      }
      currentImageTagIds = firstTags;
    }
  } else if (currentImageId) {
    const meta = allImages.find(i => i.id === currentImageId);
    if (meta && meta.tag_ids) meta.tag_ids.forEach(tid => currentImageTagIds.add(tid));
  }
  list.innerHTML = '';
  if (!projectTags.length) {
    const e = document.createElement('span');
    e.style.cssText = 'font-size:0.75rem;color:var(--text-secondary);';
    e.textContent = t('tags.chips.empty'); list.appendChild(e); return;
  }
  projectTags.forEach(tag => {
    const chip = document.createElement('button');
    chip.className = 'tag-chip' + (currentImageTagIds.has(tag.id) ? ' active' : '');
    chip.setAttribute('aria-pressed', currentImageTagIds.has(tag.id) ? 'true' : 'false');
    chip.onclick = (e) => { e.stopPropagation(); toggleTagChip(tag.id); };
    const dot = document.createElement('span');
    dot.className = 'tag-chip-dot'; dot.style.background = tag.color;
    chip.appendChild(dot);
    const name = document.createElement('span');
    name.textContent = tag.name;
    chip.appendChild(name);
    if (tag.count > 0) {
      const cnt = document.createElement('span');
      cnt.className = 'tag-chip-count'; cnt.textContent = tag.count;
      chip.appendChild(cnt);
    }
    list.appendChild(chip);
  });
}
async function toggleTagChip(tagId) {
  const targetIds = selectedForDelete.size > 0 ? Array.from(selectedForDelete) : (currentImageId ? [currentImageId] : []);
  if (!targetIds.length) return;
  const metas = allImages.filter(i => targetIds.includes(i.id));
  if (!metas.length) return;
  const hasOnAll = metas.every(m => (m.tag_ids || []).includes(tagId));
  try {
    await api('/api/images/batch_tags', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_ids: targetIds,
        add: hasOnAll ? [] : [tagId],
        remove: hasOnAll ? [tagId] : [],
      }),
    });
    metas.forEach(m => {
      const s = new Set(m.tag_ids || []);
      if (hasOnAll) s.delete(tagId); else s.add(tagId);
      m.tag_ids = Array.from(s);
      _invalidateTagSet(m);
    });
    const tag = projectTags.find(t => t.id === tagId);
    if (tag) {
      if (hasOnAll) tag.count = Math.max(0, (tag.count || 0) - metas.length);
      else tag.count = (tag.count || 0) + metas.length;
    }
    targetIds.forEach(iid => _refreshRowMeta(iid, { flash: true }));
    renderTagFilter();
    await renderTagChips();
    setStatus(hasOnAll ? t('toast.tagRemoved') : t('toast.tagApplied'));
    haptic('selection');
  } catch (e) {
    setError('Ошибка тега: ' + String(e.message).slice(0, 140));
    _tagsLastLoadedAt = 0;
    await loadTags(true);
  }
}
function openTagCreate() {
  document.getElementById('newTagNameInline').value = '';
  const picker = document.getElementById('newTagColorInline');
  if (picker) picker.value = '#0071e3';
  document.querySelectorAll('.color-picker').forEach(w => {
    const inner = w.querySelector('input[type="color"]');
    const sw = w.querySelector('.color-picker-swatch');
    if (inner && sw) sw.style.background = inner.value;
  });
  openModal('tagCreateModal');
}
function closeTagCreate() { closeModal('tagCreateModal'); }
async function createTagInline() {
  const name = document.getElementById('newTagNameInline').value.trim();
  const color = document.getElementById('newTagColorInline').value;
  if (!name) { setStatus('Введите имя тега'); return; }
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  try {
    const newTag = await api(`/api/projects/${currentProjectId}/tags`, { method: 'POST', body: new URLSearchParams({ name, color }) });
    _tagsLastLoadedAt = 0;
    await loadTags(true);
    const targetIds = selectedForDelete.size > 0 ? Array.from(selectedForDelete) : (currentImageId ? [currentImageId] : []);
    if (targetIds.length) {
      await api('/api/images/batch_tags', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_ids: targetIds, add: [newTag.id], remove: [] }),
      });
      targetIds.forEach(iid => {
        const meta = allImages.find(x => x.id === iid);
        if (meta) {
          const s = new Set(meta.tag_ids || []);
          s.add(newTag.id); meta.tag_ids = Array.from(s);
          _invalidateTagSet(meta);
        }
      });
    }
    targetIds.forEach(iid => _refreshRowMeta(iid, { flash: true }));
    await renderTagChips();
    closeTagCreate();
    setStatus(t('toast.tagCreated', { name: newTag.name }));
    haptic('success');
  } catch (e) {
    if (e.status === 409) setStatus(t('toast.tagExists'));
    else setError('Ошибка: ' + String(e.message).slice(0, 120));
  }
}

/* ===== Bulk-tag menu ===== */
function updateBulkTagBtn() {
  const btn = document.getElementById('bulkTagBtn');
  if (!btn) return;
  const n = selectedForDelete.size;
  btn.style.display = n > 0 ? '' : 'none';
  btn.disabled = false;
  btn.classList.toggle('active', n > 0);
  const fops = document.getElementById('fileOpsBtn');
  if (fops) fops.style.display = n > 0 ? '' : 'none';
}
function toggleBulkTagMenu(e) {
  if (e) e.stopPropagation();
  if (selectedForDelete.size === 0) return;
  const menu = document.getElementById('bulkTagMenu');
  const btn = document.getElementById('bulkTagBtn');
  const isOpen = menu.classList.contains('open');
  closeAllPopovers(null);
  if (isOpen) return;
  renderBulkTagMenu();
  const r = btn.getBoundingClientRect();
  const MENU_W = 240;
  let left = r.left;
  if (left + MENU_W > window.innerWidth - 8) left = Math.max(8, window.innerWidth - MENU_W - 8);
  menu.style.left = left + 'px';
  menu.style.top = (r.bottom + 6) + 'px';
  menu.classList.add('open');
}
function renderBulkTagMenu() {
  const list = document.getElementById('bulkTagList');
  if (!list) return;
  list.innerHTML = '';
  if (!projectTags.length) {
    const e = document.createElement('div');
    e.style.cssText = 'padding:8px 10px;font-size:0.75rem;color:var(--text-secondary);';
    e.textContent = t('tags.bulk.empty');
    list.appendChild(e); return;
  }
  const ids = Array.from(selectedForDelete);
  const metas = allImages.filter(i => ids.includes(i.id));
  const tagSets = metas.map(m => new Set(m.tag_ids || []));
  const frag = document.createDocumentFragment();
  projectTags.forEach(tag => {
    const isOnAll = tagSets.length > 0 && tagSets.every(s => s.has(tag.id));
    const btn = document.createElement('button');
    btn.className = 'bulk-tag-item' + (isOnAll ? ' active' : '');
    btn.setAttribute('role', 'menuitem');
    btn.setAttribute('aria-checked', isOnAll ? 'true' : 'false');
    const dot = document.createElement('span');
    dot.className = 'tag-dot'; dot.style.background = tag.color;
    btn.appendChild(dot);
    const name = document.createElement('span');
    name.style.flex = '1'; name.textContent = tag.name;
    btn.appendChild(name);
    const check = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    check.setAttribute('viewBox', '0 0 24 24');
    check.setAttribute('aria-hidden', 'true');
    check.classList.add('bulk-tag-check');
    check.innerHTML = '<polyline points="20 6 9 17 4 12"/>';
    btn.appendChild(check);
    btn.onclick = async (e) => { e.stopPropagation(); await bulkToggleTag(tag.id); };
    frag.appendChild(btn);
  });
  list.appendChild(frag);
}
async function bulkToggleTag(tagId) {
  const ids = Array.from(selectedForDelete);
  if (!ids.length) return;
  const metas = allImages.filter(i => ids.includes(i.id));
  const hasOnAll = metas.length > 0 && metas.every(m => (m.tag_ids || []).includes(tagId));
  try {
    await api('/api/images/batch_tags', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_ids: ids, add: hasOnAll ? [] : [tagId], remove: hasOnAll ? [tagId] : [] }),
    });
    metas.forEach(m => {
      const s = new Set(m.tag_ids || []);
      if (hasOnAll) s.delete(tagId); else s.add(tagId);
      m.tag_ids = Array.from(s);
      _invalidateTagSet(m);
    });
    const tag = projectTags.find(t => t.id === tagId);
    if (tag) {
      const delta = metas.length;
      tag.count = hasOnAll ? Math.max(0, (tag.count || 0) - delta) : (tag.count || 0) + delta;
    }
    ids.forEach(iid => _refreshRowMeta(iid, { flash: true }));
    renderTagFilter();
    renderBulkTagMenu();
    setStatus(hasOnAll ? t('toast.tagRemoved') : t('toast.tagApplied'));
    haptic('selection');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 140)); }
}

/* ===== Filters / sort ===== */
function applyFiltersAndRender() {
  if (viewMode === 'trash') {
    const projItems = allImages.filter(x => x._kind === 'project');
    const imgItems = allImages.filter(x => x._kind !== 'project');
    const sortedImgs = sortImages(imgItems, sortMode);
    imagesList = [...projItems, ...sortedImgs];
    _recomputeCounters();
    renderImageList({ flip: true });
    updateProgress(); updateSelectAllCheck(); updateHardBtn(); updateSimilarBtn();
    updateBulkTagBtn();
    return;
  }
  // V8.1.1: name_/type_/conf_ сортируем на клиенте (natural sort),
  // date_/size_ уже отсортированы сервером.
  let _source = allImages;
  if (!sortMode.startsWith('date_') && !sortMode.startsWith('size_')) {
    _source = sortImages(allImages, sortMode);
  }
  imagesList = _buildSectionList(_source);
  _recomputeCounters();
  renderImageList({ flip: true });
  updateProgress(); updateSelectAllCheck(); updateHardBtn(); updateSimilarBtn();
  updateBulkTagBtn();
}
function _recomputeCounters() {
  // V7.9.3: используем totals с сервера (не зависят от фильтров),
  // а если их нет (старый API / trash) — считаем локально.
  if (viewMode === 'main' && _imagesTotalInProject > 0) {
    _totalCount = _imagesTotalInProject;
    _annotatedCount = _imagesAnnotatedInProject;
  } else {
    _totalCount = allImages.length;
    _annotatedCount = 0;
    for (let i = 0; i < allImages.length; i++) {
      if ((allImages[i].annotation_count || 0) > 0) _annotatedCount++;
    }
  }
  _updateTitleProgress();
}
function filterList(arr) {
  let out = arr;
  if (activeFilter === 'unannotated') out = out.filter(x => (x.annotation_count || 0) === 0);
  else if (activeFilter === 'lowconf') out = out.filter(x => (x.low_conf_count || 0) > 0);
  else if (activeFilter === 'hard') out = out.filter(x => !!x.is_hard);
  if (activeTagIds.size > 0) {
    out = out.filter(x => {
      const s = _getTagSet(x);
      for (const tid of activeTagIds) if (s.has(tid)) return true;
      return false;
    });
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    out = out.filter(x => x.filename.toLowerCase().includes(q));
  }
  return out;
}
function confSortKey(x) {
  const c = x.annotation_count || 0;
  if (c === 0) return -1;
  if (x.min_confidence == null) return 1.5;
  return x.min_confidence;
}
function sortImages(images, mode) {
  const arr = [...images];
  switch (mode) {
    case 'name_asc': return arr.sort((a, b) => a.filename.localeCompare(b.filename, 'ru', { numeric: true }));
    case 'name_desc': return arr.sort((a, b) => b.filename.localeCompare(a.filename, 'ru', { numeric: true }));
    case 'type_asc': return arr.sort((a, b) => {
      const c = getExt(a.filename).localeCompare(getExt(b.filename));
      return c !== 0 ? c : a.filename.localeCompare(b.filename, 'ru', { numeric: true });
    });
    case 'type_desc': return arr.sort((a, b) => {
      const c = getExt(b.filename).localeCompare(getExt(a.filename));
      return c !== 0 ? c : a.filename.localeCompare(b.filename, 'ru', { numeric: true });
    });
    case 'conf_asc': return arr.sort((a, b) => confSortKey(a) - confSortKey(b));
    case 'conf_desc': return arr.sort((a, b) => confSortKey(b) - confSortKey(a));
    case 'date_asc': return arr.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
    case 'date_desc': return arr.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    case 'size_asc': return arr.sort((a, b) => (a.file_size || 0) - (b.file_size || 0));
    case 'size_desc': return arr.sort((a, b) => (b.file_size || 0) - (a.file_size || 0));
    default: return arr;
  }
}
// V8.1.0: отменяем предыдущий loadImages при новом вызове
// (быстрая смена сортировки/фильтра больше не даёт гонок ответов).
let _loadImagesAbort = null;
function _cancelLoadImages() {
  if (_loadImagesAbort) { try { _loadImagesAbort.abort(); } catch (e) {} _loadImagesAbort = null; }
}

async function loadImages() {
  if (!currentProjectId && viewMode !== 'trash') return;
  if (viewMode === 'trash') {
    showImageSkeleton();
    try {
      const { projItems, imgItems } = await loadTrashView();
      allImages = [...projItems, ...imgItems];
      _imagesHasMore = false;
      applyFiltersAndRender();
      updateTrashActionsBar(); updateBulkBar(); updateTrashBar(); updateFilterBadge();
      updateTrashBadge();
    } catch (e) {
      console.error('loadTrashView failed:', e);
      allImages = []; imagesList = [];
      renderImageList();
      setError('Ошибка загрузки: ' + String(e.message || e).slice(0, 120), 6000);
    }
    return;
  }

  _cancelLoadImages();
  _loadImagesAbort = new AbortController();
  const _signal = _loadImagesAbort.signal;
  showImageSkeleton();
  // V7.9.3: пагинация.
  // Отключаем её для сортировок по типу/уверенности и для фильтров
  // «неразмеченные/низкая уверенность» — эти вещи клиент делает сам,
  // потому что серверная реализация разъедется между SQLite/MySQL.
  // V8.1.1: пагинация только для date_/size_ (их сортирует сервер).
  // name_/type_/conf_ — клиент делает natural sort, нужен полный список.
  const usePaging = (sortMode.startsWith('date_') || sortMode.startsWith('size_'))
                    && activeFilter !== 'unannotated'
                    && activeFilter !== 'lowconf';
  const limit = usePaging ? IMAGES_PAGE_SIZE : 0;

  try {
    const raw = await api(`/api/projects/${currentProjectId}/images?${_imagesQueryParams(limit, 0)}`, { signal: _signal });
    if (Array.isArray(raw)) {
      // Старый режим: всё сразу (limit=0)
      allImages = raw;
      _imagesHasMore = false;
      _imagesTotalInProject = raw.length;
      _imagesAnnotatedInProject = 0;
      for (let i = 0; i < raw.length; i++) {
        if ((raw[i].annotation_count || 0) > 0) _imagesAnnotatedInProject++;
      }
    } else {
      allImages = raw.items || [];
      _imagesTotalInProject = raw.project_total || allImages.length;
      _imagesAnnotatedInProject = raw.annotated_total || 0;
      _imagesHasMore = (raw.offset + allImages.length) < raw.total;
    }
    applyFiltersAndRender();
    updateTrashActionsBar(); updateBulkBar(); updateTrashBar(); updateFilterBadge();
    updateTrashBadge();
    _refreshActiveLearningDebounced();
  } catch (e) {
    if (e && e.name === 'AbortError') return;
    console.error('loadImages failed:', e);
    allImages = []; imagesList = [];
    renderImageList();
    setError('Ошибка загрузки: ' + String(e.message || e).slice(0, 120), 6000);
  }
}

// V7.9.3: параметры запроса для /images
function _imagesQueryParams(limit, offset) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    sort: sortMode,
    filter: activeFilter,
    search: searchQuery || '',
  });
  if (activeTagIds.size) params.set('tag_ids', [...activeTagIds].join(','));
  return params.toString();
}

// V7.9.3: догрузка следующей страницы при скролле
async function loadMoreImages() {
  if (_imagesLoadingMore || !_imagesHasMore) return;
  if (viewMode !== 'main' || !currentProjectId) return;
  _imagesLoadingMore = true;
  try {
    const raw = await api(`/api/projects/${currentProjectId}/images?${_imagesQueryParams(IMAGES_PAGE_SIZE, allImages.length)}`);
    if (!raw || !Array.isArray(raw.items)) return;
    if (raw.items.length === 0) { _imagesHasMore = false; return; }
    allImages = allImages.concat(raw.items);
    _imagesHasMore = (raw.offset + allImages.length) < raw.total;
    applyFiltersAndRender();
    updateSelectAllCheck();
  } catch (e) {
    console.warn('loadMoreImages failed:', e);
  } finally {
    _imagesLoadingMore = false;
  }
}
function showImageSkeleton() {
  const inner = document.getElementById('imageListInner');
  if (!inner || (allImages && allImages.length)) return;
  inner.innerHTML = '';
  inner.style.height = (8 * ROW_H) + 'px';
  for (let i = 0; i < 8; i++) {
    const row = document.createElement('div');
    row.className = 'img-row skeleton-row';
    row.style.top = (i * ROW_H) + 'px';
    const thumb = document.createElement('div');
    thumb.className = 'skeleton';
    thumb.style.cssText = 'width:24px;height:24px;border-radius:6px;flex:0 0 24px;';
    const line = document.createElement('div');
    line.className = 'skeleton';
    line.style.cssText = 'height:12px;border-radius:6px;flex:1;max-width:60%;';
    row.appendChild(thumb); row.appendChild(line);
    inner.appendChild(row);
  }
}
function makeStatusDot(img) {
  const status = document.createElement('span');
  let statusKey = 'empty', title = 'Не размечено';
  if ((img.annotation_count || 0) > 0) {
    if ((img.low_conf_count || 0) > 0) { statusKey = 'suspicious'; title = `Низкая уверенность (${img.low_conf_count})`; }
    else { statusKey = 'annotated'; title = 'Размечено'; }
  }
  status.className = 'img-status';
  status.dataset.status = statusKey;
  status.setAttribute('aria-label', title);
  status.dataset.tooltip = title;
  return status;
}
function makeHardIndicator(isHard) {
  const el = document.createElement('span');
  el.className = 'img-hard' + (isHard ? ' flagged' : '');
  el.setAttribute('aria-hidden', 'true');
  if (isHard) {
    el.setAttribute('aria-label', 'Помечен как сложный');
    el.dataset.tooltip = 'Помечен как сложный';
  }
  el.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 2v20h2v-8h14l-3-5 3-5H6V2H4z"/></svg>';
  return el;
}
function makeTagsMini(tagIds) {
  const wrap = document.createElement('span');
  wrap.className = 'img-tags-mini';
  if (!tagIds || !tagIds.length) return wrap;
  tagIds.slice(0, 4).forEach(tid => {
    const t = projectTagsMap.get(tid);
    if (!t) return;
    const dot = document.createElement('span');
    dot.className = 'img-tag-dot';
    dot.style.background = t.color;
    dot.setAttribute('aria-label', t.name);
    dot.dataset.tooltip = t.name;
    wrap.appendChild(dot);
  });
  if (tagIds.length > 4) {
    const more = document.createElement('span');
    more.style.cssText = 'font-size:0.625rem;color:var(--text-secondary);';
    more.textContent = '+' + (tagIds.length - 4);
    wrap.appendChild(more);
  }
  return wrap;
}
// V8.1.0: локальное обновление статистики изображения после сохранения
// разметки. Раньше был полный loadImages() (сетевой round-trip),
// теперь пересчёт из boxes на клиенте + синхронизация счётчиков.
function _updateImageMeta(imageId) {
  const meta = allImages.find(i => i.id === imageId);
  if (!meta) return;
  const hadAnnotations = (meta.annotation_count || 0) > 0;
  const hasAnnotations = boxes.length > 0;
  meta.annotation_count = boxes.length;
  const confs = boxes.map(b => b.confidence).filter(c => c != null);
  meta.min_confidence = confs.length ? Math.min.apply(null, confs) : null;
  meta.avg_confidence = confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : null;
  meta.low_conf_count = boxes.filter(b => b.confidence != null && b.confidence < 0.5).length;
  // V8.4.0: обновляем список behaviors.
  const behSet = new Set();
  boxes.forEach(b => { if (b.behavior) behSet.add(b.behavior); });
  meta.behaviors = Array.from(behSet).sort();
  // Синхронизация счётчика «размечено» с серверным значением.
  if (viewMode === 'main' && _imagesTotalInProject > 0) {
    if (!hadAnnotations && hasAnnotations) _imagesAnnotatedInProject++;
    else if (hadAnnotations && !hasAnnotations) _imagesAnnotatedInProject = Math.max(0, _imagesAnnotatedInProject - 1);
  }
  _invalidateTagSet(meta);
  _invalidateValidateCache();
  _recomputeCounters();
}

function _refreshRowMeta(imageId, opts = {}) {
  const id = String(imageId);
  const meta = allImages.find(i => i.id === imageId);
  if (!meta) return;
  const row = document.querySelector(`#imageListInner .img-row[data-image-id="${id}"]`);
  if (!row) return;
  _updateRowContent(row, meta);
  if (opts.flash && !prefersReducedMotion()) {
    row.classList.remove('just-updated', 'just-unflagged');
    void row.offsetWidth;
    row.classList.add('just-updated');
    setTimeout(() => row.classList.remove('just-updated', 'just-unflagged'), 800);
  }
}
function _updateRowContent(row, img) {
  if (!row || !img) return;
  if (img._kind === 'project' || img._kind === 'section') return;
  const isTrash = row.classList.contains('trash-row');
  if (!isTrash) {
    const oldStatus = row.querySelector('.img-status');
    if (oldStatus) row.replaceChild(makeStatusDot(img), oldStatus);
    const oldFlag = row.querySelector('.img-hard');
    if (oldFlag) row.replaceChild(makeHardIndicator(!!img.is_hard), oldFlag);
    const oldTags = row.querySelector('.img-tags-mini');
    const hasTags = img.tag_ids && img.tag_ids.length > 0;
    if (oldTags && !hasTags) oldTags.remove();
    else if (oldTags && hasTags) row.replaceChild(makeTagsMini(img.tag_ids), oldTags);
    else if (!oldTags && hasTags) {
      const renameBtn = row.querySelector('.img-rename');
      const newTags = makeTagsMini(img.tag_ids);
      if (renameBtn) row.insertBefore(newTags, renameBtn);
      else row.appendChild(newTags);
    }
  }
  const nameEl = row.querySelector('.img-name');
  if (nameEl && nameEl.textContent !== img.filename) {
    nameEl.textContent = img.filename;
    nameEl.setAttribute('aria-label', img.filename);
    nameEl.dataset.tooltip = img.filename;
  }
  // V8.4.1: точка-индикатор behaviour в строке — обновляем/удаляем.
  const oldBehDot = row.querySelector('.img-beh-dot');
  const behList = img.behaviors || [];
  if (oldBehDot) oldBehDot.remove();
  if (behList.length) {
    const dot = document.createElement('span');
    dot.className = 'img-beh-dot' + (behList.length > 1 ? ' multi' : '');
    if (behList.length === 1) dot.dataset.beh = behList[0];
    const names = behList.map(b => t('behavior.' + b)).join(', ');
    dot.setAttribute('aria-label', names);
    dot.dataset.tooltip = names;
    const nameEl2 = row.querySelector('.img-name');
    const statusDot = row.querySelector('.img-status');
    if (nameEl2) row.insertBefore(dot, nameEl2);
    else if (statusDot) statusDot.after(dot);
    else row.appendChild(dot);
  }

}

/* ===== Sidebar-scroll adapter ===== */
function _listScrollInfo(container) {
  const scroller = container.closest('.sidebar-body') || container;
  if (scroller === container) {
    return { scroller, scrollTop: container.scrollTop, viewH: container.clientHeight || 400 };
  }
  const sRect = scroller.getBoundingClientRect();
  const lRect = container.getBoundingClientRect();
  const scrollTop = Math.max(0, sRect.top - lRect.top);
  const viewH = scroller.clientHeight || 400;
  return { scroller, scrollTop, viewH };
}

/* ===== Virtual scroll + FLIP ===== */
let renderRafPending = false;
let _lastDomIds = new Set();
let _lastRenderStart = -1;
let _lastRenderEnd = -1;

function renderImageList(opts = {}) {
  const container = document.getElementById('imageList');
  const inner = document.getElementById('imageListInner');
  const flip = !!opts.flip;
  const highlights = opts.highlightIds instanceof Set ? opts.highlightIds : null;

  if (!imagesList.length) {
    inner.style.height = 'auto';
    inner.innerHTML = '';
    _lastDomIds = new Set();
    _lastRenderStart = -1; _lastRenderEnd = -1;
    const e = document.createElement('div');
    e.style.cssText = 'padding:20px 8px;font-size:0.8125rem;color:var(--text-secondary);text-align:center;';
    if (viewMode === 'trash') e.textContent = 'Корзина пуста';
    else {
      e.textContent = (activeFilter !== 'none' || activeTagIds.size || searchQuery)
        ? 'Нет изображений по фильтрам' : 'Нет изображений';
    }
    inner.appendChild(e);
    return;
  }

  const totalH = _recomputeRowTops();
  inner.style.height = totalH + 'px';

  const { scrollTop, viewH } = _listScrollInfo(container);
  const overscan = 3;
  const startIdx = Math.max(0, _findRowIndexAtY(scrollTop) - overscan);
  let endIdx;
  for (let i = startIdx; i < imagesList.length; i++) {
    if (_rowTops[i] > scrollTop + viewH) { endIdx = i; break; }
    endIdx = i + 1;
  }
  endIdx = Math.min(imagesList.length, (endIdx || imagesList.length) + overscan);

  if (!flip && startIdx === _lastRenderStart && endIdx === _lastRenderEnd) {
    const cur = String(currentImageId);
    inner.querySelectorAll('.img-row').forEach(r => {
      if (r.classList.contains('section-row')) return;
      const isActive = r.dataset.imageId === cur;
      if (isActive !== r.classList.contains('active')) r.classList.toggle('active', isActive);
    });
    return;
  }
  _lastRenderStart = startIdx; _lastRenderEnd = endIdx;

  const beforePositions = new Map();
  if (flip && !prefersReducedMotion()) {
    inner.querySelectorAll('.img-row').forEach(r => {
      const id = r.dataset.imageId;
      if (id && !r.classList.contains('row-leaving')) beforePositions.set(id, r.getBoundingClientRect().top);
    });
  }

  const prevDomIds = _lastDomIds;
  const newIds = new Set();
  for (let i = startIdx; i < endIdx; i++) newIds.add(_rowKeyOf(imagesList[i]));

  const toRemove = [];
  inner.querySelectorAll('.img-row').forEach(r => {
    const id = r.dataset.imageId;
    if (!id) { r.remove(); return; }
    if (!newIds.has(id)) {
      if (flip) { r.classList.add('row-leaving'); toRemove.push(r); }
      else r.remove();
    }
  });
  if (toRemove.length) setTimeout(() => {
    toRemove.forEach(r => { try { r.remove(); } catch (_) {} });
  }, 200);

  const existing = new Map();
  inner.querySelectorAll('.img-row').forEach(r => {
    const id = r.dataset.imageId;
    if (id && !r.classList.contains('row-leaving')) existing.set(id, r);
  });

  for (let i = startIdx; i < endIdx; i++) {
    const it = imagesList[i];
    const key = _rowKeyOf(it);
    const targetTop = _rowTops[i];
    let row = existing.get(key);

    if (row && it._kind === 'section') {
      _updateSectionRow(row, it);
      row.dataset.index = i;
      row.style.top = targetTop + 'px';
      continue;
    }
    if (!row) {
      // V7.8.3: _rowCache удалён. Кэшем служит сама DOM-карта existing,
      // вычисленная выше из inner.querySelectorAll('.img-row').
      if (it._kind === 'section') row = makeSectionRow(it, i);
      else if (viewMode === 'trash' && it._kind === 'project') row = makeProjectTrashRow(it, i);
      else if (viewMode === 'trash') row = makeTrashRow(it, i);
      else row = makeMainRow(it, i);
      row.style.top = targetTop + 'px';
      if (flip && !prevDomIds.has(key) && !prefersReducedMotion()) {
        row.classList.add('row-entering');
        const visibleIndex = i - startIdx;
        row.style.animationDelay = Math.min(visibleIndex * 10, 200) + 'ms';
        setTimeout(() => { row.classList.remove('row-entering'); row.style.animationDelay = ''; }, 260);
      }
      if (highlights && highlights.has(it.id)) row.classList.add('just-highlighted');
      inner.appendChild(row);
    } else {
      row.dataset.index = i;
      row.style.top = targetTop + 'px';
      row.classList.toggle('active', it.id === currentImageId && !it._kind);
      const cb = row.querySelector('.img-check');
      if (cb) cb.checked = selectedForDelete.has(it.id);
      _updateRowContent(row, it);
    }
  }

  if (beforePositions.size && !prefersReducedMotion()) {
    inner.querySelectorAll('.img-row').forEach(r => {
      const id = r.dataset.imageId;
      if (!id || r.classList.contains('row-entering') || r.classList.contains('row-leaving')) return;
      const oldTop = beforePositions.get(id);
      if (oldTop == null) return;
      const newTop = r.getBoundingClientRect().top;
      const delta = oldTop - newTop;
      if (Math.abs(delta) < 0.5) return;
      try {
        r.animate(
          [{ transform: `translateY(${delta}px)` }, { transform: 'translateY(0)' }],
          { duration: 240, easing: 'cubic-bezier(0.2, 0, 0, 1)', fill: 'none' }
        );
      } catch (err) {}
    });
  }
  _lastDomIds = newIds;
}

function makeSectionRow(item, index) {
  const row = document.createElement('div');
  row.className = 'img-row section-row';
  row.dataset.imageId = 's' + item.sectionKey;
  row.dataset.index = index;
  row.dataset.sectionKey = item.sectionKey;
  row.setAttribute('role', 'button');
  row.setAttribute('tabindex', '0');
  _updateSectionRow(row, item);
  row.addEventListener('click', (e) => { e.stopPropagation(); toggleSection(item.sectionKey); });
  onActivate(row, () => toggleSection(item.sectionKey), { stop: true });
  return row;
}
function _updateSectionRow(row, item) {
  if (!row || !item) return;
  row.classList.toggle('all-done', !!item.allDone);
  row.setAttribute('aria-expanded', _collapsedSections[item.sectionKey] ? 'false' : 'true');
  row.innerHTML = '';
  const arrow = document.createElement('span');
  arrow.className = 'section-arrow';
  arrow.setAttribute('aria-hidden', 'true');
  arrow.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
  if (_collapsedSections[item.sectionKey]) arrow.style.transform = 'rotate(-90deg)';
  row.appendChild(arrow);
  const title = document.createElement('span');
  title.className = 'section-title';
  title.textContent = item.allDone ? '✓ ' + t('section.un.allDone') : item.title;
  row.appendChild(title);
  const count = document.createElement('span');
  count.className = 'section-count';
  count.textContent = item.count;
  row.appendChild(count);
}

function makeMainRow(img, index) {
  const row = document.createElement('div');
  row.className = 'img-row';
  row.dataset.imageId = img.id;
  row.dataset.index = index;
  row.setAttribute('role', 'option');
  if (img.id === currentImageId) row.classList.add('active');
  row.addEventListener('click', (e) => {
    if (e.target.closest('.img-check')) return;
    if (e.target.closest('.img-action')) return;
    if (e.target.closest('.trash-actions')) return;
    selectImage(img.id);
  });
  const check = document.createElement('input');
  check.type = 'checkbox';
  check.className = 'img-check';
  check.checked = selectedForDelete.has(img.id);
  check.setAttribute('aria-label', `Выбрать ${img.filename}`);
  check.addEventListener('click', e => e.stopPropagation());
  check.addEventListener('change', () => {
    if (check.checked) selectedForDelete.add(img.id); else selectedForDelete.delete(img.id);
    updateBulkBar(); updateSelectAllCheck(); renderTagChips();
    haptic('selection');
  });
  row.appendChild(check);
  const thumb = document.createElement('img');
  thumb.className = 'img-thumb';
  thumb.loading = 'lazy';
  thumb.alt = '';
  thumb.src = `/api/images/${img.id}/thumb`;
  // V8.3.1: placeholder для битых миниатюр.
  thumb.onerror = () => {
    thumb.onerror = null;
    thumb.style.background = 'rgba(255,59,48,0.15)';
    thumb.removeAttribute('src');
    thumb.dataset.tooltip = 'Файл отсутствует';
  };
  row.appendChild(thumb);
  row.appendChild(makeStatusDot(img));
  row.appendChild(makeHardIndicator(!!img.is_hard));
  // V8.4.0: точка-индикатор behaviour.
  const behList = img.behaviors || [];
  if (behList.length) {
    const dot = document.createElement('span');
    dot.className = 'img-beh-dot' + (behList.length > 1 ? ' multi' : '');
    if (behList.length === 1) dot.dataset.beh = behList[0];
    const names = behList.map(b => t('behavior.' + b)).join(', ');
    dot.setAttribute('aria-label', names);
    dot.dataset.tooltip = names;
    row.appendChild(dot);
  }
  const name = document.createElement('span');
  name.className = 'img-name';
  name.textContent = img.filename;
  name.setAttribute('aria-label', img.filename);
  name.dataset.tooltip = img.filename;
  row.appendChild(name);
  if (img.tag_ids && img.tag_ids.length) row.appendChild(makeTagsMini(img.tag_ids));
  const rename = document.createElement('span');
  rename.className = 'img-action img-rename';
  rename.setAttribute('role', 'button');
  rename.setAttribute('tabindex', '0');
  rename.setAttribute('aria-label', `Переименовать ${img.filename}`);
  rename.dataset.tooltip = 'Переименовать';
  rename.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>';
  rename.onclick = (e) => { e.stopPropagation(); renameImage(img.id, img.filename); };
  onActivate(rename, () => renameImage(img.id, img.filename), { stop: true });
  row.appendChild(rename);
  // V8.1.0: «Показать на диске»
  const reveal = document.createElement('span');
  reveal.className = 'img-action img-reveal';
  reveal.setAttribute('role', 'button');
  reveal.setAttribute('tabindex', '0');
  reveal.setAttribute('aria-label', `Показать ${img.filename} на диске`);
  reveal.dataset.tooltip = 'Показать на диске';
  reveal.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><use href="#i-folder"/></svg>';
  reveal.onclick = async (e) => {
    e.stopPropagation();
    try { await api(`/api/images/${img.id}/reveal`, { method: 'POST' }); }
    catch (err) { setError('Проводник: ' + String(err.message).slice(0, 120)); }
  };
  onActivate(reveal, () => reveal.click(), { stop: true });
  row.appendChild(reveal);
  const del = document.createElement('span');
  del.className = 'img-action img-del';
  del.setAttribute('role', 'button');
  del.setAttribute('tabindex', '0');
  del.setAttribute('aria-label', `Удалить ${img.filename}`);
  del.dataset.tooltip = 'Удалить';
  del.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
  del.onclick = (e) => { e.stopPropagation(); deleteImage(img.id, img.filename); };
  onActivate(del, () => deleteImage(img.id, img.filename), { stop: true });
  row.appendChild(del);
  _makeRowDraggable(row, img);
  return row;
}
// V8.1.0: drag-n-drop строк списка между проектами.
function _makeRowDraggable(row, img) {
  if (!img || img._kind) return;
  row.draggable = true;
  row.addEventListener('dragstart', (e) => {
    const ids = selectedForDelete.has(img.id)
      ? Array.from(selectedForDelete)
      : [img.id];
    e.dataTransfer.setData('application/x-pdb-images', JSON.stringify(ids));
    e.dataTransfer.effectAllowed = 'move';
  });
}

function makeTrashRow(img, index) {
  const row = document.createElement('div');
  row.className = 'img-row trash-row';
  row.dataset.imageId = img.id;
  row.dataset.index = index;
  row.dataset.kind = 'image';
  row.setAttribute('role', 'button');
  row.setAttribute('tabindex', '0');
  const check = document.createElement('input');
  check.type = 'checkbox';
  check.className = 'img-check';
  check.checked = selectedForDelete.has(img.id);
  check.setAttribute('aria-label', `Выбрать ${img.filename}`);
  check.addEventListener('click', e => e.stopPropagation());
  check.addEventListener('change', () => {
    if (check.checked) selectedForDelete.add(img.id); else selectedForDelete.delete(img.id);
    updateTrashBar(); updateSelectAllCheck(); haptic('selection');
  });
  row.appendChild(check);
  const thumb = document.createElement('img');
  thumb.className = 'img-thumb';
  thumb.loading = 'lazy';
  thumb.alt = '';
  thumb.src = `/api/images/${img.id}/thumb`;
  row.appendChild(thumb);
  const name = document.createElement('span');
  name.className = 'img-name';
  name.textContent = img.filename;
  row.appendChild(name);
  if (img.days_left != null) {
    const days = document.createElement('span');
    days.className = 'img-days';
    days.textContent = img.days_left <= 0 ? 'истекает' : `${img.days_left} дн.`;
    row.appendChild(days);
  }
  const actions = document.createElement('div');
  actions.className = 'trash-actions';
  const restore = document.createElement('button');
  restore.className = 'trash-act restore';
  restore.setAttribute('aria-label', 'Восстановить');
  restore.dataset.tooltip = 'Восстановить';
  restore.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>';
  restore.onclick = (e) => { e.stopPropagation(); restoreImage(img.id); };
  actions.appendChild(restore);
  const perm = document.createElement('button');
  perm.className = 'trash-act perm-del';
  perm.setAttribute('aria-label', 'Удалить навсегда');
  perm.dataset.tooltip = 'Удалить навсегда';
  perm.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
  perm.onclick = (e) => { e.stopPropagation(); permanentDelete(img.id, img.filename); };
  actions.appendChild(perm);
  row.appendChild(actions);
  row.onclick = (e) => {
    if (e.target.closest('.trash-actions')) return;
    if (e.target.classList.contains('img-check')) return;
    openPreview(img.id, img.filename, img.days_left);
  };
  onActivate(row, () => openPreview(img.id, img.filename, img.days_left));
  return row;
}
function makeProjectTrashRow(item, index) {
  const row = document.createElement('div');
  row.className = 'img-row trash-row project-row';
  row.dataset.imageId = 'p' + item.id;
  row.dataset.index = index;
  row.dataset.kind = 'project';
  row.setAttribute('role', 'button');
  row.setAttribute('tabindex', '0');
  const icon = document.createElement('span');
  icon.className = 'img-project-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.innerHTML = '<svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';
  row.appendChild(icon);
  const name = document.createElement('span');
  name.className = 'img-name';
  name.textContent = item.name;
  name.setAttribute('aria-label', `Проект ${item.name}`);
  row.appendChild(name);
  const cnt = document.createElement('span');
  cnt.className = 'img-days';
  cnt.textContent = `${item.images_count} фото`;
  row.appendChild(cnt);
  if (item.days_left != null) {
    const days = document.createElement('span');
    days.className = 'img-days';
    days.textContent = item.days_left <= 0 ? 'истекает' : `${item.days_left} дн.`;
    row.appendChild(days);
  }
  const actions = document.createElement('div');
  actions.className = 'trash-actions';
  const restore = document.createElement('button');
  restore.className = 'trash-act restore';
  restore.setAttribute('aria-label', `Восстановить проект «${item.name}»`);
  restore.dataset.tooltip = 'Восстановить';
  restore.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>';
  restore.onclick = (e) => { e.stopPropagation(); restoreProject(item.id); };
  actions.appendChild(restore);
  const perm = document.createElement('button');
  perm.className = 'trash-act perm-del';
  perm.setAttribute('aria-label', `Удалить проект «${item.name}» навсегда`);
  perm.dataset.tooltip = 'Удалить навсегда';
  perm.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
  perm.onclick = (e) => { e.stopPropagation(); permanentDeleteProject(item.id, item.name); };
  actions.appendChild(perm);
  row.appendChild(actions);
  return row;
}

function onListScroll() {
  if (renderRafPending) return;
  renderRafPending = true;
  requestAnimationFrame(() => {
    renderRafPending = false;
    renderImageList();
    _maybeLoadMoreImages();
  });
}

// V7.9.3: если пользователь близко к концу — тянем следующую страницу
function _maybeLoadMoreImages() {
  if (!_imagesHasMore || _imagesLoadingMore) return;
  if (viewMode !== 'main') return;
  const container = document.getElementById('imageList');
  if (!container) return;
  const info = _listScrollInfo(container);
  if (!_rowTops.length) return;
  const lastTop = _rowTops[_rowTops.length - 1] || 0;
  const lastH = _rowH(imagesList[imagesList.length - 1] || {});
  const totalH = lastTop + lastH;
  const bottom = info.scrollTop + info.viewH;
  if (totalH - bottom < ROW_H * 30) loadMoreImages();
}
function scrollListToImage(id) {
  const idx = imagesList.findIndex(x => x.id === id && _isImageItem(x));
  if (idx < 0) return;
  const container = document.getElementById('imageList');
  const scroller = container.closest('.sidebar-body') || container;
  const viewH = scroller.clientHeight || 400;
  const rowTop = _rowTops[idx] != null ? _rowTops[idx] : 0;
  const rowH = _rowH(imagesList[idx]);

  if (scroller === container) {
    const target = Math.max(0, rowTop - viewH / 2 + rowH / 2);
    container.scrollTop = target;
    return;
  }

  const sRect = scroller.getBoundingClientRect();
  const lRect = container.getBoundingClientRect();
  const sectionOffset = scroller.scrollTop + (lRect.top - sRect.top);
  const target = sectionOffset + rowTop - viewH / 2 + rowH / 2;
  scroller.scrollTop = Math.max(0, target);
}

/* ===== Progress / bars ===== */
function updateProgress() {
  if (viewMode !== 'main') { _updateTitleProgress(); return; }
  const total = _totalCount;
  const done = _annotatedCount;
  const block = document.getElementById('progressBlock');
  if (block) block.classList.toggle('hidden', total === 0);
  const pct = total ? Math.round(done / total * 100) : 0;
  const bar = document.getElementById('progressBar');
  if (bar) bar.setAttribute('aria-valuenow', String(pct));
  animateNumber(document.getElementById('progressText'), `${done} / ${total}`);
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressLabel').textContent = t('sidebar.images.progress');
  document.getElementById('progressFill').classList.remove('batch');
  _updateTitleProgress();
}
function updateBulkBar() {
  const bar = document.getElementById('bulkBar');
  const n = selectedForDelete.size;
  if (n > 0 && viewMode === 'main') {
    bar.classList.add('open');
    document.getElementById('bulkCount').textContent =
      `${n} ${pluralImages(n)} ${t('sidebar.images.bulk.selected')}`;
  } else bar.classList.remove('open');
  updateBulkTagBtn();
}
function updateTrashBar() {
  const bar = document.getElementById('trashBar');
  const n = selectedForDelete.size;
  if (n > 0 && viewMode === 'trash') {
    bar.classList.add('open');
    document.getElementById('trashCount').textContent =
      `${n} ${pluralImages(n)} ${t('sidebar.images.bulk.selected')}`;
  } else bar.classList.remove('open');
}
function updateTrashActionsBar() {
  if (viewMode !== 'trash') return;
  const el = document.getElementById('trashTotal');
  const btn = document.getElementById('emptyTrashBtn');
  if (!el) return;
  const projCount = allImages.filter(x => x._kind === 'project').length;
  const imgCount = allImages.filter(x => x._kind !== 'project').length;
  if (!allImages.length) {
    el.textContent = 'Корзина пуста';
    if (btn) btn.style.display = 'none';
  } else {
    const parts = [];
    if (projCount) parts.push(`${projCount} ${pluralProjects(projCount)}`);
    if (imgCount) parts.push(`${imgCount} ${pluralImages(imgCount)}`);
    el.textContent = parts.join(' · ') + ' в корзине';
    if (btn) btn.style.display = '';
  }
}
function updateSelectAllCheck() {
  const check = document.getElementById('selectAllCheck');
  if (!check) return;
  if (viewMode === 'trash') {
    check.checked = false; check.indeterminate = false; check.disabled = true;
    return;
  }
  const imgItems = imagesList.filter(_isImageItem);
  if (!imgItems.length) {
    check.checked = false; check.indeterminate = false; check.disabled = true; return;
  }
  check.disabled = false;
  const total = imgItems.length;
  const selected = imgItems.filter(i => selectedForDelete.has(i.id)).length;
  check.checked = selected === total && total > 0;
  check.indeterminate = selected > 0 && selected < total;
}
function toggleSelectAll() {
  if (viewMode === 'trash') return;
  const check = document.getElementById('selectAllCheck');
  const ids = imagesList.filter(_isImageItem).map(i => i.id);
  if (check.checked) ids.forEach(id => selectedForDelete.add(id));
  else ids.forEach(id => selectedForDelete.delete(id));
  renderImageList();
  updateBulkBar(); updateTrashBar(); updateSelectAllCheck(); renderTagChips();
  haptic('selection');
}
function clearSelection() {
  selectedForDelete.clear();
  renderImageList();
  updateBulkBar(); updateTrashBar(); updateSelectAllCheck(); renderTagChips();
}
function updateFilterBadge() {
  const badge = document.getElementById('filterBadge');
  const btn = document.getElementById('filterBtn');
  const n = (activeFilter !== 'none' ? 1 : 0) + activeTagIds.size;
  if (n > 0) { badge.style.display = 'block'; badge.textContent = String(n); btn.classList.add('active'); }
  else { badge.style.display = 'none'; btn.classList.remove('active'); }
}
/* ===================================================================
   V8.3.0: панель атрибутов (поведение + номер животного)
   =================================================================== */
let _currentBehavior = null;
let _currentAnimalId = null;

function _getAttrTargets() {
  // V8.3.1: работаем ТОЛЬКО с выделенными рамками.
  // Если ничего не выделено — пусто, панель выдаст подсказку.
  return getSelectedIndices();
}

function _refreshAttrBar() {
  const bar = document.getElementById('attrBar');
  if (!bar) return;
  if (!currentImageId) { bar.style.display = 'none'; return; }
  bar.style.display = '';
  const sel = getSelectedIndices();
  // V8.6.8: панель всегда активна — 🧠 авто работает без выделения.
  const counter = document.getElementById('attrCounter');
  if (counter) {
    counter.textContent = sel.length
      ? `выделено: ${sel.length}`
      : 'выдели рамку';
  }
  const targets = sel.length ? sel : [];
  // Значения — из выделенных (если одинаковые), иначе из первой рамки.
  let beh = null, aid = null;
  if (targets.length) {
    const first = boxes[targets[0]] || {};
    beh = first.behavior || null;
    aid = (first.animal_id != null) ? first.animal_id : null;
    const same = targets.every(i => (boxes[i].behavior || null) === beh &&
                                    (boxes[i].animal_id ?? null) === aid);
    if (!same) { beh = null; aid = null; }
  }
  _currentBehavior = beh;
  _currentAnimalId = aid;
  bar.querySelectorAll('.beh-btn[data-beh]').forEach(b => {
    const isActive = b.dataset.beh && b.dataset.beh === beh;
    b.classList.toggle('active', isActive);
  });
  const inp = document.getElementById('animalIdInput');
  if (inp) inp.value = (aid != null) ? String(aid) : '';
  // Тайминг
  const tmWrap = document.getElementById('attrTiming');
  const tmVal = document.getElementById('attrTimingValue');
  const meta = allImages.find(i => i.id === currentImageId);
  if (meta && meta.timestamp_sec != null) {
    const sec = meta.timestamp_sec;
    const mm = String(Math.floor(sec / 60)).padStart(2, '0');
    const ss = String(Math.floor(sec % 60)).padStart(2, '0');
    const ms = String(Math.floor((sec % 1) * 10));
    tmVal.textContent = `${mm}:${ss}.${ms}`;
    if (meta.frame_index != null) tmVal.textContent += ` (кадр ${meta.frame_index})`;
    tmWrap.style.display = '';
  } else {
    tmWrap.style.display = 'none';
  }
}

function _applyBehaviorToTargets(beh) {
  const idx = _getAttrTargets();
  if (!idx.length) {
    setStatus('Сначала выдели рамку', 2500);
    haptic('warning');
    return;
  }
  idx.forEach(i => { boxes[i].behavior = beh || null; });
  renderBoxes();
  pushHistory();
  markDirty();
  _refreshAttrBar();
  setStatus(beh ? `${t('attr.behavior')}: ${t('behavior.' + beh)}` : 'Поведение сброшено', 2000);
  haptic('selection');
}

function _applyAnimalIdToTargets(aid) {
  const idx = _getAttrTargets();
  if (!idx.length) {
    setStatus('Сначала выдели рамку', 2500);
    haptic('warning');
    return;
  }
  idx.forEach(i => { boxes[i].animal_id = (aid != null) ? aid : null; });
  renderBoxes();
  pushHistory();
  markDirty();
  _refreshAttrBar();
  setStatus(aid != null ? `${t('attr.animalId')}: ${aid}` : 'Номер сброшен', 2000);
  haptic('selection');
}

async function _assignNextAnimalId() {
  // V8.4.0: взять следующий свободный номер и присвоить выделенным.
  if (!currentProjectId) return;
  const idx = _getAttrTargets();
  if (!idx.length) {
    setStatus('Сначала выдели рамку', 2500);
    haptic('warning');
    return;
  }
  try {
    const r = await api(`/api/projects/${currentProjectId}/next_animal_id`);
    _applyAnimalIdToTargets(r.next);
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}

function _applyAllToPhoto() {
  // V8.4.0: применить текущие значения панели ко ВСЕМ рамкам фото.
  if (!boxes.length) { setStatus('На фото нет рамок', 2500); return; }
  const beh = _currentBehavior;
  const aid = _currentAnimalId;
  if (!beh && aid == null) {
    setStatus('Сначала выбери поведение или задай номер', 3000);
    haptic('warning');
    return;
  }
  boxes.forEach(b => {
    if (beh) b.behavior = beh;
    if (aid != null) b.animal_id = aid;
  });
  renderBoxes();
  pushHistory();
  markDirty();
  _refreshAttrBar();
  setStatus(`Применено ко всем рамкам (${boxes.length})`, 2500);
  haptic('success');
}

// V8.6.0 (M2.4): запросить у сервера предсказание поведения.
async function _autoDetectBehavior() {
  if (!currentImageId) return;
  if (!boxes.length) {
    setStatus(t('attr.predictBehavior.noBoxes'), 2500);
    haptic('warning');
    return;
  }
  // V8.8.6: параллельные запросы вместо последовательного цикла.
  const targets = [];
  for (let i = 0; i < boxes.length; i++) {
    if (!boxes[i].behavior) targets.push(i);
  }
  if (!targets.length) {
    setStatus(t('attr.predictBehavior.allSet'), 2500);
    haptic('warning');
    return;
  }

  // Подготовка payload-ов
  const jobs = [];
  const reasons = {};
  for (const i of targets) {
    const box = boxes[i];
    let kps = [];
    if (Array.isArray(box.keypoints) && box.keypoints.length) {
      kps = box.keypoints;
    } else if (window._kpByIndex && Array.isArray(window._kpByIndex[String(i)])
               && window._kpByIndex[String(i)].length) {
      kps = window._kpByIndex[String(i)];
      box.keypoints = kps.map(p => ({...p}));
    }
    if (!kps.length) {
      reasons['no_kp'] = (reasons['no_kp'] || 0) + 1;
      continue;
    }
    jobs.push({ i, kps, box });
  }

  let applied = 0;
  let skipped = targets.length - jobs.length;
  // Параллельно
  await Promise.all(jobs.map(async (job) => {
    try {
      const r = await api(`/api/images/${currentImageId}/predict_behavior`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keypoints: job.kps,
          animal_id: (job.box.animal_id != null) ? job.box.animal_id : null,
        }),
      });
      if (r && r.behavior) {
        job.box.behavior = r.behavior;
        applied++;
      } else {
        skipped++;
        const why = (r && r.reason) || 'unknown';
        const short = why.split(' ')[0].split('(')[0].trim();
        reasons[short] = (reasons[short] || 0) + 1;
      }
    } catch (e) {
      skipped++;
      reasons['http_error'] = (reasons['http_error'] || 0) + 1;
    }
  }));

  if (applied) {
    renderBoxes();
    pushHistory();
    markDirty();
    _refreshAttrBar();
    try {
      _updateImageMeta(currentImageId);
      _refreshRowMeta(currentImageId, { flash: true });
    } catch (e) {}
    setStatus(t('attr.predictBehavior.appliedAll', { n: applied, s: skipped }), 4000);
    haptic('success');
  } else {
    const rk = Object.keys(reasons);
    let msg = t('attr.predictBehavior.none');
    if (rk.length) msg += ' [' + rk.map(k => k + '×' + reasons[k]).join(', ') + ']';
    setStatus(msg, 6000);
    haptic('warning');
  }
}




// V8.6.9: копирование скелета из похожего кадра.
async function _copySkeletonFromSimilar() {
  if (!currentImageId) return;
  // Находим похожие кадры с скелетом.
  let data;
  try {
    data = await api(`/api/images/${currentImageId}/similar_with_skeleton`);
  } catch (e) {
    setError(t('attr.skelFromSimilar.error') + ': ' + String(e.message).slice(0, 120));
    return;
  }
  const items = (data && data.items) || [];
  if (!items.length) {
    setStatus(t('attr.skelFromSimilar.none'), 4000);
    haptic('warning');
    return;
  }
  // Если один — сразу копируем.
  if (items.length === 1) {
    await _doCopySkeleton(items[0].id, items[0].filename);
    return;
  }
  // Иначе — диалог выбора источника.
  const chosen = await _pickSkeletonSource(items);
  if (!chosen) return;
  await _doCopySkeleton(chosen.id, chosen.filename);
}

async function _doCopySkeleton(sourceId, sourceName) {
  setStatus(t('attr.skelFromSimilar.copying', { name: sourceName }), 60000);
  try {
    const r = await api(`/api/images/${currentImageId}/copy_skeleton_from/${sourceId}`, {
      method: 'POST',
    });
    if (!r.matched_boxes || !r.matched_boxes.length) {
      setStatus(t('attr.skelFromSimilar.noMatch', { name: sourceName }), 4000);
      haptic('warning');
      return;
    }
    // V8.6.10: сначала тянем _kpByIndex, потом РАСКЛАДЫВАЕМ по boxes.
    try {
      const rows = await api(`/api/images/${currentImageId}/keypoints_by_index`);
      window._kpByIndex = rows || {};
      boxes.forEach((b, bi) => {
        const k = window._kpByIndex[String(bi)];
        b.keypoints = Array.isArray(k) ? k.map(p => ({...p})) : [];
      });
      const selIdx = _targetAnnotationId();
      if (selIdx >= 0 && Array.isArray(boxes[selIdx].keypoints)) {
        keypoints = boxes[selIdx].keypoints.map(p => ({...p}));
      }
    } catch (e) { console.warn('reload after copy failed:', e); }
    renderBoxes();
    pushHistory();
    markDirty();
    setStatus(t('attr.skelFromSimilar.done', {
      name: sourceName,
      boxes: r.matched_boxes.length,
      kp: r.copied_kp,
      skipped: r.skipped,
    }), 5000);
    haptic('success');
    // V8.6.12: автоматически определяем поведение по скопированному скелету.
    try {
      await _autoDetectBehavior();
      _updateImageMeta(currentImageId);
      _refreshRowMeta(currentImageId, { flash: true });
    } catch (e) { console.warn('auto after copy failed:', e); }
  } catch (e) {
    setError(t('attr.skelFromSimilar.error') + ': ' + String(e.message).slice(0, 160));
  }
}

function _pickSkeletonSource(items) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;flex-direction:column;gap:8px;max-height:340px;overflow-y:auto;';
    const previews = [];
    items.forEach((it, idx) => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:6px;border-radius:10px;cursor:pointer;transition:background-color 120ms;';
      row.onmouseenter = () => { row.style.background = 'var(--bg-hover)'; };
      row.onmouseleave = () => { row.style.background = 'transparent'; };
      const img = document.createElement('img');
      img.src = `/api/images/${it.id}/thumb`;
      img.alt = '';
      img.style.cssText = 'width:52px;height:52px;border-radius:8px;object-fit:cover;background:var(--bg-canvas);border:1px solid var(--hairline);flex:none;';
      row.appendChild(img);
      const info = document.createElement('div');
      info.style.cssText = 'flex:1;min-width:0;';
      const nm = document.createElement('div');
      nm.style.cssText = 'font-weight:600;font-size:0.8125rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      nm.textContent = it.filename;
      info.appendChild(nm);
      const meta = document.createElement('div');
      meta.style.cssText = 'font-size:0.6875rem;color:var(--text-secondary);margin-top:2px;';
      meta.textContent = `Hamming ${it.distance} · скелетов: ${it.skeleton_count}`;
      info.appendChild(meta);
      row.appendChild(info);
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'skel_source_pick';
      radio.style.cssText = 'flex:none;margin-right:6px;';
      if (idx === 0) radio.checked = true;
      row.appendChild(radio);
      previews.push({ it, radio });
      row.onclick = () => { previews.forEach(p => p.radio.checked = false); radio.checked = true; };
      wrap.appendChild(row);
    });
    _openCustomDialog({
      title: t('attr.skelFromSimilar.pickTitle'),
      bodyText: t('attr.skelFromSimilar.pickHint'),
      selectorEl: wrap,
      okText: t('attr.skelFromSimilar.pickOk'),
    }).then((res) => {
      if (!res) { resolve(null); return; }
      const chosen = previews.find(p => p.radio.checked);
      resolve(chosen ? chosen.it : null);
    });
  });
}

// V8.7.1: авто-разметка скелета через pose-модель.
async function _autoSkeletonPose() {
  if (!currentImageId) return;
  if (!boxes.length) {
    setStatus(t('attr.skelPose.noBoxes'), 2500);
    haptic('warning');
    return;
  }
  setStatus(t('attr.skelPose.running'), 60000);
  try {
    const r = await api(`/api/images/${currentImageId}/autolabel_pose`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ only_empty: true, iou_threshold: 0.30, conf: 0.25 }),
    });
    if (!r || !r.saved_annotations) {
      setStatus(t('attr.skelPose.nothing'), 4000);
      haptic('warning');
      return;
    }
    // Перезагружаем keypoints с сервера.
    try {
      const rows = await api(`/api/images/${currentImageId}/keypoints_by_index`);
      window._kpByIndex = rows || {};
      boxes.forEach((b, bi) => {
        const k = window._kpByIndex[String(bi)];
        b.keypoints = Array.isArray(k) ? k.map(p => ({...p})) : [];
      });
      const selIdx = _targetAnnotationId();
      if (selIdx >= 0 && Array.isArray(boxes[selIdx].keypoints)) {
        keypoints = boxes[selIdx].keypoints.map(p => ({...p}));
      }
    } catch (e) { console.warn('reload after pose failed:', e); }
    renderBoxes();
    pushHistory();
    markDirty();
    setStatus(t('attr.skelPose.done', {
      boxes: r.saved_annotations, kp: r.saved_keypoints,
      skipped: r.skipped_existing,
    }), 5000);
    haptic('success');
    // Автоматически определяем поведение (как в 🦴 из похожего).
    try {
      await _autoDetectBehavior();
      _updateImageMeta(currentImageId);
      _refreshRowMeta(currentImageId, { flash: true });
    } catch (e) { console.warn('auto behavior after pose failed:', e); }
  } catch (e) {
    setStatus(t('attr.skelPose.error') + ': ' + String(e.message || e).slice(0, 160), 6000);
    haptic('error');
  }
}

// V8.8.0: трекинг по видео.
let _trackEventSource = null;

async function _startTracking() {
  if (!currentImageId) return;
  const meta = allImages.find(i => i.id === currentImageId);
  if (!meta || !meta.video_id) {
    setStatus(t('attr.track.noVideo'), 3000);
    haptic('warning');
    return;
  }
  const videoId = meta.video_id;
  try {
    const r = await api('/api/videos/' + videoId + '/track', { method: 'POST' });
    if (!r || r.status !== 'started') {
      setStatus(t('attr.track.startFailed'), 3000);
      return;
    }
    setStatus(t('attr.track.running', { total: r.total }), 0);
    _subscribeTrackEvents(videoId);
    haptic('success');
  } catch (e) {
    setStatus(t('attr.track.error') + ': ' + String(e.message || e).slice(0, 160), 6000);
    haptic('error');
  }
}

function _subscribeTrackEvents(videoId) {
  if (_trackEventSource) { try { _trackEventSource.close(); } catch (e) {} }
  const es = new EventSource('/api/videos/' + videoId + '/track/events');
  _trackEventSource = es;
  es.onmessage = (ev) => {
    let s;
    try { s = JSON.parse(ev.data); } catch (e) { return; }
    const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
    if (s.status === 'running') {
      setStatus(t('attr.track.progress', {
        done: s.done, total: s.total, tracks: s.tracks, pct: pct,
      }), 0);
      return;
    }
    es.close();
    _trackEventSource = null;
    if (s.status === 'done') {
      setStatus(t('attr.track.done', {
        tracks: s.tracks, assignments: s.assignments,
      }), 6000);
      haptic('success');
      // Обновляем список кадров и текущий кадр.
      loadImages();
      if (currentImageId) {
        api('/api/images/' + currentImageId + '/annotations')
          .then(anns => { boxes = anns || []; renderBoxes(); })
          .catch(() => {});
      }
    } else if (s.status === 'stopped') {
      setStatus(t('attr.track.stopped'), 4000);
    } else {
      setStatus(t('attr.track.error') + ': ' + (s.message || ''), 6000);
      haptic('error');
    }
  };
  es.onerror = () => { try { es.close(); } catch (e) {} _trackEventSource = null; };
}

// V8.8.1: работа с треками.
async function _linkFromPrev() {
  if (!currentImageId) return;
  try {
    const r = await api(`/api/images/${currentImageId}/link_from_prev`, { method: 'POST' });
    if (!r || !r.linked) {
      const reasons = {
        no_prev_frame: t('attr.linkPrev.noPrev'),
        no_aid_on_prev: t('attr.linkPrev.noAid'),
      };
      setStatus(reasons[r && r.reason] || t('attr.linkPrev.nothing'), 3500);
      haptic('warning');
      return;
    }
    // Обновляем аннотации с сервера
    try {
      boxes = await api(`/api/images/${currentImageId}/annotations`);
    } catch (e) {}
    renderBoxes();
    pushHistory();
    markDirty();
    _refreshAttrBar();
    setStatus(t('attr.linkPrev.linked', { n: r.linked }), 3000);
    haptic('success');
  } catch (e) {
    setStatus(t('attr.linkPrev.error') + ': ' + String(e.message || e).slice(0, 140), 6000);
    haptic('error');
  }
}

// Навигация Alt+←/→ по треку.
async function _navigateWithAid(dir) {
  if (!currentImageId || !currentProjectId) return;
  // Берём animal_id текущей выделенной рамки (или первой попавшейся с ID).
  let aid = null;
  const sel = getSelectedIndices();
  if (sel.length) {
    const a = boxes[sel[0]];
    if (a && a.animal_id != null) aid = a.animal_id;
  }
  if (aid == null) {
    for (const b of boxes) {
      if (b.animal_id != null) { aid = b.animal_id; break; }
    }
  }
  if (aid == null) {
    setStatus(t('attr.linkPrev.noAid'), 2500);
    return;
  }
  try {
    const r = await api(
      `/api/projects/${currentProjectId}/navigate_with_aid?`
      + `from_image_id=${currentImageId}&animal_id=${aid}&dir=${dir}`
    );
    if (!r.found) {
      const reasons = {
        no_video: t('attr.linkPrev.noPrev'),
        end_of_track: t('attr.linkPrev.endOfTrack'),
      };
      setStatus(reasons[r.reason] || t('attr.linkPrev.nothing'), 2500);
      return;
    }
    await selectImage(r.image_id, { skipDirtyCheck: false });
  } catch (e) {
    console.warn('navigate_with_aid:', e);
  }
}

async function openTracksModal() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const body = document.getElementById('tracksBody');
  body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;">'
                  + t('common.loading') + '</p>';
  openModal('tracksModal');
  try {
    const r = await api(`/api/projects/${currentProjectId}/tracks`);
    body.innerHTML = '';
    if (!r.items || !r.items.length) {
      body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;text-align:center;padding:24px 0;">'
                     + t('tracks.empty') + '</p>';
      return;
    }
    r.items.forEach(it => {
      const row = document.createElement('div');
      row.className = 'track-row';
      row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px;border-radius:10px;cursor:pointer;transition:background-color 120ms;';
      row.onmouseenter = () => { row.style.background = 'var(--bg-hover)'; };
      row.onmouseleave = () => { row.style.background = 'transparent'; };
      const img = document.createElement('img');
      img.loading = 'lazy';
      img.alt = '';
      img.src = `/api/images/${it.first_image_id}/thumb`;
      img.style.cssText = 'width:52px;height:52px;border-radius:8px;object-fit:cover;background:var(--bg-canvas);border:1px solid var(--hairline);flex:none;';
      row.appendChild(img);
      const info = document.createElement('div');
      info.style.cssText = 'flex:1;min-width:0;';
      const name = document.createElement('div');
      name.style.cssText = 'font-weight:600;font-size:0.8125rem;';
      name.textContent = '#' + it.animal_id;
      info.appendChild(name);
      const meta = document.createElement('div');
      meta.style.cssText = 'font-size:0.6875rem;color:var(--text-secondary);margin-top:2px;';
      meta.textContent = t('tracks.meta', { n: it.frames_count })
                       + (it.top_behavior ? ' · ' + t('behavior.' + it.top_behavior) : '');
      info.appendChild(meta);
      row.appendChild(info);
      row.onclick = async () => {
        closeTracksModal();
        // V8.8.4: открыть плеер трека вместо простого перехода.
        await openTrackPlayer(it.animal_id);
      };
      body.appendChild(row);
    });
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger);">'
                   + t('error.load', { msg: String(e.message || e) }) + '</p>';
  }
}

function closeTracksModal() { closeModal('tracksModal'); }

// V8.8.2: вектор движения выбранной рамки.
// V8.8.5: состояние сохраняется между сессиями.
let _motionVectorOn = (() => {
  try { return localStorage.getItem('pdb_motion_vector') === '1'; } catch (e) { return false; }
})();
let _motionVectorReq = 0;

function _applyMotionVectorBtnState() {
  const btn = document.getElementById('attrVectorBtn');
  if (!btn) return;
  btn.classList.toggle('active', _motionVectorOn);
  btn.setAttribute('aria-pressed', _motionVectorOn ? 'true' : 'false');
}

async function toggleMotionVector() {
  _motionVectorOn = !_motionVectorOn;
  try { localStorage.setItem('pdb_motion_vector', _motionVectorOn ? '1' : '0'); } catch (e) {}
  _applyMotionVectorBtnState();
  haptic('selection');
  await _refreshMotionVector();
}

async function _refreshMotionVector() {
  const svg = document.getElementById('motionLayer');
  if (!svg) return;
  svg.innerHTML = '<defs>'
    + '<marker id="motionArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
    + '<path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>';
  if (!_motionVectorOn || !currentImageId) return;
  if (!boxes.length) return;
  const req = ++_motionVectorReq;
  try {
    const data = await api(`/api/images/${currentImageId}/motion_vectors`);
    if (req !== _motionVectorReq) return;
    if (!data || !data.items) return;
    const NS = 'http://www.w3.org/2000/svg';
    let drawn = 0;
    const missing_reasons = {};
    for (const idxStr of Object.keys(data.items)) {
      const item = data.items[idxStr];
      if (!item) continue;
      if (!item.found) {
        const r = item.reason || 'unknown';
        const short = r.split(' ')[0].split('(')[0].trim();
        missing_reasons[short] = (missing_reasons[short] || 0) + 1;
        console.log('[motion] idx=' + idxStr + ' aid=' + (boxes[parseInt(idxStr,10)]||{}).animal_id
                    + ' NOT FOUND reason=' + r);
        continue;
      }
      const idx = parseInt(idxStr, 10);
      const box = boxes[idx];
      const [fx, fy] = item.from || [0, 0];
      const [tx, ty] = item.to || [0, 0];
      const x1 = fx * 640, y1 = fy * 640;
      const x2 = tx * 640, y2 = ty * 640;
      console.log('[motion] idx=' + idx + ' aid=' + (box||{}).animal_id
                  + ' OK delta=' + item.delta + ' src=' + item.match_source);
      if (Math.hypot(x2 - x1, y2 - y1) < 2) continue;
      let color = 'var(--accent)';
      if (box && box.behavior) color = _behaviorColor(box.behavior);
      const line = document.createElementNS(NS, 'line');
      line.setAttribute('x1', x1); line.setAttribute('y1', y1);
      line.setAttribute('x2', x2); line.setAttribute('y2', y2);
      line.setAttribute('stroke', color);
      line.setAttribute('stroke-width', '2.5');
      line.setAttribute('stroke-linecap', 'round');
      line.setAttribute('marker-end', 'url(#motionArrow)');
      line.setAttribute('opacity', '0.9');
      svg.appendChild(line);
      const start = document.createElementNS(NS, 'circle');
      start.setAttribute('cx', x1); start.setAttribute('cy', y1); start.setAttribute('r', '4');
      start.setAttribute('fill', color); start.setAttribute('fill-opacity', '0.45');
      svg.appendChild(start);
      drawn++;
    }
    const s = data.summary || {};
    if (s.total_with_aid === 0) {
      setStatus(t('attr.vector.status.noIds'), 3500);
    } else if (drawn === 0) {
      const reasons = Object.keys(missing_reasons);
      let hint = reasons.length
        ? reasons.map(k => k + '×' + missing_reasons[k]).join(', ')
        : '';
      setStatus(t('attr.vector.status.none', { total: s.total_with_aid }) + (hint ? ' [' + hint + ']' : ''), 5000);
    } else {
      setStatus(t('attr.vector.status.ok', { drawn: drawn, total: s.total_with_aid }), 3000);
    }
  } catch (e) {
    console.warn('motion_vectors failed:', e);
  }
}

// V8.8.3: цвет по поведению — используется и в стрелке, и в бейджах.
function _behaviorColor(beh) {
  const map = {
    eat:    '#34c759',
    walk:   '#0a84ff',
    lie:    '#8e8e93',
    drink:  '#5ac8fa',
    stand:  '#ffcc00',
    active: '#ff3b30',
  };
  return map[beh] || 'var(--accent)';
}

// V8.8.4: экспорт треков.
function exportTracks(fmt) {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const url = `/api/projects/${currentProjectId}/tracks/export?format=${fmt}`;
  const name = `tracks_project_${currentProjectId}.${fmt}`;
  downloadFile(url, name);
  haptic('selection');
}

// V8.8.4: плеер трека.
let _playerTrack = null;   // {animal_id, frames: [...], currentIdx: 0}

async function openTrackPlayer(animalId) {
  if (!currentProjectId) return;
  const body = document.getElementById('trackPlayerStrip');
  const meta = document.getElementById('trackPlayerMeta');
  const title = document.getElementById('trackPlayerTitle');
  body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;">'
                  + t('common.loading') + '</p>';
  meta.textContent = '';
  title.textContent = 'Трек #' + animalId;
  openModal('trackPlayerModal');
  try {
    const r = await api(`/api/projects/${currentProjectId}/tracks/${animalId}/frames`);
    const items = (r && r.items) || [];
    if (!items.length) {
      body.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:24px 0;">'
                     + t('tracks.playerEmpty') + '</p>';
      return;
    }
    _playerTrack = { animal_id: animalId, frames: items, currentIdx: 0 };
    _renderTrackPlayer();
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger);">Ошибка: '
                   + String(e.message || e) + '</p>';
  }
}

function _renderTrackPlayer() {
  if (!_playerTrack) return;
  const body = document.getElementById('trackPlayerStrip');
  const meta = document.getElementById('trackPlayerMeta');
  const items = _playerTrack.frames;
  body.innerHTML = '';
  items.forEach((it, idx) => {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'flex:0 0 110px;border-radius:10px;overflow:hidden;cursor:pointer;border:2px solid transparent;position:relative;';
    if (idx === _playerTrack.currentIdx) {
      wrap.style.borderColor = 'var(--accent)';
      wrap.style.boxShadow = '0 0 0 2px var(--accent-soft)';
    }
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.alt = '';
    img.src = `/api/images/${it.image_id}/thumb`;
    img.style.cssText = 'width:110px;height:80px;object-fit:cover;display:block;background:var(--bg-canvas);';
    wrap.appendChild(img);
    const cap = document.createElement('div');
    cap.style.cssText = 'padding:4px 6px;font-size:0.6875rem;color:var(--text-secondary);background:var(--bg-hover);text-align:center;';
    const parts = [];
    if (it.frame_index != null) parts.push('f' + it.frame_index);
    if (it.behavior) parts.push(t('behavior.' + it.behavior));
    cap.textContent = parts.join(' · ') || ('#' + it.image_id);
    wrap.appendChild(cap);
    wrap.onclick = () => {
      _playerTrack.currentIdx = idx;
      _renderTrackPlayer();
    };
    wrap.ondblclick = () => playerOpenCurrent();
    body.appendChild(wrap);
    if (idx === _playerTrack.currentIdx) {
      setTimeout(() => { try { wrap.scrollIntoView({inline: 'center', block: 'nearest'}); } catch(e) {} }, 30);
    }
  });
  const cur = items[_playerTrack.currentIdx];
  const total = items.length;
  const bi = cur.behavior ? ' · ' + t('behavior.' + cur.behavior) : '';
  meta.textContent = `#${_playerTrack.animal_id} · кадр ${_playerTrack.currentIdx + 1} из ${total}`
                   + (cur.frame_index != null ? ' (f' + cur.frame_index + ')' : '')
                   + bi;
  // disable кнопок на границах
  const p = document.getElementById('trackPlayerPrev');
  const n = document.getElementById('trackPlayerNext');
  if (p) p.disabled = _playerTrack.currentIdx <= 0;
  if (n) n.disabled = _playerTrack.currentIdx >= total - 1;
}

function playerNav(delta) {
  if (!_playerTrack) return;
  const ni = _playerTrack.currentIdx + delta;
  if (ni < 0 || ni >= _playerTrack.frames.length) return;
  _playerTrack.currentIdx = ni;
  _renderTrackPlayer();
}

async function playerOpenCurrent() {
  if (!_playerTrack) return;
  const cur = _playerTrack.frames[_playerTrack.currentIdx];
  if (!cur) return;
  closeTrackPlayer();
  if (viewMode !== 'main') { viewMode = 'main'; updateSectionUI(); }
  await selectImage(cur.image_id, { skipDirtyCheck: true });
}

function closeTrackPlayer() {
  _playerTrack = null;
  closeModal('trackPlayerModal');
}

function _installAttrBar() {
  const bar = document.getElementById('attrBar');
  if (!bar || bar.__bound) return;
  bar.__bound = true;
  // V8.3.2: не даём pointerdown уйти наружу и снять выделение.
  bar.addEventListener('pointerdown', (e) => {
    // На кнопках — не даём всплывать вообще.
    if (e.target.closest('button')) {
      e.stopPropagation();
      return;
    }
    // На input — оставляем дефолт (курсор, фокус), но не даём
    // сработать глобальному обработчику сброса выделения.
    e.stopPropagation();
  });
  bar.querySelectorAll('.beh-btn[data-beh]').forEach(btn => {
    btn.addEventListener('click', () => {
      const beh = btn.dataset.beh || null;
      _applyBehaviorToTargets(beh);
    });
  });
  const inp = document.getElementById('animalIdInput');
  if (inp) {
    inp.addEventListener('change', () => {
      const v = inp.value.trim();
      if (!v) { _applyAnimalIdToTargets(null); return; }
      const n = parseInt(v, 10);
      _applyAnimalIdToTargets((isNaN(n) || n <= 0) ? null : n);
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
    });
  }
  const newBtn = document.getElementById('animalIdNewBtn');
  if (newBtn) newBtn.addEventListener('click', () => _assignNextAnimalId());
  // V8.6.0 (M2.4): кнопка авто-определения поведения.
  const autoBtn = document.getElementById('attrPredictBehBtn');
  if (autoBtn) autoBtn.addEventListener('click', () => _autoDetectBehavior());
  // V8.6.9: кнопка копирования скелета из похожего кадра.
  const skelBtn = document.getElementById('attrSkeletonFromSimilarBtn');
  if (skelBtn) skelBtn.addEventListener('click', () => _copySkeletonFromSimilar());
  // V8.7.1: кнопка авто-скелета через pose-модель.
  const poseBtn = document.getElementById('attrSkeletonPoseBtn');
  if (poseBtn) poseBtn.addEventListener('click', () => _autoSkeletonPose());
  // V8.8.0: кнопка трекинга.
  const trackBtn = document.getElementById('attrTrackBtn');
  if (trackBtn) trackBtn.addEventListener('click', () => _startTracking());
  // V8.8.1: кнопка ручного связывания с предыдущим.
  const linkBtn = document.getElementById('attrLinkPrevBtn');
  if (linkBtn) linkBtn.addEventListener('click', () => _linkFromPrev());
  // V8.8.2: toggle вектора движения.
  const vecBtn = document.getElementById('attrVectorBtn');
  if (vecBtn) {
    vecBtn.addEventListener('click', () => toggleMotionVector());
    // V8.8.5: применить сохранённое состояние (без перезапроса).
    _applyMotionVectorBtnState();
  }
  // V8.4.0: кнопка «ко всем».
  const allBtn = document.getElementById('attrApplyAllBtn');
  if (allBtn) allBtn.addEventListener('click', () => _applyAllToPhoto());
  const clearBtn = document.getElementById('animalIdClearBtn');
  if (clearBtn) clearBtn.addEventListener('click', () => _applyAnimalIdToTargets(null));
}

function updateHardBtn() {
  const btn = document.getElementById('hardBtn');
  if (!btn) return;
  const meta = allImages.find(i => i.id === currentImageId && i._kind !== 'project');
  btn.classList.toggle('active', !!(meta && meta.is_hard));
}
function updateSimilarBtn() {
  const btn = document.getElementById('similarBtn');
  if (!btn) return;
  btn.disabled = !currentImageId;
}
function updateFreezeBtn() {
  const btn = document.getElementById('freezeBtn');
  if (!btn) return;
  btn.disabled = !getSelectedIndices().length;
}
function clearSearch() {
  document.getElementById('searchInput').value = '';
  document.getElementById('searchClear').classList.remove('visible');
  searchQuery = '';
  // V7.9.3: очистка поиска — перезапрос к серверу.
  loadImages();
}

/* ===== Upload / import ===== */
async function uploadImages() {
  const input = document.getElementById('fileInput');
  if (!input.files.length) return;
  if (viewMode !== 'main') { viewMode = 'main'; updateSectionUI(); }
  setStatus(t('toast.uploading'), 60000);
  let added = 0, dup = 0, failed = 0, renamed = 0;
  const dupNames = [];
  for (const file of input.files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch(`/api/projects/${currentProjectId}/images`, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'DatasetBuilder' } });
      if (res.status === 409) {
        dup++;
        const data = await res.json().catch(() => ({}));
        dupNames.push({ name: file.name, reason: data.detail || 'дубликат' });
      } else if (res.ok) {
        const data = await res.json();
        added++;
        if (data.renamed_from) renamed++;
      } else failed++;
    } catch (e) { failed++; }
  }
  input.value = '';
  await loadImages();
  const parts = [t('upload.added', { n: added })];
  if (renamed) parts.push(t('upload.renamed', { n: renamed }));
  if (dup) parts.push(t('upload.dups', { n: dup }));
  if (failed) parts.push(t('upload.failed', { n: failed }));
  setStatus(parts.join(', '), 6000);
  if (added > 0) haptic('success');
  if (dupNames.length) {
    const lines = dupNames.slice(0, 15).map(d => `• ${d.name}\n   → ${d.reason}`).join('\n');
    const more = dupNames.length > 15 ? `\n${t('upload.more', { n: dupNames.length - 15 })}` : '';
    await showAlert(t('upload.dupsTitle', { n: dupNames.length }), `${lines}${more}`);
  }
}
async function handleImport() {
  const input = document.getElementById('importInput');
  if (!input.files.length) return;
  const file = input.files[0];
  input.value = '';
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const status = document.getElementById('importStatus');
  const result = document.getElementById('importResult');
  const closeBtn = document.getElementById('importCloseBtn');
  const progressWrap = document.getElementById('importProgressWrap');
  const progressFill = document.getElementById('importProgressFill');
  const progressText = document.getElementById('importProgressText');
  const progressPhase = document.getElementById('importProgressPhase');
  const progressBar = document.getElementById('importProgressBar');
  const importTitle = document.getElementById('importTitle');
  if (importTitle) importTitle.textContent = 'Импорт датасета';
  status.textContent = t('importModal.loading');
  status.style.color = '';
  result.style.display = 'none'; result.innerHTML = '';
  closeBtn.style.display = 'none';
  if (progressWrap) progressWrap.style.display = 'block';
  if (progressFill) progressFill.style.width = '0%';
  if (progressText) progressText.textContent = '0%';
  if (progressPhase) progressPhase.textContent = 'Загрузка и обработка…';
  if (progressBar) progressBar.setAttribute('aria-valuenow', '0');
  openModal('importModal');
  // V7.8.2: убран поллинг /api/import/status — такого эндпоинта нет.
  // Сервер отдаёт результат одним запросом, поэтому промежуточный
  // прогресс всё равно недоступен. Показываем indeterminate-состояние.
  if (progressPhase) progressPhase.textContent = 'Обработка (может занять минуту)…';
  if (progressFill) progressFill.style.width = '30%';
  if (progressText) progressText.textContent = '…';
  if (progressBar) progressBar.setAttribute('aria-valuenow', '30');
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`/api/projects/${currentProjectId}/import`, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'DatasetBuilder' } });
    const data = await res.json().catch(() => ({}));
    if (progressWrap) progressWrap.style.display = 'none';
    if (!res.ok) {
      status.textContent = 'Ошибка импорта';
      status.style.color = 'var(--danger)';
      result.style.display = 'block';
      result.textContent = data.detail || 'Не удалось импортировать.';
    } else {
      status.textContent = 'Импорт завершён ✓';
      status.style.color = 'var(--success)';
      result.style.display = 'block';
      const fmt = ({ coco: 'COCO', yolo: 'YOLO', cvat: 'CVAT XML', ls: 'Label Studio', images_only: 'Только изображения' })[data.format] || data.format;
      let html = `<div>Формат: <b>${escapeHtml(fmt)}</b></div>`;
      if (data.imported_images) html += `<div>Загружено изображений: <b>${data.imported_images}</b></div>`;
      if (data.skipped_duplicates) html += `<div>Пропущено дубликатов: <b>${data.skipped_duplicates}</b></div>`;
      if (data.failed_images) html += `<div>Не удалось открыть: <b>${data.failed_images}</b></div>`;
      html += `<div>Совпало изображений: <b>${data.matched_images}</b></div>`;
      html += `<div>Добавлено рамок: <b>${data.added_annotations}</b></div>`;
      if (data.unmatched_count) html += `<div style="margin-top:8px;">Не найдено: <b>${data.unmatched_count}</b></div>`;
      result.innerHTML = html;
      await loadImages();
      haptic('success');
    }
  } catch (e) {
    if (progressWrap) progressWrap.style.display = 'none';
    status.textContent = 'Ошибка сети';
    status.style.color = 'var(--danger)';
    result.style.display = 'block';
    result.textContent = String(e.message || e);
  }
  closeBtn.style.display = 'inline-flex';
}
function closeImportModal() { closeModal('importModal'); }

/* ===== External imports ===== */
function openImportSourceModal() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  openModal('importSourceModal');
}
function closeImportSourceModal() { closeModal('importSourceModal'); }

async function _runExternalImport(label, fn) {
  const status = document.getElementById('importStatus');
  const result = document.getElementById('importResult');
  const closeBtn = document.getElementById('importCloseBtn');
  const progressWrap = document.getElementById('importProgressWrap');
  const progressFill = document.getElementById('importProgressFill');
  const progressText = document.getElementById('importProgressText');
  const progressPhase = document.getElementById('importProgressPhase');
  const importTitle = document.getElementById('importTitle');

  if (importTitle) importTitle.textContent = 'Импорт — ' + label;
  if (status) { status.textContent = 'Идёт импорт…'; status.style.color = ''; }
  if (result) { result.style.display = 'none'; result.innerHTML = ''; }
  if (closeBtn) closeBtn.style.display = 'none';
  if (progressWrap) progressWrap.style.display = 'block';
  if (progressFill) progressFill.style.width = '30%';
  if (progressText) progressText.textContent = '…';
  if (progressPhase) progressPhase.textContent = 'Скачивание и распаковка (может занять минуту)…';
  openModal('importModal');
  try {
    const data = await fn();
    if (progressWrap) progressWrap.style.display = 'none';
    if (status) { status.textContent = 'Импорт завершён ✓'; status.style.color = 'var(--success)'; }
    if (result) {
      result.style.display = 'block';
      const fmt = ({ coco: 'COCO', yolo: 'YOLO', cvat: 'CVAT', ls: 'Label Studio', images_only: 'Только изображения' })[data.format] || data.format;
      let html = `<div>Формат: <b>${escapeHtml(fmt)}</b></div>`;
      html += `<div>Загружено изображений: <b>${data.imported_images || 0}</b></div>`;
      if (data.skipped_duplicates) html += `<div>Пропущено дубликатов: <b>${data.skipped_duplicates}</b></div>`;
      html += `<div>Совпало: <b>${data.matched_images || 0}</b></div>`;
      html += `<div>Добавлено рамок: <b>${data.added_annotations || 0}</b></div>`;
      result.innerHTML = html;
    }
    await loadImages();
    haptic('success');
  } catch (e) {
    if (progressWrap) progressWrap.style.display = 'none';
    if (status) { status.textContent = 'Ошибка'; status.style.color = 'var(--danger)'; }
    if (result) { result.style.display = 'block'; result.textContent = String(e.message || e); }
  }
  if (closeBtn) closeBtn.style.display = 'inline-flex';
}
async function importFromUrl() {
  const url = await showPrompt(t('prompt.importUrl.title'),
    { text: t('prompt.importUrl.text'), defaultValue: '', hint: t('prompt.importUrl.hint'), okText: t('prompt.importUrl.ok') });
  if (!url) return;
  closeImportSourceModal();
  await _runExternalImport('URL', () => api(`/api/projects/${currentProjectId}/import/url`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: String(url).trim() }),
  }));
}
async function importFromRoboflow() {
  const apiKey = await showPrompt('Roboflow: API key', { text: 'Найди в Settings → API Keys.', okText: 'Далее' });
  if (!apiKey) return;
  const workspace = await showPrompt('Roboflow: workspace', { okText: 'Далее' });
  if (!workspace) return;
  const project = await showPrompt('Roboflow: project slug', { okText: 'Далее' });
  if (!project) return;
  const versionStr = await showPrompt('Roboflow: version', { defaultValue: '1', okText: 'Импортировать' });
  if (versionStr === null) return;
  const version = parseInt(versionStr, 10);
  if (isNaN(version)) { setError('Version должен быть числом'); return; }
  closeImportSourceModal();
  await _runExternalImport('Roboflow', () => api(`/api/projects/${currentProjectId}/import/roboflow`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey, workspace, project, version }),
  }));
}
async function importFromSupervisely() {
  const token = await showPrompt('Supervisely: API token', { text: 'Account settings → API Token.', okText: 'Далее' });
  if (!token) return;
  const pidStr = await showPrompt('Supervisely: project ID', { okText: 'Далее' });
  if (!pidStr) return;
  const pid = parseInt(pidStr, 10);
  if (isNaN(pid)) { setError('Project ID должен быть числом'); return; }
  const dsStr = await showPrompt('Supervisely: dataset ID (опционально)', { text: 'Оставь пустым.', defaultValue: '', okText: 'Импортировать' });
  if (dsStr === null) return;
  const dsId = dsStr.trim() ? parseInt(dsStr, 10) : null;
  closeImportSourceModal();
  await _runExternalImport('Supervisely', () => api(`/api/projects/${currentProjectId}/import/supervisely`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_token: token, project_id: pid, dataset_id: dsId }),
  }));
}
async function importFromLocalFolder() {
  const path = await showPrompt(t('prompt.importFolder.title'),
    { text: t('prompt.importFolder.text'), hint: t('prompt.importFolder.hint'), okText: t('prompt.importFolder.ok') });
  if (!path) return;
  const recursiveStr = await showPrompt(t('prompt.importFolder.recursive.title'),
    { text: t('prompt.importFolder.recursive.text'), defaultValue: 'yes', okText: t('prompt.importFolder.recursive.ok') });
  if (recursiveStr === null) return;
  const recursive = ['y', 'yes', 'да', '1', 'true'].includes(String(recursiveStr).trim().toLowerCase());
  closeImportSourceModal();
  await _runExternalImport('Папка', () => api(`/api/projects/${currentProjectId}/import/local_folder`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: String(path).trim(), recursive }),
  }));
}
async function importFromLabelbox() {
  const apiKey = await showPrompt('Labelbox: API key', { text: 'Account → API key.', okText: 'Далее' });
  if (!apiKey) return;
  const projectId = await showPrompt('Labelbox: Project ID', { text: 'ID в URL или в настройках проекта.', okText: 'Импортировать' });
  if (!projectId) return;
  closeImportSourceModal();
  await _runExternalImport('Labelbox', () => api(`/api/projects/${currentProjectId}/import/labelbox`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: String(apiKey).trim(), project_id: String(projectId).trim() }),
  }));
}
async function importFromScale() {
  const apiKey = await showPrompt('Scale AI: API key', { text: 'Settings → API Keys.', okText: 'Далее' });
  if (!apiKey) return;
  const dsId = await showPrompt('Scale AI: Dataset ID', { text: 'ID датасета в Nucleus.', okText: 'Импортировать' });
  if (!dsId) return;
  closeImportSourceModal();
  await _runExternalImport('Scale AI', () => api(`/api/projects/${currentProjectId}/import/scale`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: String(apiKey).trim(), dataset_id: String(dsId).trim() }),
  }));
}
async function importFromDarwin() {
  const apiKey = await showPrompt('V7 Darwin: API key', { text: 'Settings → API keys.', okText: 'Далее' });
  if (!apiKey) return;
  const team = await showPrompt('V7 Darwin: team slug', { text: 'Slug команды.', okText: 'Далее' });
  if (!team) return;
  const ds = await showPrompt('V7 Darwin: dataset slug', { text: 'Slug датасета.', okText: 'Далее' });
  if (!ds) return;
  const ver = await showPrompt('V7 Darwin: имя версии (опционально)', { text: 'Оставь пустым для автоимени.', defaultValue: '', okText: 'Импортировать' });
  if (ver === null) return;
  closeImportSourceModal();
  await _runExternalImport('V7 Darwin', () => api(`/api/projects/${currentProjectId}/import/darwin`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key: String(apiKey).trim(),
      team_slug: String(team).trim(),
      dataset_slug: String(ds).trim(),
      version_name: String(ver || '').trim() || null,
    }),
  }));
}

/* ===== Select / delete / rename ===== */
let _selectToken = 0;
async function selectImage(id, { autoAutolabel = false, skipDirtyCheck = false } = {}) {
  if (viewMode !== 'main') return;
  // V7.9.3: клик по уже активному изображению ничего не делает.
  // Иначе пользователь получает перезагрузку файла и запрос
  // «перейти без сохранения?», хотя никуда не уходит.
  if (id === currentImageId && !autoAutolabel) return;
  if (!skipDirtyCheck && isDirty && currentImageId && currentImageId !== id) {
    const ok = await showConfirm(
      t('confirm.unsaved.title'),
      t('confirm.unsaved.text'),
      { okText: t('confirm.unsaved.ok'), danger: true }
    );
    if (!ok) return;
  }
  const token = ++_selectToken;
  currentImageId = id;
  selectedIndex = -1; multiSelected.clear(); dragState = null;
  showCanvas(true);
  updateDelBoxBtn();
  scrollListToImage(id);
  renderImageList();

  const img = document.getElementById('image');
  if (img.__selectAbort) { try { img.__selectAbort.abort(); } catch (_) {} }
  const controller = new AbortController();
  img.__selectAbort = controller;

  img.style.transition = 'none';
  img.style.opacity = '0';
  const imgLoadPromise = new Promise((resolve) => {
    const onDone = () => resolve();
    img.onload = onDone;
    // V8.3.1: явно сообщаем про отсутствующий файл.
    img.onerror = () => {
      setError('Файл изображения отсутствует на диске', 5000);
      onDone();
    };
    controller.signal.addEventListener('abort', onDone, { once: true });
  });
  const meta = allImages.find(i => i.id === id);
  img.alt = meta ? `Размеченное изображение: ${meta.filename}` : 'Размеченное изображение';
  img.src = `/api/images/${id}/file?t=${Date.now()}`;

  const loadAnnotations = async () => {
    try { return await api(`/api/images/${id}/annotations`); }
    catch (e) {
      if (e.status !== 404) {
        console.error('loadAnnotations failed:', e);
        setStatus('Не удалось загрузить разметку', 4000, 'error');
      }
      return [];
    }
  };
  const [_, anns] = await Promise.all([imgLoadPromise, loadAnnotations()]);
  if (token !== _selectToken) return;
  void img.offsetWidth;
  img.style.transition = '';
  img.style.opacity = '1';

  boxes = anns;
  _clearDebugBoxes();
  currentImageTagIds = new Set(meta?.tag_ids || []);
  renderBoxes();
  resetHistory();
  markClean();
  const dz = currentProjectMeta && currentProjectMeta.default_zoom;
  if (dz && Number.isFinite(dz) && dz !== 1.0) {
    zoom = Math.min(Math.max(dz, ZOOM_MIN), ZOOM_MAX);
    panX = 320 - 320 * zoom;
    panY = 320 - 320 * zoom;
    clampPan();
    applyTransform();
  } else {
    zoomReset();
  }
  updateHardBtn();
  updateSimilarBtn();
  updateFreezeBtn();
  _refreshAttrBar();
  // V8.8.6: motion vector — в очередь, без блокировки.
  scheduleRefreshMotionVectorDebounced(120);
  // V8.5.1: подгружаем keypoints для этого изображения.
  window._kpByIndex = {};
  try {
    const rows = await api(`/api/images/${id}/keypoints_by_index`);
    window._kpByIndex = rows || {};
    // V8.5.6: ВСЕГДА перезаписываем boxes[].keypoints из серверного снимка.
    // (даже пустым — иначе стейл от предыдущего открытия)
    boxes.forEach((b, bi) => {
      const k = window._kpByIndex[String(bi)];
      b.keypoints = Array.isArray(k) ? k.map(p => ({...p})) : [];
    });
  } catch (e) { window._kpByIndex = {}; }
  if (skeletonMode) {
    keypoints = [];
    const _si = _targetAnnotationId();
    if (_si >= 0 && Array.isArray(boxes[_si].keypoints)) {
      keypoints = boxes[_si].keypoints.map(p => ({...p}));
    }
    renderSkeleton();
  }
  await renderTagChips();

  const isNewInSession = !sessionSeen.has(id);
  sessionSeen.add(id);
  if (autoAutolabel && isNewInSession && (!meta || (meta.annotation_count || 0) === 0)) {
    await runAutolabel();
  }
}
async function deleteImage(id, filename) {
  const ok = await showConfirm(
    t('confirm.deleteImage.title'),
    t('confirm.deleteImage.text', { name: filename }),
    { okText: t('confirm.toTrash.ok') }
  );
  if (!ok) return;
  haptic('warning');
  // V8.1.1: запоминаем для undo списка.
  _pushListUndo({ type: 'delete', ids: [id] });
  try {
    await api(`/api/images/${id}`, { method: 'DELETE' });
    sessionSeen.delete(id);
    selectedForDelete.delete(id);
    if (currentImageId === id) {
      currentImageId = null; boxes = []; selectedIndex = -1; multiSelected.clear();
      document.getElementById('image').removeAttribute('src');
      _clearDebugBoxes();
      renderBoxes(); showCanvas(false); resetHistory(); markClean(); updateDelBoxBtn();
    }
    await loadImages();
    await renderTagChips();
    setStatus(t('toast.imageDeleted'));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function renameImage(id, currentName) {
  const oldExt = getExt(currentName);
  const oldStem = getStem(currentName);
  const hint = oldExt
    ? `Расширение .${oldExt} сохраняется автоматически. Недопустимые: \\ / : * ? " < > |`
    : 'Недопустимые символы: \\ / : * ? " < > |';
  const input = await showPrompt(t('prompt.renameFile.title'), {
    text: t('prompt.renameFile.text'),
    defaultValue: oldStem,
    hint,
    okText: t('prompt.renameFile.ok'),
  });
  if (input === null) return;
  const newStem = String(input).trim();
  if (!newStem) { setStatus('Пустое имя'); return; }
  if (newStem === oldStem) return;
  if (/[\\/:*?"<>|]/.test(newStem)) { setError('Недопустимые символы', 5000); return; }
  try {
    const r = await api(`/api/images/${id}/rename`, { method: 'POST', body: new URLSearchParams({ filename: newStem }) });
    await loadImages();
    setStatus(t('toast.renamed', { name: r.filename }));
  } catch (e) {
    if (e.status === 409) setStatus('Имя уже занято', 4000);
    else setError(String(e.message || e).slice(0, 140), 4000);
  }
}
async function restoreImage(id) {
  try {
    await api(`/api/images/${id}/restore`, { method: 'POST' });
    selectedForDelete.delete(id);
    await loadImages();
    setStatus(t('toast.imageRestored'));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function permanentDelete(id, filename) {
  const ok = await showConfirm(
    t('confirm.deletePerm.title'),
    t('confirm.deletePerm.text', { name: filename }),
    { okText: t('confirm.deletePerm.ok'), danger: true }
  );
  if (!ok) return;
  haptic('warning');
  try {
    await api(`/api/images/${id}/permanent`, { method: 'DELETE' });
    selectedForDelete.delete(id);
    await loadImages();
    setStatus(t('toast.imageDeletedPerm'));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}

/* ===== Hard / freeze ===== */
async function toggleHardCurrent() {
  if (!currentImageId) return;
  const meta = allImages.find(i => i.id === currentImageId);
  try {
    const r = await api(`/api/images/${currentImageId}/toggle_hard`, { method: 'POST' });
    if (meta) meta.is_hard = !!r.is_hard;
    updateHardBtn();
    _refreshRowMeta(currentImageId, { flash: true });
    if (activeFilter === 'hard') applyFiltersAndRender();
    haptic('selection');
    setStatus(r.is_hard ? t('toast.hardSet') : t('toast.hardUnset'));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
function toggleFreezeSelected() {
  const indices = getSelectedIndices();
  if (!indices.length) { setStatus(t('toast.pickBoxes')); return; }
  const allFrozen = indices.every(i => boxes[i].frozen);
  indices.forEach(i => { boxes[i].frozen = !allFrozen; });
  renderBoxes(); pushHistory(); markDirty();
  haptic('selection');
  setStatus(allFrozen ? t('toast.unfrozen') : t('toast.frozen'));
}

/* ===== Batch ===== */
async function confirmBatchDelete() {
  const n = selectedForDelete.size;
  if (!n) return;
  const _undoIds = Array.from(selectedForDelete);
  const ok = await showConfirm(
    t('confirm.toTrash.title', { n }),
    t('confirm.toTrash.text'),
    { okText: t('confirm.toTrash.ok') }
  );
  if (!ok) return;
  haptic('warning');
  try {
    const r = await api('/api/images/batch_delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Array.from(selectedForDelete)),
    });
    if (Array.from(selectedForDelete).includes(currentImageId)) {
      currentImageId = null; boxes = []; selectedIndex = -1; multiSelected.clear();
      document.getElementById('image').removeAttribute('src');
      _clearDebugBoxes();
      renderBoxes(); showCanvas(false); resetHistory(); markClean(); updateDelBoxBtn();
    }
    selectedForDelete.clear();
    _pushListUndo({ type: 'delete', ids: _undoIds });
    await loadImages();
    await renderTagChips();
    setStatus(t('toast.toTrashN', { n: r.deleted }));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function confirmBatchPermanentDelete() {
  const n = selectedForDelete.size;
  if (!n) return;
  const ok = await showConfirm(
    t('confirm.batchPerm.title', { n }),
    t('confirm.batchPerm.text'),
    { okText: t('confirm.deletePerm.ok'), danger: true }
  );
  if (!ok) return;
  haptic('warning');
  try {
    const r = await api('/api/images/batch_permanent_delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Array.from(selectedForDelete)),
    });
    selectedForDelete.clear();
    await loadImages();
    setStatus(t('toast.deletedN', { n: r.deleted }));
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function batchRestore() {
  const ids = Array.from(selectedForDelete);
  if (!ids.length) return;
  try {
    const r = await api('/api/images/batch_restore', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ids),
    });
    selectedForDelete.clear();
    await loadImages();
    let msg = `Восстановлено: ${r.restored}`;
    if (r.renamed) msg += ` (переименовано: ${r.renamed})`;
    setStatus(msg, 5000);
    haptic('success');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}

/* ===== Preview / Stats / Validate ===== */
function openPreview(id, filename, daysLeft) {
  document.getElementById('previewName').textContent = filename;
  document.getElementById('previewDays').textContent = daysLeft != null
    ? (daysLeft <= 0 ? 'истекает' : `осталось ${daysLeft} дн.`) : '';
  const previewImg = document.getElementById('previewImg');
  previewImg.src = `/api/images/${id}/file?t=${Date.now()}`;
  previewImg.alt = `Превью: ${filename}`;
  openModal('previewModal');
}
function closePreview() {
  closeModal('previewModal');
  document.getElementById('previewImg').removeAttribute('src');
}
async function downloadStatsCsv() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  // V8.0.0: активные фильтры применяются и к CSV-экспорту.
  const params = new URLSearchParams({
    filter: activeFilter,
    search: searchQuery || '',
  });
  if (activeTagIds.size) params.set('tag_ids', [...activeTagIds].join(','));
  const qs = params.toString();
  await downloadFile(
    `/api/projects/${currentProjectId}/stats.csv?${qs}`,
    `stats_project_${currentProjectId}.csv`,
  );
}
async function downloadFilesCsv() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  await downloadFile(`/api/projects/${currentProjectId}/files.csv`, `files_project_${currentProjectId}.csv`);
}
// V8.1.0: экспорт CSV всех рамок проекта.
async function downloadBoxesCsv() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  await downloadFile(`/api/projects/${currentProjectId}/boxes.csv`,
                     `boxes_project_${currentProjectId}.csv`);
}

async function openStats() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  try {
    const s = await api(`/api/projects/${currentProjectId}/stats`);
    document.getElementById('statTotal').textContent = s.total_images;
    document.getElementById('statAnnotated').textContent = s.annotated_images;
    document.getElementById('statUnannotated').textContent = s.unannotated_images;
    document.getElementById('statBoxes').textContent = s.total_boxes;
    const c = s.confidence;
    const maxVal = Math.max(c.manual, c.low, c.mid, c.high, 1);
    document.getElementById('barHigh').style.width = (c.high / maxVal * 100) + '%';
    document.getElementById('barMid').style.width = (c.mid / maxVal * 100) + '%';
    document.getElementById('barLow').style.width = (c.low / maxVal * 100) + '%';
    document.getElementById('barManual').style.width = (c.manual / maxVal * 100) + '%';
    document.getElementById('valHigh').textContent = c.high;
    document.getElementById('valMid').textContent = c.mid;
    document.getElementById('valLow').textContent = c.low;
    document.getElementById('valManual').textContent = c.manual;
    const list = document.getElementById('suspList');
    list.innerHTML = '';
    if (!s.top_suspicious.length) {
      const e = document.createElement('div');
      e.style.cssText = 'color:var(--text-secondary);font-size:0.8125rem;padding:8px 4px;';
      e.textContent = 'Размеченных нет.';
      list.appendChild(e);
    } else {
      s.top_suspicious.forEach(item => {
        const row = document.createElement('div');
        row.className = 'susp-row';
        row.setAttribute('role', 'button');
        row.setAttribute('tabindex', '0');
        const name = document.createElement('span');
        name.className = 'susp-name'; name.textContent = item.filename;
        row.appendChild(name);
        const badge = document.createElement('span');
        badge.className = 'susp-badge ' + (
          item.min_confidence == null ? 'manual'
          : item.min_confidence >= 0.75 ? 'high'
          : item.min_confidence >= 0.5 ? 'mid' : 'low');
        badge.textContent = item.min_confidence != null ? item.min_confidence.toFixed(2) : '—';
        row.appendChild(badge);
        const cnt = document.createElement('span');
        cnt.className = 'susp-count';
        cnt.textContent = `${item.annotation_count} шт.`;
        row.appendChild(cnt);
        const handler = async () => {
          closeStats();
          if (viewMode !== 'main') { viewMode = 'main'; updateSectionUI(); }
          await selectImage(item.id, { skipDirtyCheck: true });
        };
        row.onclick = handler;
        onActivate(row, handler);
        list.appendChild(row);
      });
    }
    openModal('statsModal');
  } catch (e) { setError('Статистика недоступна: ' + String(e.message).slice(0, 120), 5000); }
}
function closeStats() { closeModal('statsModal'); }
function openValidateFromExport() { closeExportModal(); setTimeout(() => openValidateModal(), 80); }
async function openValidateModal() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const body = document.getElementById('validateBody');
  body.innerHTML = `<p style="color:var(--text-secondary);font-size:0.8125rem;">${t('validate.checking')}</p>`;
  openModal('validateModal');
  try {
    // V8.0.0: если есть кэш для этого проекта — рендерим без запроса.
    let r;
    if (_validateCache && _validateCache.projectId === currentProjectId) {
      r = _validateCache.data;
    } else {
      r = await api(`/api/projects/${currentProjectId}/validate?deep=true`);
      _validateCache = { projectId: currentProjectId, data: r };
    }
    const bt = r.by_type || {};
    let html = '';
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card"><div class="stat-value" style="color:var(--box-low)">${bt.small_box || 0}</div><div class="stat-label">${t('validate.small')}</div></div>`;
    html += `<div class="stat-card"><div class="stat-value" style="color:var(--warning)">${bt.overlap || 0}</div><div class="stat-label">${t('validate.overlap')}</div></div>`;
    html += `<div class="stat-card"><div class="stat-value" style="color:var(--danger)">${bt.out_of_bounds || 0}</div><div class="stat-label">${t('validate.outOfBounds')}</div></div>`;
    html += `</div>`;
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card"><div class="stat-value" style="color:#ff375f">${bt.nested_box || 0}</div><div class="stat-label">${t('validate.nested')}</div></div>`;
    html += `<div class="stat-card"><div class="stat-value">${bt.aspect || 0}</div><div class="stat-label">${t('validate.aspect')}</div></div>`;
    html += `<div class="stat-card"><div class="stat-value">${r.unannotated.length}</div><div class="stat-label">${t('validate.unannotated')}</div></div>`;
    html += `</div>`;
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card" style="grid-column: 1 / -1;"><div class="stat-value" style="color:${r.total_issues ? 'var(--danger)' : 'var(--success)'}">${r.total_issues}</div><div class="stat-label">${t('validate.totalIssues')}</div></div>`;
    html += `</div>`;
    if (!r.total_issues && !r.unannotated.length) {
      html += `<p style="color:var(--success);font-size:0.875rem;text-align:center;padding:20px 0;">${t('validate.ok')}</p>`;
    } else {
      if (r.issues.length) {
        html += `<div class="stats-section-title">${t('validate.problems')}</div>`;
        const typeName = { small_box: 'малая', overlap: 'пересеч.', out_of_bounds: 'вне', aspect: 'аспект', nested_box: 'вложено' };
        r.issues.forEach(it => {
          const detailShort = escapeHtml(String(it.detail).slice(0, 70));
          html += `<div class="validator-issue ${it.type}" data-image-id="${it.image_id}" role="button" tabindex="0">`;
          html += `<span class="vi-type">${typeName[it.type] || it.type}</span>`;
          html += `<span class="vi-name">${escapeHtml(it.filename)}</span>`;
          html += `<span class="vi-detail">${detailShort}</span>`;
          html += `</div>`;
        });
      }
      if (r.unannotated.length) {
        html += `<div class="stats-section-title" style="margin-top:16px;">Без разметки (${r.unannotated.length})</div>`;
        r.unannotated.forEach(it => {
          html += `<div class="validator-issue aspect" data-image-id="${it.id}" role="button" tabindex="0">`;
          html += `<span class="vi-type">${t('validate.empty')}</span>`;
          html += `<span class="vi-name">${escapeHtml(it.filename)}</span>`;
          html += `</div>`;
        });
      }
    }
    body.innerHTML = html;
    body.querySelectorAll('.validator-issue').forEach(el => {
      const handler = async () => {
        const iid = parseInt(el.dataset.imageId, 10);
        closeValidateModal();
        if (viewMode !== 'main') { viewMode = 'main'; updateSectionUI(); }
        await loadImages();
        await selectImage(iid, { autoAutolabel: false, skipDirtyCheck: true });
      };
      el.onclick = handler;
      onActivate(el, handler);
    });
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger);">Ошибка: ' + escapeHtml(String(e.message || e)) + '</p>';
  }
}
function closeValidateModal() { closeModal('validateModal'); }

/* ===== Similar ===== */
async function openSimilarModal() {
  if (!currentImageId) return;
  const body = document.getElementById('similarBody');
  body.innerHTML = `<p style="color:var(--text-secondary);font-size:0.8125rem;padding:8px 0;">${t('similar.searching')}</p>`;
  openModal('similarModal');
  try {
    const r = await api(`/api/projects/${currentProjectId}/similar/${currentImageId}`);
    body.innerHTML = '';
    if (!r.items.length) {
      body.innerHTML = `<p style="color:var(--text-secondary);font-size:0.8125rem;padding:12px 0;text-align:center;">${t('similar.notFound')}</p>`;
      return;
    }
    r.items.forEach(it => {
      const row = document.createElement('div');
      row.className = 'similar-row';
      const img = document.createElement('img');
      img.className = 'similar-thumb'; img.loading = 'lazy'; img.alt = '';
      img.src = `/api/images/${it.id}/thumb`;
      row.appendChild(img);
      const info = document.createElement('div');
      info.className = 'similar-info';
      const nm = document.createElement('div');
      nm.className = 'similar-name'; nm.textContent = it.filename;
      const meta = document.createElement('div');
      meta.className = 'similar-meta';
      meta.textContent = t('similar.hamming', { d: it.distance, n: it.annotation_count });
      info.appendChild(nm); info.appendChild(meta);
      row.appendChild(info);
      const actions = document.createElement('div');
      actions.className = 'similar-actions';
      const openBtn = document.createElement('button');
      openBtn.className = 'btn btn-ghost btn-sm'; openBtn.textContent = t('similar.open');
      openBtn.onclick = async () => {
        closeSimilarModal();
        if (viewMode !== 'main') { viewMode = 'main'; updateSectionUI(); }
        await selectImage(it.id, { autoAutolabel: false, skipDirtyCheck: true });
      };
      actions.appendChild(openBtn);
      if (it.annotation_count > 0) {
        const copyBtn = document.createElement('button');
        copyBtn.className = 'btn btn-primary btn-sm';
        copyBtn.textContent = t('similar.copy', { n: it.annotation_count });
        copyBtn.onclick = async () => {
          const meta2 = allImages.find(x => x.id === currentImageId);
          if (meta2 && (meta2.annotation_count || 0) > 0) {
            const ok = await showConfirm(
              t('confirm.overwriteAnnotations.title'),
              t('confirm.overwriteAnnotations.text', { n: meta2.annotation_count, m: it.annotation_count }),
              { okText: t('confirm.overwriteAnnotations.ok'), danger: true }
            );
            if (!ok) return;
          }
          try {
            const res = await api(`/api/images/${currentImageId}/copy_annotations_from/${it.id}`, { method: 'POST' });
            boxes = await api(`/api/images/${currentImageId}/annotations`);
            renderBoxes({ animateIndices: new Set(boxes.map((_, i) => i)) });
            resetHistory(); markClean();
            await loadImages();
            closeSimilarModal();
            setStatus(`Скопировано рамок: ${res.count}`);
            haptic('success');
          } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
        };
        actions.appendChild(copyBtn);
      }
      row.appendChild(actions);
      body.appendChild(row);
    });
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger);">Ошибка: ' + escapeHtml(String(e.message || e)) + '</p>';
  }
}
function closeSimilarModal() { closeModal('similarModal'); }

/* ===== SAM ===== */
// V8.5.1: включение/выключение режима скелета.
function toggleSkeletonMode() {
  setSkeletonMode(!skeletonMode);
}

function setSkeletonMode(on) {
  skeletonMode = !!on;
  const btn = document.getElementById('skeletonModeBtn');
  if (btn) {
    btn.classList.toggle('active', skeletonMode);
    btn.setAttribute('aria-pressed', skeletonMode ? 'true' : 'false');
  }
  if (skeletonMode) {
    loadKeypointSchema().then(() => renderSkeleton());
    setStatus(t('skeleton.status.on'), 3000);
  } else {
    _clearSkeletonHint();
  }
  renderSkeleton();
  haptic('selection');
}

function _clearSkeletonHint() {
  if (_kpNextHintEl) { _kpNextHintEl.remove(); _kpNextHintEl = null; }
}

// V8.5.3: двойной клик по точке → toggle visibility.
function _toggleKeypointVisibility(idx) {
  if (idx < 0 || idx >= keypoints.length) return;
  const kp = keypoints[idx];
  kp.visibility = (kp.visibility != null && kp.visibility < 0.5) ? 1.0 : 0.0;
  _syncKeypointsToBox();
  pushHistory();
  markDirty();
  renderSkeleton();
  const meta = _schemaName(kp.name);
  const lbl = meta ? (getLang() === 'en' ? meta.label_en : meta.label_ru) : kp.name;
  setStatus(kp.visibility < 0.5
    ? t('skeleton.status.hidden', { name: lbl })
    : t('skeleton.status.visible', { name: lbl }), 1500);
  haptic('selection');
}

function _installSkeletonDblClick() {
  const layer = document.getElementById('skeletonLayer');
  if (!layer || layer.__dblBound) return;
  layer.__dblBound = true;
  layer.addEventListener('dblclick', (e) => {
    const dot = e.target.closest && e.target.closest('.skeleton-point');
    if (!dot) return;
    e.preventDefault();
    e.stopPropagation();
    const i = parseInt(dot.dataset.kpIdx, 10);
    if (!isNaN(i)) _toggleKeypointVisibility(i);
  });
}

function _targetAnnotationId() {
  // Выделенная рамка (или единственная на фото).
  const sel = getSelectedIndices();
  if (sel.length === 1) return sel[0];
  return -1;
}

// V8.5.8: рисование скелета для одной рамки.
// (функция была потеряна при замене renderSkeleton в v8.5.6/8.5.7)
function _drawSkeletonForBox(layer, kps, isSelected) {
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const wrap = document.createElement('div');
  wrap.className = 'skeleton-box' + (isSelected ? '' : ' muted');
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'skeleton-svg');
  svg.setAttribute('viewBox', '0 0 640 640');
  svg.setAttribute('preserveAspectRatio', 'none');
  wrap.appendChild(svg);
  const placedMap = new Map(kps.map(p => [p.name, p]));
  (keypointSchema.edges || []).forEach(([p, c]) => {
    const pA = placedMap.get(p), pB = placedMap.get(c);
    if (!pA || !pB) return;
    const ln = document.createElementNS(SVG_NS, 'line');
    ln.setAttribute('x1', String(pA.x * 640));
    ln.setAttribute('y1', String(pA.y * 640));
    ln.setAttribute('x2', String(pB.x * 640));
    ln.setAttribute('y2', String(pB.y * 640));
    ln.setAttribute('class', 'skeleton-edge');
    svg.appendChild(ln);
  });
  kps.forEach((p, i) => {
    const _hidden = (p.visibility != null && p.visibility < 0.5);
    const dot = document.createElement('div');
    dot.className = 'skeleton-point ' + (_hidden ? 'hidden-pt' : 'placed');
    if (isSelected) dot.dataset.kpIdx = String(i);
    dot.style.left = (p.x * 640) + 'px';
    dot.style.top = (p.y * 640) + 'px';
    const meta = _schemaName(p.name);
    const lbl = meta ? (getLang() === 'en' ? meta.label_en : meta.label_ru) : p.name;
    dot.setAttribute('aria-label', lbl);
    dot.dataset.tooltip = lbl;
    wrap.appendChild(dot);
    const tag = document.createElement('div');
    tag.className = 'skeleton-label';
    tag.style.left = (p.x * 640 + 10) + 'px';
    tag.style.top = (p.y * 640 - 18) + 'px';
    tag.textContent = lbl;
    wrap.appendChild(tag);
  });
  layer.appendChild(wrap);
}

function renderSkeleton() {
  // V8.8.6: если режим выключен — не трогаем DOM вообще.
  if (!skeletonMode) {
    const _l = document.getElementById('skeletonLayer');
    if (_l && _l.firstChild) _l.innerHTML = '';
    return;
  }
  const layer = document.getElementById('skeletonLayer');
  if (!layer) return;
  layer.innerHTML = '';
  _clearSkeletonHint();
  if (!skeletonMode || !keypointSchema) return;

  const selIdx = _targetAnnotationId();

  // V8.5.7: синхронизируем глобальный keypoints ИЗ boxes выделенной рамки.
  // (в V8.5.6 было наоборот — старые точки записывались в новую рамку.)
  if (selIdx >= 0) {
    if (Array.isArray(boxes[selIdx].keypoints)) {
      keypoints = boxes[selIdx].keypoints.map(p => ({...p}));
    } else if (window._kpByIndex && window._kpByIndex[String(selIdx)]) {
      keypoints = window._kpByIndex[String(selIdx)].map(p => ({...p}));
      boxes[selIdx].keypoints = keypoints.map(p => ({...p}));
    } else {
      keypoints = [];
      boxes[selIdx].keypoints = [];
    }
  } else {
    keypoints = [];
  }

  // V8.5.4: рисуем скелет для ВСЕХ рамок на фото.
  boxes.forEach((b, bi) => {
    let kps = null;
    if (bi === selIdx) {
      kps = keypoints;
    } else if (Array.isArray(b.keypoints) && b.keypoints.length) {
      kps = b.keypoints;
    } else if (window._kpByIndex && window._kpByIndex[String(bi)]) {
      kps = window._kpByIndex[String(bi)];
    }
    if (kps && kps.length) {
      _drawSkeletonForBox(layer, kps, bi === selIdx);
    }
  });

  if (selIdx < 0) {
    const hint = document.createElement('div');
    hint.className = 'skeleton-hint';
    hint.textContent = t('skeleton.hint.clickBox');
    layer.appendChild(hint);
    _kpNextHintEl = hint;
    return;
  }

  const next = _nextUnplacedName();
  if (next) {
    const meta = _schemaName(next);
    const lbl = meta ? (getLang() === 'en' ? meta.label_en : meta.label_ru) : next;
    const hint = document.createElement('div');
    hint.className = 'skeleton-hint';
    hint.innerHTML = `${escapeHtml(t('skeleton.hint.next'))}: <b>${escapeHtml(lbl)}</b> · ${escapeHtml(t('skeleton.hint.shift'))} · ${escapeHtml(t('skeleton.hint.rmb'))} · ${escapeHtml(t('skeleton.hint.dbl'))}`;
    layer.appendChild(hint);
    _kpNextHintEl = hint;
  } else {
    const hint = document.createElement('div');
    hint.className = 'skeleton-hint';
    hint.textContent = t('skeleton.hint.done');
    layer.appendChild(hint);
    _kpNextHintEl = hint;
  }
}



async function _reloadKeypointsForImage() {
  keypoints = [];
  if (!currentImageId) { renderSkeleton(); return; }
  try {
    const rows = await api(`/api/images/${currentImageId}/keypoints_by_index`);
    window._kpByIndex = rows || {};
    const idx = _targetAnnotationId();
    if (idx >= 0) keypoints = (window._kpByIndex[String(idx)] || []).map(p => ({...p}));
    else keypoints = [];
  } catch (e) {
    console.warn('keypoints_by_index failed:', e);
    window._kpByIndex = {};
    keypoints = [];
  }
  renderSkeleton();
}

function _syncKeypointsToBox() {
  const idx = _targetAnnotationId();
  if (idx < 0) return;
  boxes[idx].keypoints = keypoints.map(p => ({...p}));
}

// V8.5.3: после undo/redo пересобрать keypoints из boxes.
function _reloadKeypointsFromBox() {
  const idx = _targetAnnotationId();
  if (idx < 0) { keypoints = []; renderSkeleton?.(); return; }
  // V8.5.6: всегда держим boxes[idx].keypoints и keypoints синхронными.
  if (Array.isArray(boxes[idx].keypoints)) {
    keypoints = boxes[idx].keypoints.map(p => ({...p}));
  } else if (window._kpByIndex && window._kpByIndex[String(idx)]) {
    keypoints = window._kpByIndex[String(idx)].map(p => ({...p}));
    boxes[idx].keypoints = keypoints.map(p => ({...p}));
  } else {
    keypoints = [];
    boxes[idx].keypoints = [];
  }
  if (typeof renderSkeleton === 'function') renderSkeleton();
}

function _placeNextKeypoint(nx, ny, visibility) {
  const next = _nextUnplacedName();
  if (!next) {
    setStatus(t('skeleton.status.allPlaced'), 2500);
    return;
  }
  // V8.5.2: visibility = 1.0 (обычная) или 0.0 (скрытая часть тела).
  const vis = (visibility != null) ? visibility : 1.0;
  keypoints.push({ name: next, x: nx, y: ny, visibility: vis });
  _syncKeypointsToBox();
  pushHistory();   // V8.5.3: точка — шаг истории
  markDirty();
  renderSkeleton();
  const meta = _schemaName(next);
  const lbl = meta ? (getLang() === 'en' ? meta.label_en : meta.label_ru) : next;
  setStatus(vis < 0.5 ? t('skeleton.status.placedHidden', { name: lbl })
                      : t('skeleton.status.placed', { name: lbl }), 1500);
  haptic('selection');
}

function _removeLastKeypoint() {
  if (!keypoints.length) return;
  const removed = keypoints.pop();
  _syncKeypointsToBox();
  pushHistory();   // V8.5.3
  markDirty();
  renderSkeleton();
  const meta = _schemaName(removed.name);
  const lbl = meta ? (getLang() === 'en' ? meta.label_en : meta.label_ru) : removed.name;
  setStatus(t('skeleton.status.removed', { name: lbl }), 1500);
}

function isSamModeActive() { return samMode; }
function toggleSamMode() {
  if (!currentImageId) { setStatus(t('toast.pickImage')); return; }
  setSamMode(!samMode);
}
function setSamMode(on) {
  samMode = !!on;
  const btn = document.getElementById('samBtn');
  if (btn) {
    btn.classList.toggle('active', samMode);
    btn.setAttribute('aria-pressed', samMode ? 'true' : 'false');
    const tt = samMode ? 'SAM-режим включён (M / Esc — выйти)' : 'SAM: кликнуть по объекту (M)';
    btn.setAttribute('aria-label', tt);
    btn.dataset.tooltip = tt;
  }
  const vp = document.getElementById('canvasViewport');
  if (vp) vp.classList.toggle('sam-mode', samMode);
  if (samMode) {
    setStatus(t('toast.samHint'));
    haptic('selection');
  } else {
    _clearSamPreview();
  }
}
function _clearSamPreview() {
  samPreview = null;
  const el = document.getElementById('samPreview');
  if (el) el.remove();
}
function _renderSamPreview() {
  // Удаляем предыдущий DOM-элемент превью, но НЕ трогаем samPreview.
  const old = document.getElementById('samPreview');
  if (old) old.remove();

  if (!samPreview || !samPreview.bbox) return;

  const layer = document.getElementById('boxes');
  if (!layer) return;

  const b = samPreview.bbox;
  const box = document.createElement('div');
  box.id = 'samPreview';
  box.className = 'box sam-preview';
  box.setAttribute('aria-hidden', 'true');
  box.style.left   = (b.x * 640) + 'px';
  box.style.top    = (b.y * 640) + 'px';
  box.style.width  = (b.w * 640) + 'px';
  box.style.height = (b.h * 640) + 'px';
  box.style.setProperty('--box-color', 'var(--accent)');

  if (samPreview.mask) {
    const img = document.createElement('img');
    img.className = 'sam-mask';
    img.alt = '';
    img.src = 'data:image/png;base64,' + samPreview.mask;
    img.draggable = false;
    box.appendChild(img);
  }

  const hint = document.createElement('span');
  hint.className = 'sam-hint';
  hint.textContent = `Enter — принять${samPreview.score != null ? ' · ' + Math.round(samPreview.score * 100) + '%' : ''}`;
  box.appendChild(hint);

  layer.appendChild(box);
}
async function _samClickAt(normX, normY) {
  if (!currentImageId || samPointInFlight) return;
  samPointInFlight = true;
  setStatus('<span class="status-spinner"></span>SAM думает…', 0, null, { html: true });
  try {
    const r = await api(`/api/images/${currentImageId}/sam_predict`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points: [{ x: normX, y: normY, positive: true }] }),
    });
    if (!r.found) {
      setStatus(t('toast.samNotFound'), 3000, 'error');
      _clearSamPreview();
      return;
    }
    samPreview = { bbox: r.bbox, mask: r.mask, score: r.score };
    _renderSamPreview();
    setStatus(t('toast.samReady'), 4000, 'success');
    haptic('success');
  } catch (e) {
    haptic('error');
    setError('SAM: ' + String(e.message || e).slice(0, 160), 6000);
  } finally {
    samPointInFlight = false;
  }
}
function _confirmSamPreview() {
  if (!samPreview || !samPreview.bbox) return;
  boxes.push({
    x: samPreview.bbox.x, y: samPreview.bbox.y,
    w: samPreview.bbox.w, h: samPreview.bbox.h,
    label: currentObjectClass(),
    confidence: null, frozen: false,
  });
  selectedIndex = boxes.length - 1;
  multiSelected.clear();
  _clearSamPreview();
  renderBoxes();
  pushHistory();
  markDirty();
  setStatus(t('toast.samAdded'));
  haptic('success');
}
async function _checkSamModel() {
  try {
    const s = await api('/api/sam/status');
    const btn = document.getElementById('samBtn');
    if (btn) btn.title = t('sam.title', { model: s.model });
  } catch (e) {}
}

/* ===== Active learning ===== */
// V7.9.3: debounce — не дёргаем /active_learning на каждое сохранение
// или переключение изображения. Реальный вызов — раз в 1.5 с.
let _alDebounceTimer = null;
function _refreshActiveLearningDebounced() {
  if (_alDebounceTimer) clearTimeout(_alDebounceTimer);
  _alDebounceTimer = setTimeout(() => {
    _alDebounceTimer = null;
    _refreshActiveLearning();
  }, 1500);
}
async function _refreshActiveLearning() {
  if (!currentProjectId || viewMode === 'trash') { _hideActiveLearningBanner(); return; }
  try {
    const s = await api(`/api/projects/${currentProjectId}/active_learning`);
    if (s.show_suggestion && !_activeLearningDismissed && !_isTrashOrProjectEmpty(s)) _showActiveLearningBanner(s);
    else _hideActiveLearningBanner();
  } catch (e) { _hideActiveLearningBanner(); }
}
function _isTrashOrProjectEmpty(s) {
  if (!s) return true;
  return (s.total_images || 0) === 0;
}
function _showActiveLearningBanner(s) {
  const el = document.getElementById('activeLearningBanner');
  if (!el) return;
  const last = s.last_train || {};
  const summary = last.summary || {};
  const newCount = s.new_since_train || 0;
  const lastMap = summary.mAP50 != null ? ` (mAP@50 = ${(summary.mAP50).toFixed(3)})` : '';

  el.innerHTML = '';
  const icon = document.createElement('span');
  icon.className = 'al-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>';
  el.appendChild(icon);
  const body = document.createElement('div');
  body.className = 'al-body';
  const title = document.createElement('div');
  title.className = 'al-title';
  title.textContent = t('activeLearning.title', { n: newCount, map: lastMap });
  body.appendChild(title);
  const sub = document.createElement('div');
  sub.className = 'al-sub';
  sub.textContent = t('activeLearning.sub');
  body.appendChild(sub);
  el.appendChild(body);
  const actions = document.createElement('div');
  actions.className = 'al-actions';
  const laterBtn = document.createElement('button');
  laterBtn.className = 'btn btn-ghost btn-sm';
  laterBtn.textContent = t('activeLearning.later');
  laterBtn.onclick = () => { _activeLearningDismissed = true; _hideActiveLearningBanner(); };
  actions.appendChild(laterBtn);
  const trainBtn = document.createElement('button');
  trainBtn.className = 'btn btn-primary btn-sm';
  trainBtn.textContent = t('activeLearning.train');
  trainBtn.onclick = () => {
    _activeLearningDismissed = true;
    _hideActiveLearningBanner();
    openTrainModal();
  };
  actions.appendChild(trainBtn);
  el.appendChild(actions);
  el.style.display = 'flex';
  el.classList.add('visible');
}
function _hideActiveLearningBanner() {
  const el = document.getElementById('activeLearningBanner');
  if (!el) return;
  el.classList.remove('visible');
  el.style.display = 'none';
}

/* ===== Metrics ===== */
// V8.1.0: сравнение двух прогонов обучения side-by-side.
async function openModelCompare() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  let list;
  try { list = await api('/api/train/runs?project_id=' + currentProjectId); }
  catch (e) { setError('Не удалось получить список прогонов'); return; }
  if (!list.items || list.items.length < 2) {
    setStatus('Нужно минимум 2 прогона обучения для сравнения');
    return;
  }
  const body = document.getElementById('metricsBody');
  document.getElementById('metricsTitle').textContent = 'Сравнение моделей';
  body.innerHTML = '';
  const mkSelect = (side) => {
    const sel = document.createElement('select');
    sel.style.cssText = 'flex:1;padding:8px 12px;border-radius:10px;border:1px solid var(--hairline-strong);background:var(--bg-surface);color:var(--text-primary);';
    list.items.forEach((r, i) => {
      const o = document.createElement('option');
      o.value = r.folder;
      o.textContent = `${r.model_name || r.run_id} · mAP@50 ${((r.summary||{}).mAP50 || 0).toFixed(3)}`;
      if (i === (side === 'L' ? 0 : 1)) o.selected = true;
      sel.appendChild(o);
    });
    return sel;
  };
  const leftSel = mkSelect('L'); const rightSel = mkSelect('R');
  const wrapSel = document.createElement('div');
  wrapSel.style.cssText = 'display:flex;gap:8px;margin-bottom:16px;';
  wrapSel.appendChild(leftSel); wrapSel.appendChild(rightSel);
  body.appendChild(wrapSel);
  const grid = document.createElement('div');
  grid.id = 'modelCompareGrid';
  grid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:16px;';
  body.appendChild(grid);
  async function render() {
    grid.innerHTML = '';
    for (const folder of [leftSel.value, rightSel.value]) {
      const col = document.createElement('div');
      col.id = 'modelCompareCol-' + folder;
      col.style.cssText = 'min-width:0;';
      col.innerHTML = '<div style="color:var(--text-secondary);font-size:0.8125rem;">Загрузка…</div>';
      grid.appendChild(col);
      try {
        const m = await api(`/api/train/runs/${encodeURIComponent(folder)}/metrics`);
        col.innerHTML = '';
        const meta = m.metadata || {};
        const summary = meta.summary || {};
        const head = document.createElement('div');
        head.innerHTML = `<div style="font-weight:600;margin-bottom:8px;">${escapeHtml(meta.model_name || folder)}</div>
          <div style="font-size:0.75rem;color:var(--text-secondary);margin-bottom:8px;">${escapeHtml(meta.created_at || '')} · ${meta.annotated_count || 0} фото</div>`;
        col.appendChild(head);
        const cards = document.createElement('div');
        cards.className = 'metrics-cards';
        const items2 = [
          ['mAP@50', summary.mAP50],
          ['mAP@50-95', summary.mAP50_95],
          ['Precision', summary.precision],
          ['Recall', summary.recall],
          ['Лучшая эпоха', summary.best_epoch],
        ];
        items2.forEach(([lbl, v]) => {
          const c = document.createElement('div'); c.className = 'metrics-card';
          const vv = document.createElement('div'); vv.className = 'metrics-card-value';
          vv.textContent = v != null ? (typeof v === 'number' ? v.toFixed(3) : String(v)) : '—';
          const ll = document.createElement('div'); ll.className = 'metrics-card-label'; ll.textContent = lbl;
          c.appendChild(vv); c.appendChild(ll); cards.appendChild(c);
        });
        col.appendChild(cards);
        if ((m.epochs || []).length) {
          col.appendChild(_renderMetricsChart({
            title: 'mAP', yMin: 0, yMax: 1,
            series: [
              { label: 'mAP@50', color: 'var(--accent)', values: m.epochs.map(e => e.mAP50) },
              { label: 'mAP@50-95', color: 'var(--success)', values: m.epochs.map(e => e.mAP50_95) },
            ],
            xLabels: m.epochs.map(e => e.epoch),
          }));
        }
      } catch (e) {
        col.innerHTML = '<div style="color:var(--danger);">Ошибка: ' + escapeHtml(String(e.message)) + '</div>';
      }
    }
  }
  leftSel.onchange = render; rightSel.onchange = render;
  openModal('metricsModal');
  await render();
}

async function openMetricsModal(runFolder) {
  const title = document.getElementById('metricsTitle');
  const body = document.getElementById('metricsBody');
  if (!body) return;
  title.textContent = t('metrics.title');
  body.innerHTML = `<p style="color:var(--text-secondary);font-size:0.8125rem;padding:8px 0;">${t('common.loading')}</p>`;
  openModal('metricsModal');
  try {
    let folder = runFolder;
    if (!folder) {
      const list = await api('/api/train/runs?project_id=' + currentProjectId);
      if (!list.items.length) {
        body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;padding:12px 0;text-align:center;">Пока нет ни одного обучения.</p>';
        return;
      }
      folder = list.items[0].folder;
    }
    const m = await api(`/api/train/runs/${encodeURIComponent(folder)}/metrics`);
    _renderMetrics(body, folder, m);
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger);">Ошибка: ' + escapeHtml(String(e.message || e)) + '</p>';
  }
}
function closeMetricsModal() { closeModal('metricsModal'); }
function _renderMetrics(body, folder, m) {
  body.innerHTML = '';
  const meta = m.metadata || {};
  const summary = meta.summary || {};
  const epochs = m.epochs || [];
  const header = document.createElement('div');
  header.className = 'metrics-header';
  header.innerHTML = `
    <div class="metrics-meta">
      <div class="metrics-meta-row"><span>${t('metrics.run')}:</span><b>${escapeHtml(meta.run_id || folder)}</b></div>
      <div class="metrics-meta-row"><span>${t('metrics.class')}:</span><b>${escapeHtml(meta.object_class || '—')}</b></div>
      <div class="metrics-meta-row"><span>${t('metrics.annotated')}:</span><b>${meta.annotated_count != null ? meta.annotated_count : '—'}</b></div>
      <div class="metrics-meta-row"><span>${t('metrics.model')}:</span><b>${escapeHtml(meta.model_name || '—')}</b></div>
      <div class="metrics-meta-row"><span>${t('metrics.date')}:</span><b>${meta.created_at ? escapeHtml(meta.created_at.replace('T',' ').slice(0,19)) : '—'}</b></div>
    </div>`;
  body.appendChild(header);
  if (!epochs.length) {
    const e = document.createElement('p');
    e.style.cssText = 'color:var(--text-secondary);font-size:0.8125rem;padding:12px 0;text-align:center;';
    e.textContent = t('metrics.noData');
    body.appendChild(e);
  } else {
    const cards = document.createElement('div');
    cards.className = 'metrics-cards';
    const items = [
      { label: t('metrics.bestEpoch'), value: summary.best_epoch != null ? String(summary.best_epoch) : '—' },
      { label: 'mAP@50', value: summary.mAP50 != null ? summary.mAP50.toFixed(3) : '—' },
      { label: 'mAP@50-95', value: summary.mAP50_95 != null ? summary.mAP50_95.toFixed(3) : '—' },
      { label: 'Precision', value: summary.precision != null ? summary.precision.toFixed(3) : '—' },
      { label: 'Recall', value: summary.recall != null ? summary.recall.toFixed(3) : '—' },
    ];
    items.forEach(it => {
      const c = document.createElement('div');
      c.className = 'metrics-card';
      const v = document.createElement('div');
      v.className = 'metrics-card-value'; v.textContent = it.value;
      const l = document.createElement('div');
      l.className = 'metrics-card-label'; l.textContent = it.label;
      c.appendChild(v); c.appendChild(l);
      cards.appendChild(c);
    });
    body.appendChild(cards);
    body.appendChild(_renderMetricsChart({
      title: t('metrics.mapTitle'), yMin: 0, yMax: 1,
      series: [
        { label: 'mAP@50', color: 'var(--accent)', values: epochs.map(e => e.mAP50) },
        { label: 'mAP@50-95', color: 'var(--success)', values: epochs.map(e => e.mAP50_95) },
      ],
      xLabels: epochs.map(e => e.epoch),
    }));
    body.appendChild(_renderMetricsChart({
      title: t('metrics.prTitle'), yMin: 0, yMax: 1,
      series: [
        { label: 'Precision', color: 'var(--warning)', values: epochs.map(e => e.precision) },
        { label: 'Recall', color: '#ff2d55', values: epochs.map(e => e.recall) },
      ],
      xLabels: epochs.map(e => e.epoch),
    }));
    body.appendChild(_renderMetricsChart({
      title: t('metrics.lossTitle'), yMin: null, yMax: null,
      series: [
        { label: 'train box', color: 'var(--accent)', values: epochs.map(e => e.train_box_loss) },
        { label: 'val box', color: 'var(--danger)', values: epochs.map(e => e.val_box_loss) },
      ],
      xLabels: epochs.map(e => e.epoch),
    }));
  }
  if (folder) {
    const cmWrap = document.createElement('div');
    cmWrap.className = 'metrics-image-block';
    const t = document.createElement('div');
    t.className = 'stats-section-title'; t.textContent = t('metrics.confusion');
    cmWrap.appendChild(t);
    const img = document.createElement('img');
    img.className = 'metrics-image'; img.loading = 'lazy'; img.alt = 'Confusion matrix';
    img.src = `/api/train/runs/${encodeURIComponent(folder)}/file/confusion_matrix.png`;
    img.onerror = () => { cmWrap.style.display = 'none'; };
    cmWrap.appendChild(img);
    body.appendChild(cmWrap);

    const predWrap = document.createElement('div');
    predWrap.className = 'metrics-image-block';
    const t2 = document.createElement('div');
    t2.className = 'stats-section-title'; t2.textContent = t('metrics.valPred');
    predWrap.appendChild(t2);
    const pimg = document.createElement('img');
    pimg.className = 'metrics-image'; pimg.loading = 'lazy'; pimg.alt = 'Validation predictions';
    pimg.src = `/api/train/runs/${encodeURIComponent(folder)}/file/val_batch0_pred.jpg`;
    pimg.onerror = () => { predWrap.style.display = 'none'; };
    predWrap.appendChild(pimg);
    body.appendChild(predWrap);
  }
}
function _renderMetricsChart({ title, yMin, yMax, series, xLabels }) {
  const wrap = document.createElement('div');
  wrap.className = 'metrics-chart-block';
  const t = document.createElement('div');
  t.className = 'stats-section-title'; t.textContent = title;
  wrap.appendChild(t);

  const W = 620, H = 200, PAD_L = 44, PAD_R = 12, PAD_T = 12, PAD_B = 24;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const n = series[0].values.length;
  let allVals = [];
  series.forEach(s => allVals = allVals.concat(s.values.filter(v => v != null)));
  let lo = yMin, hi = yMax;
  if (lo == null) lo = Math.min(...allVals, 0);
  if (hi == null) hi = Math.max(...allVals, 1);
  if (hi === lo) hi = lo + 1;
  const range = hi - lo;

  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('class', 'metrics-chart');
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

  const ticksY = 4;
  for (let i = 0; i <= ticksY; i++) {
    const yVal = lo + (range * i / ticksY);
    const y = PAD_T + plotH - (i / ticksY) * plotH;
    const ln = document.createElementNS(svgNS, 'line');
    ln.setAttribute('x1', PAD_L); ln.setAttribute('x2', W - PAD_R);
    ln.setAttribute('y1', y); ln.setAttribute('y2', y);
    ln.setAttribute('stroke', 'currentColor');
    ln.setAttribute('stroke-opacity', '0.08');
    svg.appendChild(ln);
    const txt = document.createElementNS(svgNS, 'text');
    txt.setAttribute('x', PAD_L - 6);
    txt.setAttribute('y', y + 3);
    txt.setAttribute('text-anchor', 'end');
    txt.setAttribute('class', 'metrics-chart-axis');
    txt.textContent = yVal.toFixed(2);
    svg.appendChild(txt);
  }
  series.forEach(s => {
    let d = '';
    for (let i = 0; i < n; i++) {
      const v = s.values[i];
      if (v == null) continue;
      const x = PAD_L + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
      const y = PAD_T + plotH - ((v - lo) / range) * plotH;
      d += (d ? ' L ' : 'M ') + x.toFixed(2) + ' ' + y.toFixed(2);
    }
    const path = document.createElementNS(svgNS, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', s.color);
    path.setAttribute('stroke-width', '2');
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('stroke-linecap', 'round');
    svg.appendChild(path);
  });
  if (n > 0) {
    const labels = [xLabels[0], xLabels[Math.floor((n - 1) / 2)], xLabels[n - 1]];
    const xs = [PAD_L, PAD_L + plotW / 2, PAD_L + plotW];
    labels.forEach((lbl, i) => {
      const txt = document.createElementNS(svgNS, 'text');
      txt.setAttribute('x', xs[i]);
      txt.setAttribute('y', H - 6);
      txt.setAttribute('text-anchor', i === 0 ? 'start' : (i === 2 ? 'end' : 'middle'));
      txt.setAttribute('class', 'metrics-chart-axis');
      txt.textContent = 'эп. ' + lbl;
      svg.appendChild(txt);
    });
  }
  wrap.appendChild(svg);
  const legend = document.createElement('div');
  legend.className = 'metrics-chart-legend';
  series.forEach(s => {
    const item = document.createElement('span');
    item.className = 'metrics-legend-item';
    const dot = document.createElement('span');
    dot.className = 'metrics-legend-dot';
    dot.style.background = s.color;
    item.appendChild(dot);
    const lbl = document.createElement('span');
    lbl.textContent = s.label;
    item.appendChild(lbl);
    legend.appendChild(item);
  });
  wrap.appendChild(legend);
  return wrap;
}

/* ===== Storage ===== */
async function _refreshStorageInfo() {
  const wrap = document.getElementById('storageInfo');
  if (!wrap) return;
  wrap.innerHTML = '<div class="storage-loading">Загрузка…</div>';
  try {
    const info = await api('/api/storage/info');
    _renderStorageInfo(info);
  } catch (e) {
    wrap.innerHTML = '<div class="storage-error">Ошибка: ' + escapeHtml(String(e.message || e)) + '</div>';
  }
}
function _renderStorageInfo(info) {
  const wrap = document.getElementById('storageInfo');
  if (!wrap) return;
  wrap.innerHTML = '';

  const engineRow = document.createElement('div');
  engineRow.className = 'storage-row';
  engineRow.innerHTML = `<span class="storage-key">${t('storage.engine')}</span><span class="storage-val">${escapeHtml(info.engine.toUpperCase())}</span>`;
  wrap.appendChild(engineRow);

  const pathRow = document.createElement('div');
  pathRow.className = 'storage-row';
  if (info.engine === 'sqlite') {
    pathRow.innerHTML = `<span class="storage-key">${t('storage.dbFile')}</span><span class="storage-val mono">${escapeHtml(info.db_path || '—')}</span>`;
  } else {
    pathRow.innerHTML = `<span class="storage-key">${t('storage.mysql')}</span><span class="storage-val mono">${escapeHtml((info.db_host || '') + '/' + (info.db_name || ''))}</span>`;
  }
  wrap.appendChild(pathRow);

  const dbSizeRow = document.createElement('div');
  dbSizeRow.className = 'storage-row';
  dbSizeRow.innerHTML = `<span class="storage-key">${t('storage.dbSize')}</span><span class="storage-val">${_fmtBytes(info.db_size)}</span>`;
  wrap.appendChild(dbSizeRow);

  const dirs = info.dirs || {};
  const dirLabels = {
    uploads: t('storage.dir.uploads'), thumbs: t('storage.dir.thumbs'),
    models: t('storage.dir.models'), videos: t('storage.dir.videos'),
    backups: t('storage.dir.backups'), exports: t('storage.dir.exports'),
    runs: t('storage.dir.runs'),
  };
  const dirsWrap = document.createElement('details');
  dirsWrap.className = 'storage-details';
  const sum = document.createElement('summary');
  sum.textContent = `${t('storage.data')}: ${_fmtBytes(info.total_size - (info.db_size || 0))}`;
  dirsWrap.appendChild(sum);
  const ul = document.createElement('div');
  ul.className = 'storage-dir-list';
  Object.entries(dirs).forEach(([k, v]) => {
    if (!v) return;
    const row = document.createElement('div');
    row.className = 'storage-dir-row';
    row.innerHTML = `<span>${dirLabels[k] || k}</span><b>${_fmtBytes(v)}</b>`;
    ul.appendChild(row);
  });
  dirsWrap.appendChild(ul);
  wrap.appendChild(dirsWrap);

  const rootRow = document.createElement('div');
  rootRow.className = 'storage-row';
  rootRow.innerHTML = `<span class="storage-key">DATA_ROOT</span><span class="storage-val mono">${escapeHtml(info.data_root || '—')}</span>`;
  wrap.appendChild(rootRow);

  const btnRow = document.createElement('div');
  btnRow.className = 'storage-actions';
  const btnBackup = document.createElement('button');
  btnBackup.className = 'btn btn-ghost btn-sm';
  btnBackup.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
         style="margin-right:6px;" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
    ${t('storage.downloadDb')}`;
  btnBackup.onclick = () => _downloadDbBackup(btnBackup);
  btnRow.appendChild(btnBackup);
  const btnRefresh = document.createElement('button');
  btnRefresh.className = 'btn btn-ghost btn-sm';
  btnRefresh.textContent = t('storage.refresh');
  btnRefresh.onclick = () => _refreshStorageInfo();
  btnRow.appendChild(btnRefresh);
  wrap.appendChild(btnRow);

  _renderMigrationBlock(info, wrap);
}
async function _downloadDbBackup(btn) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = 'Готовим…';
  try {
    const res = await fetch('/api/storage/backup_db', { method: 'POST', headers: { 'X-Requested-With': 'DatasetBuilder' } });
    if (!res.ok) {
      let msg = 'Ошибка';
      try { msg = (await res.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename="?([^"]+)"?/.exec(cd);
    const name = m ? m[1] : 'dataset_backup.db';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
    setSuccess('Скачано: ' + name, 4000);
    haptic('success');
  } catch (e) {
    setError('Ошибка: ' + String(e.message || e).slice(0, 180));
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}
async function _renderMigrationBlock(info, wrap) {
  if (!info.can_migrate_to_sqlite) return;
  const block = document.createElement('div');
  block.className = 'storage-migrate-block';
  block.id = 'storageMigrateBlock';

  const title = document.createElement('div');
  title.className = 'settings-group-title';
  title.style.marginTop = '10px';
  title.textContent = t('storage.migration');
  block.appendChild(title);

  const desc = document.createElement('p');
  desc.className = 'form-hint';
  desc.style.marginBottom = '10px';
  desc.textContent = t('storage.migration.desc');
  block.appendChild(desc);

  const targetRow = document.createElement('div');
  targetRow.className = 'storage-row';
  targetRow.innerHTML = `<span class="storage-key">${t('storage.migration.target')}</span>
    <span class="storage-val mono">${escapeHtml(info.migration_target || '—')}</span>`;
  block.appendChild(targetRow);

  const actions = document.createElement('div');
  actions.className = 'storage-actions';
  const btnMigrate = document.createElement('button');
  btnMigrate.className = 'btn btn-primary btn-sm';
  btnMigrate.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
         style="margin-right:6px;" aria-hidden="true">
      <path d="M4 4v6h6"/>
      <path d="M20 20v-6h-6"/>
      <path d="M4 10a16 16 0 0 1 16 0"/>
      <path d="M20 14a16 16 0 0 1-16 0"/>
    </svg>
    ${t('storage.migration.go')}`;
  btnMigrate.onclick = () => _startMigration(info.migration_target);
  actions.appendChild(btnMigrate);
  block.appendChild(actions);

  const status = document.createElement('div');
  status.className = 'storage-migrate-status';
  status.id = 'storageMigrateStatus';
  status.style.display = 'none';
  block.appendChild(status);
  wrap.appendChild(block);

  try {
    const s = await api('/api/storage/migrate/status');
    if (s.status !== 'idle') {
      _renderMigrationStatus(s);
      if (s.status === 'running') _pollMigration();
    }
  } catch (e) {}
}
function _renderMigrationStatus(s) {
  const el = document.getElementById('storageMigrateStatus');
  if (!el) return;
  el.style.display = 'block';
  el.classList.remove('migrate-ok', 'migrate-error', 'migrate-running');
  const pct = Math.round(s.progress || 0);
  if (s.status === 'running') {
    el.classList.add('migrate-running');
    el.innerHTML = `
      <div class="migrate-row">
        <span class="migrate-spinner"></span>
        <span>${escapeHtml(s.message || t('migrate.running'))}</span>
        <b>${pct}%</b>
      </div>
      <div class="migrate-track"><div class="migrate-fill" style="width:${pct}%"></div></div>
    `;
    return;
  }
  if (s.status === 'done') {
    el.classList.add('migrate-ok');
    const stats = s.stats && s.stats.copied ? s.stats.copied : {};
    const total = Object.values(stats).reduce((a, b) => a + (b || 0), 0);
    el.innerHTML = `
      <div class="migrate-row"><b>${t('migrate.done')}</b></div>
      <div style="font-size:0.75rem;color:var(--text-secondary);margin-top:6px;">
        ${t('migrate.done.rows', { n: total })}<br>
        ${t('migrate.done.file', { path: escapeHtml(s.target_path || '') })}<br>
        ${s.env_updated ? t('migrate.env.saved') : '<span style="color:var(--warning)">' + t('migrate.env.missing') + '</span>'}
      </div>
      <div class="migrate-restart-hint"><b>${t('migrate.restart')}</b></div>
    `;
    return;
  }
  if (s.status === 'error') {
    el.classList.add('migrate-error');
    el.innerHTML = `
      <div class="migrate-row"><b>${t('migrate.error')}</b></div>
      <div style="font-size:0.75rem;margin-top:6px;word-break:break-word;">
        ${escapeHtml(s.error || s.message || '—')}
      </div>
      <div style="margin-top:8px;">
        <button class="btn btn-ghost btn-sm" onclick="_resetMigrationState()">${t('migrate.reset')}</button>
      </div>
    `;
    return;
  }
}
async function _startMigration(targetPath) {
  const ok = await showConfirm(
    t('confirm.migrate.title'),
    t('confirm.migrate.text', { path: targetPath }),
    { okText: t('confirm.migrate.ok') }
  );
  if (!ok) return;
  let overwrite = false;
  try {
    const s = await api('/api/storage/migrate/status');
    if (s.target_exists) {
      const ow = await showConfirm(
        t('confirm.migrateExists.title'),
        t('confirm.migrateExists.text', { path: s.target_path }),
        { okText: t('confirm.migrateExists.ok'), danger: true }
      );
      if (!ow) return;
      overwrite = true;
    }
  } catch (e) {}
  const el = document.getElementById('storageMigrateStatus');
  if (el) {
    el.style.display = 'block';
    el.className = 'storage-migrate-status migrate-running';
    el.innerHTML = `
      <div class="migrate-row">
        <span class="migrate-spinner"></span>
        <span>${t('migrate.launching')}</span>
        <b>0%</b>
      </div>
      <div class="migrate-track"><div class="migrate-fill" style="width:0%"></div></div>
    `;
  }
  try {
    await api('/api/storage/migrate/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_path: targetPath, overwrite }),
    });
    setStatus(t('toast.migrationStarted'), 5000);
    haptic('warning');
    _pollMigration();
  } catch (e) {
    setError(t('migrate.errorStart', { msg: String(e.message || e).slice(0, 200) }));
    _renderMigrationStatus({ status: 'error', error: String(e.message || e) });
  }
}
async function _resetMigrationState() {
  try {
    await api('/api/storage/migrate/reset', { method: 'POST' });
    _refreshStorageInfo();
  } catch (e) {
    setError('Не удалось сбросить: ' + String(e.message || e).slice(0, 120));
  }
}
function _pollMigration() {
  if (_migratePollTimer) clearTimeout(_migratePollTimer);
  const tick = async () => {
    try {
      const s = await api('/api/storage/migrate/status');
      _renderMigrationStatus(s);
      if (s.status === 'running') _migratePollTimer = setTimeout(tick, 700);
      else {
        _migratePollTimer = null;
        if (s.status === 'done') {
          setSuccess(t('toast.migrationDone'), 8000);
          haptic('success');
          _refreshStorageInfo();
        } else if (s.status === 'error') {
          setError(t('migrate.errorFailed', { msg: String(s.error || '').slice(0, 200) }), 8000);
        }
      }
    } catch (e) { _migratePollTimer = setTimeout(tick, 1500); }
  };
  tick();
}

/* ===== File operations ===== */
async function openBulkRename() {
  const n = selectedForDelete.size;
  if (!n) { setStatus('Сначала выдели изображения'); return; }
  const pattern = await showPrompt(
    t('prompt.bulkRename.title', { n }),
    {
      text: t('prompt.bulkRename.text'),
      defaultValue: 'image_{n:04d}',
      hint: t('prompt.bulkRename.hint'),
      okText: t('prompt.bulkRename.ok'),
    }
  );
  if (pattern === null) return;
  const startStr = await showPrompt(
    t('prompt.bulkRename.startTitle'),
    { defaultValue: '1', okText: t('common.ok') }
  );
  if (startStr === null) return;
  const start = parseInt(startStr, 10) || 1;
  try {
    const r = await api('/api/images/bulk_rename', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_ids: Array.from(selectedForDelete),
        pattern: String(pattern),
        start,
      }),
    });
    await loadImages();
    setStatus(`Переименовано: ${r.renamed}` + (r.failed_count ? `, пропущено: ${r.failed_count}` : ''), 5000);
    haptic('success');
  } catch (e) {
    setError('Ошибка: ' + String(e.message).slice(0, 160));
  }
}
async function openMoveCopyDialog(mode) {
  const n = selectedForDelete.size;
  if (!n) { setStatus('Сначала выдели изображения'); return; }
  const projects = _cachedProjectsList.filter(p => p.id !== currentProjectId);
  if (!projects.length) { setStatus('Нет других проектов — создай новый'); return; }
  const sel = document.createElement('select');
  sel.style.cssText = 'width:100%; padding:10px 14px; border-radius:10px; border:1px solid var(--hairline-strong); background:var(--bg-surface); color:var(--text-primary); font-family:inherit; font-size:0.875rem;';
  projects.forEach(p => {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = `${p.name} (${p.object_class || 'pig'}) — ${p.images_count} фото`;
    sel.appendChild(o);
  });
  const wrap = document.createElement('div');
  wrap.appendChild(sel);
  const title = mode === 'copy' ? `Скопировать ${n} ${pluralImages(n)}` : `Переместить ${n} ${pluralImages(n)}`;
  const body = mode === 'copy'
    ? 'Будут созданы новые файлы, оригиналы останутся.'
    : 'Файлы переедут в другой проект. Разметка сохранится, класс будет перезаписан.';
  const res = await _openCustomDialog({
    title, bodyText: body, selectorEl: wrap,
    okText: mode === 'copy' ? 'Скопировать' : 'Переместить',
  });
  if (!res) return;
  const targetId = parseInt(sel.value, 10);
  try {
    const url = mode === 'copy' ? '/api/images/bulk_copy_to_project' : '/api/images/bulk_move_to_project';
    const r = await api(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_ids: Array.from(selectedForDelete),
        target_project_id: targetId,
      }),
    });
    selectedForDelete.clear();
    await loadProjects();
    await loadImages();
    setStatus(`Готово: ${r.moved} изображений`, 5000);
    haptic('success');
  } catch (e) {
    setError('Ошибка: ' + String(e.message).slice(0, 180));
  }
}
async function openDuplicatesModal() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const body = document.getElementById('duplicatesBody');
  if (!body) return;
  body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;padding:8px 0;">Ищу дубликаты…</p>';
  openModal('duplicatesModal');
  try {
    const r = await api(`/api/projects/${currentProjectId}/duplicates`);
    body.innerHTML = '';
    if (!r.groups.length) {
      body.innerHTML = '<p style="color:var(--success);font-size:0.875rem;text-align:center;padding:24px 0;">✓ Дубликатов не найдено</p>';
      return;
    }
    const head = document.createElement('p');
    head.style.cssText = 'color:var(--text-secondary);font-size:0.75rem;margin:0 0 12px;';
    head.textContent = t('duplicates.found', { n: r.total, word: pluralGroups(r.total) });
    body.appendChild(head);
    r.groups.slice(0, 50).forEach((g, gi) => {
      const groupEl = document.createElement('div');
      groupEl.className = 'duplicates-group';
      const header = document.createElement('div');
      header.className = 'duplicates-group-header';
      header.textContent = t('duplicates.groupHeader', { gi: gi + 1, n: g.items.length });
      groupEl.appendChild(header);
      const grid = document.createElement('div');
      grid.className = 'duplicates-grid';
      g.items.forEach(it => {
        const card = document.createElement('div');
        card.className = 'duplicates-card';
        if (it.id === g.representative_id) card.classList.add('representative');
        const img = document.createElement('img');
        img.className = 'duplicates-thumb'; img.loading = 'lazy'; img.alt = '';
        img.src = `/api/images/${it.id}/thumb`;
        card.appendChild(img);
        const name = document.createElement('div');
        name.className = 'duplicates-name'; name.textContent = it.filename;
        name.dataset.tooltip = it.filename;
        card.appendChild(name);
        const meta = document.createElement('div');
        meta.className = 'duplicates-meta'; meta.textContent = fmtSize(it.file_size || 0);
        card.appendChild(meta);
        if (it.id === g.representative_id) {
          const badge = document.createElement('span');
          badge.className = 'duplicates-badge'; badge.textContent = t('duplicates.representative');
          card.appendChild(badge);
        }
        const actions = document.createElement('div');
        actions.className = 'duplicates-actions';
        const delBtn = document.createElement('button');
        delBtn.className = 'btn btn-ghost btn-sm'; delBtn.textContent = t('duplicates.toTrash');
        delBtn.onclick = async () => {
          await deleteImage(it.id, it.filename);
          card.style.opacity = '0.4';
          card.style.pointerEvents = 'none';
        };
        actions.appendChild(delBtn);
        const openBtn = document.createElement('button');
        openBtn.className = 'btn btn-ghost btn-sm'; openBtn.textContent = t('duplicates.open');
        openBtn.onclick = async () => {
          closeDuplicatesModal();
          await selectImage(it.id, { skipDirtyCheck: true });
        };
        actions.appendChild(openBtn);
        card.appendChild(actions);
        grid.appendChild(card);
      });
      groupEl.appendChild(grid);
      body.appendChild(groupEl);
    });
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger);">Ошибка: ' + escapeHtml(String(e.message || e)) + '</p>';
  }
}
function closeDuplicatesModal() { closeModal('duplicatesModal'); }
function toggleFileOpsMenu(e, closeOnly) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('fileOpsMenu');
  if (!menu) return;
  if (closeOnly) { menu.classList.remove('open'); return; }
  const btn = document.getElementById('fileOpsBtn');
  const isOpen = menu.classList.contains('open');
  closeAllPopovers(null);
  if (isOpen) return;
  const r = btn.getBoundingClientRect();
  const W = 240;
  let left = r.left;
  if (left + W > window.innerWidth - 8) left = Math.max(8, window.innerWidth - W - 8);
  menu.style.position = 'fixed';
  menu.style.left = left + 'px';
  menu.style.top = (r.bottom + 6) + 'px';
  menu.style.minWidth = W + 'px';
  menu.style.zIndex = '500';
  menu.classList.add('open');
}

/* ===== FFmpeg ===== */
async function _refreshFfmpegStatus() {
  const wrap = document.getElementById('ffmpegStatus');
  if (!wrap) return;
  wrap.innerHTML = `<div class="storage-loading">${t('ffmpeg.checking')}</div>`;
  try {
    const r = await api('/api/system/ffmpeg');
    _renderFfmpegStatus(r);
  } catch (e) {
    wrap.innerHTML = '<div class="storage-error">Ошибка: ' + escapeHtml(String(e.message || e)) + '</div>';
  }
}
function _renderFfmpegStatus(r) {
  const wrap = document.getElementById('ffmpegStatus');
  if (!wrap) return;
  wrap.innerHTML = '';

  const row = document.createElement('div');
  row.className = 'storage-row';
  const label = document.createElement('span');
  label.className = 'storage-key'; label.textContent = 'FFmpeg';
  row.appendChild(label);
  const val = document.createElement('span');
  val.className = 'storage-val';
  if (r.ok) { val.style.color = 'var(--success)'; val.textContent = t('ffmpeg.ok'); }
  else { val.style.color = 'var(--danger)'; val.textContent = t('ffmpeg.missing'); }
  row.appendChild(val);
  wrap.appendChild(row);

  if (r.ok && r.ffmpeg) {
    const pathRow = document.createElement('div');
    pathRow.className = 'storage-row';
    pathRow.innerHTML = `<span class="storage-key">${t('ffmpeg.path')}</span>
      <span class="storage-val mono">${escapeHtml(r.ffmpeg)}</span>`;
    wrap.appendChild(pathRow);
  }

  const actions = document.createElement('div');
  actions.className = 'storage-actions';

  const helpBtn = document.createElement('button');
  helpBtn.className = 'btn btn-ghost btn-sm';
  helpBtn.textContent = r.ok ? t('ffmpeg.howReplace') : t('ffmpeg.howInstall');
  helpBtn.onclick = () => openFfmpegHelp(r);
  actions.appendChild(helpBtn);

  const setBtn = document.createElement('button');
  setBtn.className = 'btn btn-ghost btn-sm';
  setBtn.textContent = t('ffmpeg.setPath');
  setBtn.onclick = () => setFfmpegPathManually(r);
  actions.appendChild(setBtn);

  if (r.ok) {
    const recheckBtn = document.createElement('button');
    recheckBtn.className = 'btn btn-ghost btn-sm';
    recheckBtn.textContent = t('ffmpeg.recheck');
    recheckBtn.onclick = () => {
      _refreshFfmpegStatus();
      if (typeof checkVideoCapabilities === 'function') checkVideoCapabilities();
    };
    actions.appendChild(recheckBtn);
  }
  wrap.appendChild(actions);
}
function openFfmpegHelp(r) {
  const body = document.getElementById('ffmpegHelpBody');
  if (!body) return;
  body.innerHTML = '';

  const intro = document.createElement('p');
  intro.style.cssText = 'font-size:0.8125rem;color:var(--text-secondary);margin:0 0 12px;line-height:1.5;';
  intro.textContent = t('ffmpegHelp.intro');
  body.appendChild(intro);

  const osLabel = { mac: 'macOS', win: 'Windows', linux: 'Linux' }[r.os] || r.os;

  const block = document.createElement('div');
  block.className = 'ffmpeg-help-block';
  block.innerHTML = `
    <div class="ffmpeg-help-os">${t('ffmpegHelp.quick')} · ${escapeHtml(osLabel)}</div>
    <div class="ffmpeg-help-step"><b>1.</b> ${t('ffmpegHelp.step.open')}</div>
    <div class="ffmpeg-help-step"><b>2.</b> ${t('ffmpegHelp.step.run')}</div>
    <div class="ffmpeg-help-cmd"><code>${escapeHtml(r.cmd || '')}</code></div>
    <div class="ffmpeg-help-step" style="margin-top:10px;"><b>3.</b> ${t('ffmpegHelp.step.wait')}</div>
    <div class="ffmpeg-help-step"><b>4.</b> ${t('ffmpegHelp.step.recheck')}</div>
  `;
  body.appendChild(block);

  if (r.os === 'win') {
    const alt = document.createElement('div');
    alt.className = 'ffmpeg-help-block';
    alt.innerHTML = `
      <div class="ffmpeg-help-os">${t('ffmpegHelp.manualWin')}</div>
      <div class="ffmpeg-help-step"><b>1.</b> <a href="https://www.gyan.dev/ffmpeg/builds/" target="_blank" rel="noopener">${t('ffmpegHelp.manualWin.s1')}</a>.</div>
      <div class="ffmpeg-help-step"><b>2.</b> ${t('ffmpegHelp.manualWin.s2')}</div>
      <div class="ffmpeg-help-step"><b>3.</b> ${t('ffmpegHelp.manualWin.s3')}</div>
    `;
    body.appendChild(alt);
  } else {
    const alt = document.createElement('div');
    alt.className = 'ffmpeg-help-block';
    alt.innerHTML = `
      <div class="ffmpeg-help-os">${t('ffmpegHelp.alt')}</div>
      <div class="ffmpeg-help-step">${escapeHtml(r.cmd_alt || '')}</div>
      <div class="ffmpeg-help-step" style="margin-top:8px;">${t('ffmpegHelp.alt.hint')}</div>
    `;
    body.appendChild(alt);
  }

  const actions = document.createElement('div');
  actions.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:12px;';
  const setPathBtn = document.createElement('button');
  setPathBtn.className = 'btn btn-primary';
  setPathBtn.textContent = t('ffmpegHelp.setPathBtn');
  setPathBtn.onclick = () => { closeFfmpegHelp(); setFfmpegPathManually(r); };
  actions.appendChild(setPathBtn);
  body.appendChild(actions);
  openModal('ffmpegHelpModal');
}
function closeFfmpegHelp() { closeModal('ffmpegHelpModal'); }
async function setFfmpegPathManually(r) {
  const cur = (r && r.ffmpeg && r.ffmpeg !== 'ffmpeg' && r.ffmpeg !== 'ffprobe') ? r.ffmpeg : '';
  const hint = (r && r.os === 'win')
    ? 'Полный путь к ffmpeg.exe, например C:\\ffmpeg\\bin\\ffmpeg.exe\nПусто — искать автоматически'
    : 'Полный путь к ffmpeg, например /usr/local/bin/ffmpeg\nПусто — искать автоматически';
  const path = await showPrompt('Указать путь к ffmpeg',
    { text: hint, defaultValue: cur, okText: 'Сохранить' });
  if (path === null) return;
  try {
    const res = await api('/api/system/ffmpeg/set_path', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: String(path).trim() }),
    });
    _renderFfmpegStatus(res);
    if (typeof checkVideoCapabilities === 'function') checkVideoCapabilities();
    if (res.ok) {
      setSuccess('FFmpeg найден: ' + (res.ffmpeg || ''), 5000);
      haptic('success');
    } else {
      setStatus('Путь сохранён, но ffmpeg не найден', 5000, 'error');
      haptic('warning');
    }
  } catch (e) {
    setError('Ошибка: ' + String(e.message).slice(0, 160));
  }
}

/* ===== V7.7.0: извлечение кадров из видео ===== */
async function checkVideoCapabilities() {
  try {
    const r = await api('/api/video/capabilities');
    // Бэкенд может ответить по-разному — принимаем любой из вариантов
    const ok = !!(r && (r.ffmpeg || r.ok || r.available));
    _videoCaps = {
      ffmpeg: ok,
      error: r && r.error ? String(r.error) : null,
      raw: r || null,
    };
    try { console.log('[video/capabilities]', r); } catch (e) {}
  } catch (e) {
    _videoCaps = { ffmpeg: false, error: 'API недоступен: ' + String(e.message || e) };
    try { console.warn('[video/capabilities] failed', e); } catch (_) {}
  }
  return _videoCaps;
}
async function triggerVideoExtract() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  if (viewMode === 'trash') { setStatus(t('toast.leaveTrash')); return; }

  // Всегда перепроверяем: пользователь мог только что установить ffmpeg
  const caps = await checkVideoCapabilities();
  if (!caps.ffmpeg) {
    const err = caps.error || 'ffmpeg не найден в PATH';
    setError('Видео недоступно: ' + err +
             '. Открой Настройки → Видео (ffmpeg) → «Указать путь» или «Как установить».', 10000);
    return;
  }
  const inp = document.getElementById('videoInput');
  if (inp) inp.click();
}
async function extractVideoFrames() {
  const input = document.getElementById('videoInput');
  if (!input.files.length) return;
  if (!currentProjectId) { setStatus(t('toast.pickProject')); input.value = ''; return; }
  if (viewMode === 'trash') { setStatus(t('toast.leaveTrash')); input.value = ''; return; }

  const file = input.files[0];
  input.value = '';

  const fpsStr = await showPrompt(t('prompt.extractFps.title'), {
    text: t('prompt.extractFps.text', { name: file.name }),
    defaultValue: '2',
    hint: t('prompt.extractFps.hint'),
    okText: t('prompt.extractFps.ok'),
  });
  if (fpsStr === null) return;
  const efps = parseFloat(fpsStr);
  if (![0.5, 1, 2, 5, 10].includes(efps)) {
    setError('FPS должен быть: 0.5, 1, 2, 5 или 10');
    return;
  }

  const status = document.getElementById('importStatus');
  const result = document.getElementById('importResult');
  const closeBtn = document.getElementById('importCloseBtn');
  const progressWrap = document.getElementById('importProgressWrap');
  const progressFill = document.getElementById('importProgressFill');
  const progressText = document.getElementById('importProgressText');
  const progressPhase = document.getElementById('importProgressPhase');
  const progressBar = document.getElementById('importProgressBar');
  const importTitle = document.getElementById('importTitle');

  if (importTitle) importTitle.textContent = 'Извлечение кадров';
  status.textContent = 'Загрузка видео и извлечение кадров…';
  status.style.color = '';
  result.style.display = 'none'; result.innerHTML = '';
  closeBtn.style.display = 'none';
  if (progressWrap) progressWrap.style.display = 'block';
  if (progressFill) progressFill.style.width = '20%';
  if (progressText) progressText.textContent = '20%';
  if (progressPhase) progressPhase.textContent = 'Обработка (может занять минуту-две)…';
  if (progressBar) progressBar.setAttribute('aria-valuenow', '20');
  openModal('importModal');

  const fd = new FormData();
  fd.append('file', file);
  fd.append('extract_fps', String(efps));

  try {
    const res = await fetch(`/api/projects/${currentProjectId}/videos/upload`, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'DatasetBuilder' } });
    const data = await res.json().catch(() => ({}));
    if (progressWrap) progressWrap.style.display = 'none';
    if (!res.ok) {
      status.textContent = 'Ошибка извлечения';
      status.style.color = 'var(--danger)';
      result.style.display = 'block';
      result.textContent = data.detail || 'Не удалось обработать видео.';
    } else {
      status.textContent = 'Готово ✓';
      status.style.color = 'var(--success)';
      result.style.display = 'block';
      result.innerHTML = `
        <div>Файл: <b>${escapeHtml(data.filename || file.name)}</b></div>
        <div>Извлечено кадров: <b>${data.images_count}</b></div>
        <div>FPS извлечения: <b>${data.extract_fps}</b></div>
        ${data.duration_sec ? `<div>Длительность видео: <b>${Number(data.duration_sec).toFixed(1)} сек</b></div>` : ''}
        <div style="margin-top:8px;color:var(--text-secondary);font-size:0.75rem;">Кадры добавлены в список изображений.</div>
      `;
      await loadImages();
      haptic('success');
      setTimeout(() => closeImportModal(), 1200);
    }
  } catch (e) {
    if (progressWrap) progressWrap.style.display = 'none';
    status.textContent = 'Ошибка сети';
    status.style.color = 'var(--danger)';
    result.style.display = 'block';
    result.textContent = String(e.message || e);
  }
  closeBtn.style.display = 'inline-flex';
}
function _installVideoListeners() {
  const inp = document.getElementById('videoInput');
  if (inp && !inp.__bound) {
    inp.__bound = true;
    inp.addEventListener('change', extractVideoFrames);
  }
}

/* ===== Version history ===== */
const VERSION_HISTORY = [
  { version: 'V10.4.0', current: true, changes: [
    'Perf: rAF-батчинг рендера — серия вызовов renderBoxes/renderSkeleton склеивается в 1 кадр.',
    'Perf: motion vector — debounce 200 мс (drag рамки не долбит сервер запросами).',
    'Perf: _autoDetectBehavior — параллельные запросы через Promise.all (N×быстрее).',
    'Perf: renderSkeleton — не трогает DOM, если режим выключен.',
    'Perf: motion_vectors_all — один SQL вместо N+1 (batch по аннотациям текущего и предыдущего кадров).',
    'Perf: list_images при limit=0 — жёсткий cap 5000 (не тянет всё в память).',
    'Perf: трекинг — commit раз в 50 изменений (было 20).',
  ]},
  { version: 'V10.3.1', changes: [
    'Fix: кнопка «→ вектор» теперь явно показывает активное состояние (accent bg + белый текст).',
    'Fix: вектор не рисуется молча — показывается счётчик «N из M» и причина по каждой рамке.',
    'Feat: состояние «вектор включён» сохраняется между перезагрузками (localStorage).',
    'Feat: ответ motion_vectors возвращает reason для каждой рамки (no_prev_frame / no_iou_match / no_prev_boxes).',
    'API: расширенный motion_vectors_all — {items, summary: {total_with_aid, found, missing}}.',
  ]},
  { version: 'V10.3.0', changes: [
    'Fix: вектор движения для вручную созданных рамок — fallback по IoU, если animal_id не найден на предыдущем кадре.',
    'Feat: экспорт треков проекта в JSON и CSV (кнопки в модалке треков).',
    'Feat: плеер трека — превью-лента кадров одной animal_id с навигацией.',
    'API: GET /api/projects/{id}/tracks/{aid}/frames — кадры одного трека.',
    'API: GET /api/projects/{id}/tracks/export?format=json|csv — экспорт.',
  ]},
  { version: 'V10.2.1', changes: [
    'Feat: вектор движения рисуется сразу для ВСЕХ рамок с animal_id, без выделения.',
    'Feat: цвет стрелки = цвет поведения рамки (eat/walk/lie/drink/stand/active).',
    'Feat: batch-эндпоинт /motion_vectors — один запрос вместо N.',
  ]},
  { version: 'V10.2.0', changes: [
    'Feat: кнопка «→ вектор» — оверлей стрелки движения на холсте.',
    'Feat: правила walk / active в predict_behavior (сравнение с предыдущим кадром по animal_id).',
    'Feat: движение проверяется ПЕРЕД статикой (active / walk приоритетнее lie / stand).',
    'API: GET /api/images/{id}/motion_vector — центры bbox между кадрами.',
    'API: predict_behavior принимает animal_id — сервер сам считает motion.',
    'Note: пороги delta 0.02 (walk) и 0.06 (active) — будут уточнены по реальным данным.',
  ]},
  { version: 'V10.1.0', changes: [
    'Feat: кнопка «🔗 с предыдущим» — копирует animal_id с прошлого кадра по IoU.',
    'Feat: модалка «Треки» со списком треков, превью и переходом к первому кадру.',
    'Feat: Alt+→ / Alt+← — навигация по кадрам одного трека.',
    'API: GET /api/projects/{id}/tracks — список треков с доминирующим поведением.',
    'API: POST /api/images/{id}/link_from_prev — ручное связывание.',
    'API: GET /api/projects/{id}/navigate_with_aid — переход по треку.',
  ]},
  { version: 'V10.0.0', changes: [
    'Feat: трекинг кадров видео через ByteTrack.',
    'Feat: кнопка 🎯 трекинг в панели атрибутов (когда у фото есть video_id).',
    'Feat: прогресс через SSE — видно сколько кадров обработано и треков найдено.',
    'Feat: animal_id заполняется автоматически по трекам.',
    'Feat: уже введённые вручную animal_id сохраняются (маппинг track_id → ID).',
    'Feat: работает по кадрам из БД — оригинальный mp4 не нужен.',
    'API: POST/GET /api/videos/{id}/track[/status|/events|/stop].',
  ]},
  { version: 'V9.5.0', changes: [
    'Feat: кнопка 🦴 авто — авто-разметка скелета через pose-модель.',
    'Feat: маппинг предсказанных bbox → существующих аннотаций по IoU (порог 0.30).',
    'Feat: уже размеченные скелеты НЕ перезаписываются.',
    'Feat: после авто-скелета автоматически определяется поведение.',
    'API: POST /api/images/{id}/autolabel_pose.',
    'API: helper _get_pose_model_path — поиск pose-модели в models/.',
  ]},
  { version: 'V9.4.0', changes: [
    'Feat: обучение pose-модели YOLOv8 из UI — переключатель «Детекция / Скелет (pose)».',
    'Feat: датасет генерируется в YOLO-pose формате с kpt_shape [17, 3] и flip_idx.',
    'Feat: `yolo pose train` вместо detect — своя инициализация модели.',
    'Feat: подсчёт скелетов в проекте через /api/projects/{id}/skeletons_count.',
    'Feat: предупреждения в форме обучения о минимуме данных.',
    'Note: pose-модель может дать низкое качество при <100 скелетах.',
  ]},
  { version: 'V9.3.4', changes: [
    'Fix: «ест» — три независимых критерия вместо одного (tilt / nose / head_top ниже спины).',
    'Fix: стоящая свинья с мордой вперёд-вниз больше не попадает в «ест».',
    'Fix: порог head_tilt поднят 0.15 → 0.20.',
  ]},
  { version: 'V9.3.3', changes: [
    'Fix: после копирования скелета из похожего кадра автоматически определяется поведение.',
    'Fix: цветная точка в списке появляется сразу после копирования скелета.',
  ]},
  { version: 'V9.3.2', changes: [
    'Fix: критерий «ест» — нос ниже середины спина↔копыта (стоящая свинья больше не путается).',
    'Fix: diag приходит во всех ветвях (было undefined для eat/drink).',
    'Fix: цветная точка поведения в списке обновляется сразу после 🧠 авто.',
    'Fix: в режиме скелета работает pan (Space / СКМ / zoom>1 на пустом).',
  ]},
  { version: 'V9.3.1', changes: [
    'Fix: критерий «ест» — комбинированный (head_tilt > 0.15 ИЛИ nose_y ниже спины > 0.15).',
    'Fix: едящая свинья с опущенной макушкой теперь определяется правильно.',
    'Fix: после копирования скелета boxes[i].keypoints раскладываются по всем рамкам — S сохраняет всё.',
  ]},
  { version: 'V9.3.0', changes: [
    'Feat: кнопка «🦴 из похожего» — копирование скелета с похожего кадра (по pHash).',
    'Feat: автоматический матчинг рамок между кадрами по IoU (порог 0.20).',
    'Feat: координаты keypoints трансформируются относительно source-bbox → target-bbox.',
    'Feat: уже размеченные скелеты на target НЕ перезаписываются.',
    'Feat: если источников несколько — диалог выбора с превью.',
    'API: GET /api/images/{id}/similar_with_skeleton — похожие кадры со скелетами.',
    'API: POST /api/images/{target}/copy_skeleton_from/{source} — копирование.',
  ]},
  { version: 'V9.2.8', changes: [
    'Fix: neck исключён из spine_y — он ниже спины у стоящих и занижал offset.',
    'Feat: кнопка 🧠 авто работает на все рамки фото без выделения.',
    'Feat: авто-режим НЕ перезаписывает уже установленные поведения.',
    'Fix: панель атрибутов больше не приглушается без выделения — кнопка 🧠 авто всегда кликабельна.',
    'Fix: diag со всеми цифрами приходит в F12 для отладки.',
  ]},
  { version: 'V9.2.7', changes: [
    'Fix: lie/stand теперь по 2 признакам: hoof_offset + body_height.',
    'Fix: пограничная зона 0.18..0.30 разрешается по высоте скелета.',
    'Diag: predict_behavior возвращает diag — все ключевые цифры.',
  ]},
  { version: 'V9.2.6', changes: [
    'Fix: убрана «мёртвая зона» lie/stand — теперь одна граница 0.32.',
    'Fix: лежащая свинья с высунутыми копытами (offset≈0.26) больше не попадает в ambiguous.',
    'Feat: единая константа BEHAVIOR_LIE_STAND_BOUNDARY для настройки.',
  ]},
  { version: 'V9.2.5', changes: [
    'Fix: главный критерий «ест» — наклон ГОЛОВЫ (nose vs head_top), а не «нос ниже спины».',
    'Fix: у стоячей свиньи нос тоже ниже спины, старый порог 0.05 ловил ложные «ест».',
    'Fix: порог «лежит» у копыт уточнён (0.25 → 0.20), ложные срабатывания ушли.',
    'Feat: все пороги поведения вынесены в константы BEHAVIOR_*.',
  ]},
  { version: 'V9.2.4', changes: [
    'Fix: правило поведения работает с любым набором видимых точек, а не жёстко требует nose+withers+hip.',
    'Fix: линия спины усредняется по доступным (withers / mid_spine / hip / neck / tail_base).',
    'Fix: для lie/stand достаточно 2 видимых копыт.',
    'Diag: reason теперь указывает какие точки пришли и почему правило не сработало.',
  ]},
  { version: 'V9.2.3', changes: [
    'Diag: predict_behavior пишет print вместо log.info (uvicorn перехватывает логгеры).',
    'Diag: console.log вместо console.debug — видно по умолчанию в F12.',
  ]},
  { version: 'V9.2.2', changes: [
    'Fix: правило поведения ищет точки по синонимам (nose/Нос/Nose).',
    'Diag: predict_behavior логирует имена и видимость входящих точек.',
    'Diag: при ошибке возвращает список полученных имён.',
  ]},
  { version: 'V9.2.1', changes: [
    'Fix: авто-определение поведения скелета теперь ищет точки во всех источниках (boxes / _kpByIndex / keypoints).',
    'Fix: различные сообщения для «нет рамки» / «нет точек» / «правило не сработало».',
    'Feat: диагностика в консоли (F12 → [predict-behavior]).',
  ]},
  { version: 'V9.2.0', changes: [
    'Feat: YOLO-экспорт автоматически переходит на pose-формат, если у ≥50% рамок есть скелет.',
    'Feat: COCO-экспорт включает keypoints + skeleton + num_keypoints, если у ≥50% рамок есть скелет.',
    'Feat: правила определения поведения по геометрии скелета (eat / drink / lie / stand).',
    'Feat: API POST /api/images/{id}/predict_behavior.',
    'Feat: кнопка «🧠 авто» в панели атрибутов — определяет поведение выделенной рамки.',
  ]},
  { version: 'V9.1.7', changes: [
    'Fix: восстановлена пропавшая функция _drawSkeletonForBox — скелет снова рисуется.',
    'Fix: подсказка «Следующая точка» работает после возврата функции.',
  ]},
  { version: 'V9.1.6', changes: [
    'Fix: подсказка «Следующая точка» снова работает — скелет больше не пишет чужие keypoints в текущую рамку.',
    'Fix: renderSkeleton синхронизирует keypoints ТОЛЬКО из boxes (не наоборот).',
    'Fix: защита от null-схемы в _nextUnplacedName.',
  ]},
  { version: 'V9.1.5', changes: [
    'Fix: скелеты всех размеченных рамок видны, когда включён режим Skeleton.',
    'Fix: при переключении между рамками keypoints гарантированно синхронизируются с boxes.',
    'Fix: при открытии фото keypoints у всех рамок перезагружаются из сервера.',
    'i18n: все строки скелета переведены на английский.',
  ]},
  { version: 'V9.1.4', changes: [
    'Fix: Ctrl+Z в режиме скелета откатывает по одной точке, а не весь скелет.',
    'Fix: Ctrl+Y / Ctrl+Shift+Z восстанавливает точки после отката.',
    'UX: статус-бар виснет overlay — больше не сдвигает холст при появлении/исчезновении.',
    'UX: уменьшен вертикальный зазор между тулбаром и холстом (16→12 px).',
  ]},
  { version: 'V9.1.3', changes: [
    'Fix: скелет рисуется для ВСЕХ рамок на фото (не только для выделенной).',
    'Fix: при снятии выделения скелет больше не пропадает.',
    'Fix: при повторном выделении рамки точки берутся из живого состояния, а не из устаревшего серверного снимка.',
  ]},
  { version: 'V9.1.2', changes: [
    'Fix: Ctrl+Z и Ctrl+Y откатывают действия со скелетом (точки теперь входят в историю).',
    'Fix: правый клик в режиме скелета удаляет последнюю точку.',
    'Fix: выбранный проект сохраняется между перезагрузками страницы.',
    'Fix: navigator.vibrate больше не спамит warning до первого клика.',
    'Feat: двойной клик по точке скелета — переключить видимость (видно ↔ скрыто).',
    'Feat: подсказка снизу напоминает про все действия (Shift, ПКМ, двойной клик).',
  ]},
  { version: 'V9.1.1', changes: [
    'Fix: в режиме скелета теперь можно выделить рамку кликом — она выбирается, а не ставит точку.',
    'Fix: скелет сохраняется вместе с рамками — была потеря привязки.',
    'Feat: Shift+клик ставит точку со скрытой видимостью (visibility=0) для частей тела, которые не видны на кадре.',
    'UX: серые кружки для точек с visibility < 0.5.',
    'UX: подсказка снизу напоминает про Shift+клик.',
  ]},
  { version: 'V9.1.0', changes: [
    'Feat: UI-режим «Скелет» — кнопка в тулбаре и Shift+K.',
    'Feat: точки ставятся кликом по холсту, отменяются правым кликом.',
    'Feat: drag точки — перемещение.',
    'Feat: провода между точками рисуются по схеме.',
    'Feat: подсказка о следующей точке снизу холста.',
    'Feat: точки сохраняются вместе с рамками (S) в PUT /api/images/{id}/annotations.',
    'Feat: keypoints загружаются при переключении между фото.',
    'API: GET /api/images/{id}/keypoints_by_index — точки для всех аннотаций фото.',
    'Fix: убрано уточнение «» из текстов и комментариев.',
  ]},
  { version: 'V9.0.0', changes: [
    'Feat: backend скелета — ORM-таблица keypoints.',
    'Feat: схема скелета из 17 точек в конфиге KEYPOINT_SCHEMA.',
    'API: GET/PUT/DELETE /api/annotations/{id}/keypoints.',
    'API: GET /api/keypoint_schema — схема для UI.',
    'Export: keypoints.csv в YOLO-архиве (отдельно от attributes.csv).',
    'Export: boxes.csv — колонка keypoints_count.',
    'Note: UI-режим «Скелет» — в следующем патче (V8.5.1).',
  ]},
  { version: 'V8.4.2', changes: [
    'UX: масштабирование фото — Ctrl/Cmd + колесо мыши (как в Google Maps / Figma).',
    'UX: обычное колесо мыши — листает страницу как обычно (не перехватывается).',
    'UX: панорамирование холста — только зажатой ЛКМ + drag (без изменений).',
    'UX: pinch на трекпаде — zoom (браузер эмулирует Ctrl+wheel).',
  ]},
  { version: 'V8.4.1', changes: [
    'Fix: перетаскивание рамки больше не сбрасывает behavior и animal_id.',
    'Fix: resize за угол и nudge стрелками тоже сохраняют атрибуты.',
    'Fix: индикатор-точка behaviour в списке обновляется сразу после сохранения, без F5.',
  ]},
  { version: 'V8.4.0', changes: [
    'Feat: хоткеи 1..6 для назначения поведения выделенной рамке.',
    'Feat: хоткей 0 — присвоить следующий свободный ID; Shift+0 — сбросить ID.',
    'Feat: кнопка «↧ ко всем» — применить текущее поведение/ID ко всем рамкам фото.',
    'Feat: экспорт YOLO генерирует attributes.csv (behavior + animal_id + timestamp_sec).',
    'Feat: цветная точка-индикатор behaviour в списке изображений (multi — секторами).',
  ]},
  { version: 'V8.3.2', changes: [
    'Fix: клик по панели атрибутов (поведение, поле ID) больше не сбрасывает выделение рамки.',
    'Fix: чипсы тегов под холстом не сбрасывают выделение рамок.',
    'Fix: глобальный pointerdown игнорирует клики внутри .attr-bar и .tag-chips-bar.',
  ]},
  { version: 'V8.3.1', changes: [
    'Fix: битые ссылки на изображения — get_image_file явно возвращает 404, а не 500.',
    'Fix: placeholder «файл отсутствует» в списке для битых миниатюр.',
    'Feat: диагностика — GET /api/projects/{id}/broken_images и автоскан при старте.',
    'Fix: атрибуты рамки (поведение + номер) применяются ТОЛЬКО к выделенным рамкам.',
    'UX: счётчик выделенных в панели атрибутов + приглушение, когда ничего не выделено.',
    'UX: ручки ресайза и крестик появляются только при наведении (кроме тач-устройств).',
  ]},
  { version: 'V8.3.0', changes: [
    'Feat: атрибуты рамки — behavior (поведение) и animal_id (номер животного).',
    'Feat: images.timestamp_sec — таймкод кадра из исходного видео.',
    'Feat: панель под холстом — 6 кнопок поведения + поле номера + кнопка «присвоить новый ID».',
    'Feat: цветовые бейджи поведения и номера прямо на рамках.',
    'Feat: массовое применение атрибутов к выделенным рамкам.',
    'Feat: CSV-экспорт рамок — добавлены behavior, animal_id, timestamp_sec.',
    'API: POST /api/images/bulk_annotation_attrs — bulk-обновление атрибутов.',
    'API: GET /api/projects/{id}/next_animal_id — следующий свободный номер.',
  ]},
  { version: 'V8.2.3', changes: [
    'Fix: не все модалки закрывались по Enter — теперь confirm-диалоги (удаление фото, очистка корзины, удаление проекта, очистка разметки, удаление тега) реагируют на Enter.',
    'Fix: dialogModal — Enter при фокусе на «Отмена» вызывает Отмена, а не OK.',
    'Fix: openModal больше не фокусирует скрытые [data-autofocus] элементы (из-за этого фокус оставался на кнопке вне модалки).',
    'Fix: data-autofocus на #dialogInput управляется динамически — есть только когда открыто поле ввода.',
    'Fix: Enter-на-кнопке учитывается только если кнопка внутри активной модалки.',
    'Feat: универсальный Enter в модалках — жмёт главную кнопку (экспорт, обучение, настройки, создание проекта/тега), если фокус не в поле и не на кнопке.',
    'Note: importModal и importSourceModal исключены — там Enter не должен случайно отменять процесс.',
  ]},
  { version: 'V8.2.2', changes: [
    'Fix: Ctrl+Z теперь откатывает авторазметку (раньше история стиралась).',
    'Fix: авторазметка добавляет новое состояние в историю, а не заменяет её.',
    'Fix: если авторазметка не дала изменений — Ctrl+Z откатит предыдущее действие.',
  ]},
  { version: 'V8.2.1', changes: [
    'Fix: debug-авторазметка больше не делает существующие рамки красными — сохранение перенесено на сервер, клиент не POST-ит /annotations.',
    'Fix: существующие рамки сохраняют confidence / label / frozen после авторазметки в любом режиме.',
    'Refactor: bulk_save_objects → add_all (SQLAlchemy 2.0 style).',
  ]},
  { version: 'V8.2.0', changes: [
    'Feat: режим авторазметки «Добавлять» (по умолчанию) — старые рамки не сбрасываются, дорисовываются только уникальные детекции.',
    'Feat: фильтр дубликатов по IoU > 0.5 ИЛИ расстоянию центров < 5%.',
    'Feat: переключатель «Добавлять / Заменять» в настройках (сегмент).',
    'Feat: работает в одиночной, debug и batch авторазметке.',
    'Feat: статус показывает «+N новых, M пропущено».',
  ]},
  { version: 'V8.1.1', changes: [
    'Fix: меню горячих клавиш — текст больше не накладывается (CSS grid).',
    'Fix: полный EN-перевод секций «Мышь и жесты» и «Холст».',
    'Fix: сортировка «по имени» — natural sort (свинка_2 перед свинка_10).',
    'Fix: сортировка «по типу» — группирует файлы по расширению.',
    'Fix: Undo/Redo списка изображений — одиночные удаления тоже восстанавливаются.',
    'Fix: Ctrl+Z откатывает удаление изображения, если нет undo для рамок.',
  ]},
  { version: 'V8.1.0', changes: [
    'Fix: создание тега из чипс-бара больше не падает (shadowing t()).',
    'Fix: убраны дубликаты маршрутов /i18n.js и атрибутов в index.html.',
    'Fix: версия синхронизирована во всех файлах (единый version.py).',
    'Fix: loadImages отменяет предыдущий запрос через AbortController.',
    'Fix: VACUUM INTO проверяет версию SQLite (>= 3.27).',
    'Fix: миграция MySQL->SQLite делает снимок .env и откатывает при ошибке.',
    'Security: CSRF-защита — write-запросы требуют X-Requested-With.',
    "Security: CSP (default-src 'self', frame-ancestors 'none').",
    'Security: X-Frame-Options: DENY, X-Content-Type-Options: nosniff.',
    'Security: Referrer-Policy: no-referrer, Permissions-Policy.',
    'Perf: pHash-дубликаты — 6-символьный префикс + лимит 400 (от O(n^2)).',
    'Perf: find_duplicate и _compute_duplicate_ids ограничены LIMIT.',
    'Perf: _rowTops пересчитывается инкрементально при пагинации.',
    'Feat: Undo/Redo списка изображений (Ctrl+Shift+Z).',
    'Feat: «Показать на диске» — открывает проводник/Finder.',
    'Feat: TTA (test-time augmentation) при авторазметке — тумблер в настройках.',
    'Feat: сравнение моделей side-by-side в метриках.',
    'Feat: экспорт CSV всех рамок проекта (FileOps).',
    'Feat: drag-n-drop изображений между проектами.',
    'Feat: командная палитра ищет по классам и тегам, хранит 5 последних команд.',
    'i18n: fallback для t() — приложение не сломается без i18n.js.',
    'i18n: backend-ошибки отдают ключи, клиент переводит.',
    'Cross-platform: иконка окна выбирается под ОС (icns / ico / png).',
    'Cross-platform: файловый лог и в dev-режиме (app.log).',
    'Build: build.spec чище — убран дубликат collect_data_files(ultralytics).',
    'Docs: README.md переписан под V8.1.0.',
  ]},
  { version: 'V8.0.0', changes: [
    'Feat: поддержка i18n — английский интерфейс (переключатель в настройках).',
    'Feat: HTML и JS-строки локализованы, бэкенд возвращает error keys.',
    'Feat: plural-функции учитывают язык (images/image, projects/project).',
    'Feat: автоопределение языка браузера при первом запуске.',
  ]},
  { version: 'V7.9.4', changes: [
    'Perf: миниатюры генерируются в фоновом пуле — импорт 1000+ фото не блокируется.',
    'Perf: сохранение разметки обновляет список без сетевого рефетча.',
    'Perf: /api/projects/{id}/stats кэшируется на 30 секунд.',
    'Feat: системное уведомление при завершении обучения (если вкладка свёрнута).',
  ]},
  { version: 'V7.9.3', changes: [
    'Fix: Escape закрывает диалог подтверждения даже из поля ввода.',
    'Fix: остановка обучения на Linux/macOS убивает всю process group — DataLoader-воркеры не висят.',
    'Fix: launcher.py сохраняет настройки (тема, скрытие подсказок) между запусками.',
    'Fix: launcher.py даёт понятную ошибку, если не установлен pywebview.',
    'Perf: активная YOLO-модель прогревается в фоне при старте — первый запрос классов без задержки.',
    'Perf: backfill v7.6.0 уехал в фон — импорт app.py больше не блокируется.',
    'Perf: /active_learning не дёргается на каждое сохранение — debounce 1.5 с.',
    'Perf: similar_images fallback расширен до 5000 записей.',
    'UX: клик по активному изображению в списке больше не перезагружает его.',
    'UI: height: 100dvh для корректного скролла на мобильных Safari/Chrome.',
    'Fix: валидатор разметки кэшируется — не пересчитывается при каждом открытии.',
    'Feat: /stats.csv учитывает активные фильтры (уверенность, теги, поиск, дубликаты).',
    'Feat: фильтр «Только дубликаты» в списке изображений.',
  ]},
{ version: 'V7.9.2', changes: [
    'Fix: стоп обучения на Windows работает — процесс завершается, а не висит в «stopping».',
    'Fix: статус «Останавливаю обучение…» больше не залипает в тулбаре — показывается спиннер и гаснет сам.',
    'Fix: tooltip «Удалить» корректно исчезает после удаления рамки.',
    'Fix: вручную сдвинутая рамка сразу перекрашивается в красный.',
    'Fix: Ctrl+Z / Ctrl+Y работают всегда — включая после закрытия модалок.',
]},
{ version: 'V7.9.1', changes: [
  'Fix: кнопка корзины в сайдбаре больше не проваливается под шапку при hover.',
  'Fix: live-графики метрик не мигают во время обучения.',
  'Fix: настройки открываются мгновенно — модели и статусы грузятся в фоне.',
]},
{ version: 'V7.9.0', changes: [
  'SAM: кэш эмбеддинга картинки — повторные клики по тому же фото в 10× быстрее.',
  'Список обучений грузится из кэша по mtime — мгновенное открытие.',
  'pHash-дедупликация ускорена в 2–3 раза (int вместо парсинга строк).',
  'YOLO-кэш на 2 модели (LRU) — переключение без перезагрузки с диска.',
  'Сборка стала на 40–50 % легче: OpenCV headless, чистка torch-зависимостей.',
  'Пользовательские данные перенесены в системную папку (%LOCALAPPDATA%).',
  'Автомиграция данных со старого места рядом с exe.',
]},
{ version: 'V7.8.4', changes: [
  'Внутренний рефакторинг: единый хелпер onActivate для активации по Enter/Space.',
  'Плюрализация объединена в одну функцию plural() с чистой формулой.',
  'Внешние импортёры (Roboflow, Darwin) используют общий скелет временного zip.',
  'Поведение приложения не изменилось — только чище код.',
]},
{ version: 'V7.8.3', changes: [
  'Удалён неиспользуемый код live-tracking видео и интерполяции (~300 строк).',
  'Удалён мёртвый кэш рядов списка — меньше потребление памяти при длинной сессии.',
  'Убраны write-only переменные (_activeLearningState, _currentSamModel, _lastRenderIds).',
  'Удалён импорт CORSMiddleware и no-op listener prefers-reduced-motion.',
  'SVG-иконки trash и download вынесены в спрайт — HTML стал короче.',
]},
{ version: 'V7.8.2', changes: [
    'Fix: Исправлена работа SAM-режима.',
    'Приложение упаковано в .exe',
    'Fix: обучение не падает на Linux/macOS (CREATE_NEW_PROCESS_GROUP).',
    'Fix: настройка «Размер миниатюр» проекта теперь применяется.',
    'Fix: убран 404-поллинг несуществующего /api/import/status.',
    'Fix: холст помечен как region — скринридеры корректно ходят по интерфейсу.',
  ]},
{ version: 'V7.8.1', changes: [
    'Fix: Esc при активном SAM-превью отменяет только превью, без других действий.',
    'Fix: сайдбар — секции не наезжают друг на друга, список проектов со своим скроллом.',
    'Fix: путь к ffmpeg принимается с кавычками от Windows Explorer.',
    'Автопоиск ffmpeg в WinGet Links и WinGet Packages (Gyan.FFmpeg).',
    'Сообщение «ffmpeg не найден» больше не дублируется.',
  ]},
  { version: 'V7.8.0', changes: [
    'Debug-режим YOLO: тумблер в настройках показывает все классы детекции.',
    'Нецелевые объекты рисуются серыми пунктирными рамками, не сохраняются.',
    'Хоткей ⇧G — быстрое переключение debug-режима.',
  ]},
  { version: 'V7.7.0', changes: [
    'Видео упрощено: только извлечение кадров, без timeline и трекинга.',
    'Focus-режим: фото по центру, тулбар над фото полупрозрачный.',
    'Кнопка установки ffmpeg в настройках с инструкцией под ОС.',
    'Фиксы: пустая разметка, SAM-объекты, поля настроек проекта, сайдбар.',
  ]},
  { version: 'V7.6.1', changes: [
    'Импорт из Labelbox по API key + project_id.',
    'Импорт из Scale AI (Nucleus) по API key + dataset_id.',
    'Импорт из V7 Darwin по API key + team_slug + dataset_slug.',
    'Универсальная конвертация в COCO на лету — попадает в общий pipeline.',
  ]},
  { version: 'V7.6.0', changes: [
    'Live-графики обучения: mAP / loss обновляются в реальном времени.',
    'Live-трекинг видео через SSE: счётчик кадров, кнопка «Стоп».',
    'Bulk rename по маске: image_{n:04d}.jpg, любой шаблон.',
    'Копирование и перемещение изображений между проектами.',
    'Поиск дубликатов в проекте по pHash: группы, выбор «оставить».',
    'Сортировка списка: по дате и размеру файла.',
    'Экспорт CSV со списком всех файлов проекта.',
    'Импорт из Roboflow, Supervisely, произвольного URL (S3/GCS), локальной папки.',
  ]},
  { version: 'V7.5.1', changes: [
    'Автоматическая миграция MySQL → SQLite одной кнопкой.',
    'Копирование данных через ORM (без mysqldump), с проверкой целостности.',
    'Прогресс миграции по таблицам, точные счётчики (ожидается / перенесено).',
    '.env обновляется автоматически — DB_ENGINE=sqlite, DB_PATH=<путь>.',
    'Старая SQLite-БД сохраняется как .bak при перезаписи.',
  ]},
  { version: 'V7.5.0', changes: [
    'Local-first режим: DB_ENGINE=sqlite — работает без MySQL, данные в одном файле.',
    'WAL-журнал, foreign_keys, busy_timeout — SQLite настроен для многопоточной работы.',
    'Панель «Хранилище» в настройках: движок, пути, размер данных.',
    'Кнопка «Скачать всю базу» — VACUUM INTO для SQLite, mysqldump для MySQL.',
    'DATA_ROOT — можно вынести все пользовательские данные в отдельную папку.',
  ]},
  { version: 'V7.4.0', changes: [
    'Видео-режим: загрузка mp4/mov/avi/mkv/webm, извлечение кадров через ffmpeg.',
    'Timeline с навигацией по кадрам, слайдер, счётчик кадров.',
    'Интерполяция между двумя ключевыми кадрами.',
    'Авто-трекинг объектов: YOLO + ByteTrack.',
  ]},
  { version: 'V7.3.0', changes: [
    'Отмена обучения сохраняет last.pt — можно продолжить с чекпоинта.',
    'Остановленная модель копируется в models/ как <name>_partial.pt и активируется.',
    'Warning-значок рядом с моделями, которые не знают класс текущего проекта.',
    'Расширенные настройки проекта: TTL корзины, размер миниатюр, дефолтный zoom.',
    'TTL корзины работает per-project (override перекрывает глобальный).',
  ]},
  { version: 'V7.2.0', changes: [
    'SAM-сегментация в один клик: кликнул по объекту — получил рамку по маске.',
    'Режим SAM (M) — клик по объекту, Enter — принять, Esc — отменить.',
    'Метрики обучения: mAP@50, mAP@50-95, precision/recall по эпохам.',
    'Active learning: приложение подсказывает, когда переобучить модель.',
    'История обучений: все прогоны с метриками сохраняются в runs/.',
  ]},
  { version: 'V7.1.0', changes: [
    'Командная палитра (⌘K / Ctrl+K) — все действия из одного места.',
    'Focus-режим (⌘\\ / Ctrl+\\) — скрывает сайдбар и тулбар.',
    'Секции «Неразмеченные / Размеченные» с авто-сворачиванием.',
    'Прогресс в заголовке вкладки: 12/48 — Dataset Builder.',
    'Zoom-to-selection (Z) — приближает к выделенной рамке.',
  ]},
  { version: 'V7.0.0', changes: [
    'Мультиклассовые проекты: у каждого проекта свой объект детекции.',
    'Поиск по классам, которые реально знает активная YOLO-модель.',
    'Класс «своё» — если обучен на собственном классе, вводится вручную.',
    'Настройки проекта (⚙ на строке проекта): выбор класса и очистка разметки.',
    'Смена класса блокируется, если в проекте есть хоть одна рамка.',
    'Приложение переименовано в Dataset Builder.',
  ]},
  { version: 'V6.2.2', changes: [
    'Fix: resize рамки мышью — handles больше не перекрыты боковыми полосками.',
    'Hover-подъём добавлен всем интерактивам.',
    'Fix: в светлой теме неактивная кнопка темы больше не «засвечивается» белым.',
    'Enter закрывает диалог подтверждения.',
    'После закрытия модалки по Esc фокус снимается с кнопки-триггера.',
    'Из тулбара убрана кнопка «Удалить рамку».',
  ]},
  { version: 'V6.2.1', changes: [
    'Hover-подъём кнопок усилен: −3px с лёгким увеличением, мягкий пружинистый возврат.',
    'Иконочные кнопки поднимаются вместе с кнопками: −2px + scale(1.12).',
    'Контейнерные ограничения в модалках и тулбаре смягчены.',
  ]},
  { version: 'V6.2.0', changes: [
    'Сортировка «сомнительные» подняла неразмеченные в самый верх.',
    'Кнопки сортировки и фильтра закрываются повторным нажатием.',
    'Окно бэкапа переверстано: убраны лишние пропуски.',
    'Статус размечено / неразмечено теперь обновляется сразу после сохранения.',
    'Активная кнопка корзины визуально подсвечена.',
    'Корзина объединена: проекты и изображения в одном списке.',
    'Рамки на холсте выделяются только при клике по линии/краю.',
    'Панорамирование открытой фотографии мышкой при zoom > 1.',
    'create by Xulkvan — кликабельная ссылка на GitHub.',
  ]},
  { version: 'V6.1.0', changes: [
    'Корзина проектов: удаление — в корзину, восстановление, окончательное удаление.',
    'Мягкое нажатие кнопок: убран bounce, оставлен плавный :active scale.',
    'Исправлены залипания тултипов.',
    'Кнопка удаления проекта больше не накладывается на счётчик фото.',
    'Кастомный color-picker с пресетами, hex-инпутом и закрытием по клику вне.',
    'Мгновенное обновление тегов / флагов / статуса в строках списка.',
    'Расширены форматы импорта: AVIF, HEIC, HEIF, GIF.',
    'Клик по всей строке изображения.',
    'Status-плашка стала sticky.',
  ]},
  { version: 'V6.0.0', changes: [
    'Полный аудит производительности, безопасности, a11y и UX.',
    'Backend: SWR-кэш pHash, batch-commit авторазметки, numpy DCT, sweep-line в валидаторе.',
    'Frontend: combobox-паттерн для custom-select, drag-n-drop файлов, прогресс импорта через polling.',
  ]},
{ version: 'V5.5', changes: [
    'Файлы проекта разбиты и структурированы',
  ]},
  { version: 'V5.4.4', changes: [
    'Zoom-кнопки на холсте снова работают.',
    'Убрана избыточная кнопка «100%».',
    'Окно горячих клавиш (H) дополнено.',
  ]},
  { version: 'V5.4.3', changes: [
    'H / ? — toggle: то же нажатие закрывает окно горячих клавиш.',
    'Кнопка «?» перенесена из тулбара в сайдбар.',
    'Кнопка «Назначить тег» скрывается, когда ничего не выделено.',
  ]},
  { version: 'V5.4.2', changes: [
    'Анимация нажатия кнопок: press-down → overshoot → settle.',
  ]},
  { version: 'V5.4.1', changes: [
    'Скроллбар в модалках прижат к самому правому краю.',
    'Убран scrollbar-gutter: stable.',
    'Модалки: padding только сверху/снизу.',
    'Контент симметричен: 24px слева / 24px справа.',
  ]},
  { version: 'V5.4.0', changes: [
    'Pointer events: единый ввод мышь/тач/перо, pinch-zoom, панорама двумя пальцами.',
    'FLIP-анимация списка.',
    'Bulk-tag menu в тулбаре.',
    'Импорт датасета: in-memory pHash-бакеты + batch-commit.',
    'Хендлы, чекбоксы и строки списка увеличены для пальцев.',
  ]},
  { version: 'V5.3.0', changes: [
    'Motion: реальный hover-lift, settle-плюх при рисовании рамки, draw-dot.',
    'Fix XSS: setStatus экранирует по умолчанию.',
    'Cmd/Ctrl+S — сохранить, H — toggle окна горячих клавиш.',
    'freeze слоёв ≤ 9.',
  ]},
  { version: 'V5.2.1', changes: [
    'Fix: сообщение бэкапа больше не выходит за рамки.',
    'Скроллбар прижат вплотную к правому краю модалки.',
  ]},
  { version: 'V5.2.0', changes: [
    'Импорт датасета целиком: изображения + разметка из zip.',
    'История статусов: in-memory лог на 1000 событий.',
    'Бэкап проекта: POST /api/projects/{id}/backup.',
    'Скроллбар в меню: тонкий thumb с прозрачной рамкой.',
  ]},
  { version: 'V5.1.1', changes: [
    'Fix: custom-select menu вынесено в document.body.',
    'Fix: тултипы больше не всплывают на программный фокус.',
    'Возвращены apple-style hover.',
    'Toolbar: overflow visible + flex-wrap.',
  ]},
  { version: 'V5.1.0', changes: [
    'Кастомные тултипы вместо браузерных title.',
    'Убран hover-scale у кнопок.',
    'model-row / stat-card: hover без подъёма, только тень.',
    'Liquid Glass: modal/backdrop/меню/тулбар с backdrop-filter.',
    'Materialization-анимация модалок.',
    'Reduce Motion покрывает все новые hover/press.',
  ]},
  { version: 'V5.0.0', changes: [
    'Motion-токены Apple HIG + Haptics + Skeleton shimmer.',
    'Кастомные дропдауны OpenImages V7 / COCO.',
  ]},
  { version: 'V4.5.0', changes: [
    'Дефолт — yolov8n-oiv7.pt (в OpenImages V7 есть Pig, в COCO — нет).',
    'Авторазметка фильтрует классы: pig/wild boar/boar/hog/piglet/swine.',
    'SSE bootstrap корректно закрывается, retry скачивания.',
    'batch_restore восстанавливает с уникальными именами.',
    'Валидация hex-цвета тега, logging, host 127.0.0.1.',
  ]},
  { version: 'V4.4.8', changes: [
    'В блок подсказок вернулась легенда цветов рамок.',
    'В легенду добавлен пункт «заморожена».',
  ]},
  { version: 'V4.4.7', changes: [
    'Длинные названия опций в кастомных селектах больше не обрезаются.',
    'Меню селекта растягивается под содержимое (до 360px).',
  ]},
  { version: 'V4.4.6', changes: [
    'Кастомные выпадающие списки — скруглённое меню в стиле интерфейса.',
    'Переключение модели кликом по всей строке работает всегда.',
  ]},
  { version: 'V4.4.5', changes: [
    'Статус скачивания модели авто-скрывается через 5 секунд.',
    'Клик по всей строке модели активирует её.',
    'Все <select> в UI приведены к закруглённому виду через CSS.',
  ]},
  { version: 'V4.4.4', changes: [
    'SSE-статус автозагрузки дефолтной модели при первом запуске.',
    'Кнопка ручного скачивания YOLO-модели (COCO / OpenImages V7, n/s/m).',
    'Прогресс скачивания в реальном времени.',
    'Авто-активация первой скачанной / обученной модели.',
  ]},
  { version: 'V4.4.3', changes: [
    'При первом запуске модель yolov8n.pt скачивается автоматически.',
    'После обучения новая модель автоматически становится активной.',
  ]},
  { version: 'V4.4.2', changes: [
    'Разрешено переименование и удаление pig.pt.',
    'Удаление блокируется только для активной модели и последней в папке.',
    'Кнопки карандаша/корзины у всех моделей.',
  ]},
  { version: 'V4.4.1', changes: [
    'Прогресс и эпоха обучения в UI корректны (строгий regex).',
    'Предупреждение в форме обучения при недостатке размеченных фото.',
    'Дефолтные эпохи 100.',
    'Возможность задать имя обучаемой модели.',
  ]},
  { version: 'V4.4', changes: [
    'Выбор предобученного датасета: COCO или OpenImages V7.',
    'Параметры fine-tune: freeze, lr0, patience, cos_lr, warmup.',
    'Опция «Текущая активная модель» для continual learning.',
    'prepare_training_dataset: отсеивание неразмеченных, честный train/val split.',
  ]},
  { version: 'V4.3.1', changes: [
    'Кликабельной сделана только сама версия (Vn.n.n).',
    'Сайдбар: убран двойной вертикальный скролл.',
    'Модалка статистики: убран вложенный скролл.',
    'Fix: диалог подтверждения поверх открытых модалок.',
  ]},
  { version: 'V4.3', changes: [
    'Из валидатора удалены near_duplicate и possible_missed.',
    'Версия приложения стала кликабельной — история версий.',
    'Fix: case() в project_stats (500 ошибка в статистике).',
    'Глобальный exception handler.',
  ]},
  { version: 'V4.2', changes: [
    'Pydantic-схемы для аннотаций и batch-запросов.',
    'Индексы БД (images, annotations, tags, image_tags).',
    'Кэш YOLO-моделей, bucket-поиск pHash.',
    'Защита от path traversal и zip-slip.',
    'Focus-trap в модалках, Escape закрывает верхнюю.',
    'Counter-scale handles/labels при zoom.',
    'Blob-экспорт, ARIA-атрибуты, prefers-reduced-motion.',
  ]},
  { version: 'V4.1', changes: [
    'Тег-чипсы под холстом (1 клик = назначить/снять).',
    'Инлайн-создание тега прямо из чипс-бара.',
    'Заморозка/разморозка рамок (L).',
    'Хоткеи N/P/R/L/H и окно всех шорткатов (?).',
    'Улучшенный валидатор.',
    'CSV-экспорт статистики проекта.',
  ]},
  { version: 'V4.0', changes: [
    'Virtual scrolling списка изображений.',
    'Превью-миниатюры 64×64 (кэш на сервере).',
    'SSE-прогресс массовой авторазметки.',
    'Фикс z-index диалоговых окон.',
  ]},
  { version: 'V3.11', changes: [
    'Обучение модели прямо из UI + SSE-прогресс.',
    'Выбор активной модели.',
    'Кластеризация похожих кадров по pHash.',
  ]},
  { version: 'V3.10', changes: [
    'Импорт разметки: COCO / YOLO / CVAT / Label Studio.',
    'Train / Val / Test split при экспорте.',
    'Поиск по имени, теги, фильтр по тегу.',
    'Валидатор разметки.',
  ]},
  { version: 'V3.9', changes: [
    'Zoom/Pan холста.',
    '«Принять и далее» (Enter).',
    'Флаг сложных кадров (F).',
    'Мультивыбор и групповые операции над рамками.',
  ]},
  { version: 'V3.8', changes: [
    'Кастомные модалки вместо alert/confirm/prompt.',
    'Экспорт с выбором имён.',
    'Фиксация расширения при переименовании.',
  ]},
  { version: 'V3.7', changes: [
    'Уникальные имена файлов (name (N)).',
    'Кнопка переименования изображения.',
  ]},
  { version: 'V3.6', changes: [
    'Статистика проекта.',
    'Автоочистка корзины через N дней.',
    'Тема «Авто».',
  ]},
  { version: 'V3.5', changes: [
    '4 уровня confidence для рамок.',
    'XOR-фильтры.',
    'Корзина с восстановлением.',
  ]},
  { version: 'V3.3', changes: [
    'pHash-дедупликация при загрузке.',
    'Удаление проектов.',
  ]},
  { version: 'V3.0', changes: [
    'Zoom/Pan холста, undo/redo.',
    'Мультивыбор, нудж стрелками.',
    'Флаг сложных кадров.',
  ]},
  { version: 'V2.0', changes: [
    'Корзина и мягкое удаление.',
    'Импорт разметки.',
    'Экспорт статистики.',
  ]},
  { version: 'V1.0', changes: [
    'Первый MVP: загрузка, letterbox 640×640.',
    'Авторазметка YOLO, экспорт YOLO/COCO.',
  ]},
];

function openVersions() { renderVersions(); openModal('versionsModal'); }
function closeVersions() { closeModal('versionsModal'); }
function renderVersions() {
  const list = document.getElementById('versionsList');
  if (!list) return;
  const frag = document.createDocumentFragment();
  VERSION_HISTORY.forEach(v => {
    const div = document.createElement('div');
    div.className = 'version-entry';
    const header = document.createElement('div');
    header.className = 'version-header';
    const num = document.createElement('span');
    num.className = 'version-num'; num.textContent = v.version;
    header.appendChild(num);
    if (v.current) {
      const cur = document.createElement('span');
      cur.className = 'version-current'; cur.textContent = t('versions.current');
      header.appendChild(cur);
    }
    div.appendChild(header);
    const ul = document.createElement('ul');
    ul.className = 'version-changes';
    let currentLi = null;
    v.changes.forEach(c => {
      const isContinuation = /^\s/.test(c);
      if (isContinuation && currentLi) {
        currentLi.appendChild(document.createElement('br'));
        currentLi.appendChild(document.createTextNode(c.replace(/^\s+/, '')));
      } else {
        const li = document.createElement('li');
        li.textContent = c;
        ul.appendChild(li);
        currentLi = li;
      }
    });
    div.appendChild(ul);
    frag.appendChild(div);
  });
  list.innerHTML = '';
  list.appendChild(frag);
}

// V8.1.0: TTA — сохраняется в localStorage, отправляется в autolabel.
function getTta() { try { return localStorage.getItem('pdb_tta') === '1'; } catch (e) { return false; } }
function setTta(v) {
  try { localStorage.setItem('pdb_tta', v ? '1' : '0'); } catch (e) {}
  const cb = document.getElementById('ttaToggle');
  if (cb) cb.checked = !!v;
}

/* ===== Shortcuts / Settings ===== */
function openShortcuts() { openModal('shortcutsModal'); }
function closeShortcuts() { closeModal('shortcutsModal'); }
async function openSettings() {
  updateThemeSegment();
  document.getElementById('hideHintsToggle').checked = getHideHints();
  const dbgToggle = document.getElementById('debugModeToggle');
  if (dbgToggle) dbgToggle.checked = getDebugMode();
  updateCurrentProjectInfo();

  // V7.9.1: модалка открывается мгновенно. Тяжёлые запросы идут фоном,
  // иначе открытие настроек ждало от 2 до 5 секунд из-за перебора моделей.
  openModal('settingsModal');
  _refreshStorageInfo();
  _refreshFfmpegStatus();

  // trash_ttl — маленький запрос
  (async () => {
    try {
      const s = await api('/api/settings/trash_ttl');
      document.getElementById('trashTtlInput').value = s.days;
      _originalTrashTtlDays = s.days;
    } catch (e) {
      document.getElementById('trashTtlInput').value = 30;
      _originalTrashTtlDays = 30;
    }
  })();

  // Список моделей — самый долгий (читает .pt через YOLO)
  loadModelsIntoUI().catch(() => {});

  // Статус bootstrap — фоном
  api('/api/models/bootstrap/status').then(bs => {
    if (bs.status === 'downloading') renderBootstrapStatus(bs);
    else renderBootstrapStatus({ status: 'idle' }, { skipTerminal: true });
  }).catch(() => {});
}
function closeSettings() {
  if (_migratePollTimer) { clearTimeout(_migratePollTimer); _migratePollTimer = null; }
  closeModal('settingsModal');
}
async function saveSettings() {
  const days = parseInt(document.getElementById('trashTtlInput').value, 10);
  if (isNaN(days) || days < 0) { setStatus('Введите число ≥ 0'); return; }
  const changed = (days !== _originalTrashTtlDays);
  try {
    await api('/api/settings/trash_ttl', { method: 'POST', body: new URLSearchParams({ days: String(days) }) });
    _originalTrashTtlDays = days;
    closeSettings();
    if (changed) setStatus(`Автоочистка: ${days === 0 ? 'выключена' : days + ' дн.'}`);
    haptic('success');
    if (viewMode === 'trash') await loadImages();
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function downloadModel() {
  const pretrain = document.getElementById('downloadPretrain').value;
  const size = document.getElementById('downloadSize').value;
  try {
    await api('/api/models/download', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ size, pretrain }),
    });
    setStatus(`<span class="status-spinner" aria-hidden="true"></span>Скачиваем yolov8${size}${pretrain === 'oiv7' ? '-oiv7' : ''}.pt…`, 0, null, { html: true });
    subscribeBootstrapEvents();
    haptic('light');
  } catch (e) {
    if (e.status === 409) setStatus('Уже идёт скачивание другой модели');
    else setError('Ошибка: ' + String(e.message).slice(0, 140));
  }
}
async function loadModelsIntoUI() {
  const wrap = document.getElementById('modelsList');
  wrap.innerHTML = '<div style="font-size:0.8125rem;color:var(--text-secondary);padding:8px 4px;">Загрузка…</div>';
  try {
    const r = await api('/api/models');
    wrap.innerHTML = '';
    if (!r.models.length) {
      const e = document.createElement('div');
      e.style.cssText = 'font-size:0.8125rem;color:var(--text-secondary);padding:8px 4px;';
      e.textContent = 'Моделей нет. Используй «Скачать» ниже или обучи новую.';
      wrap.appendChild(e);
      return;
    }
    let compat = {};
    if (currentProjectMeta && currentProjectMeta.object_class) {
      try {
        compat = await api('/api/models/compatibility?object_class=' +
          encodeURIComponent(currentProjectMeta.object_class));
      } catch (e) { compat = {}; }
    }
    const frag = document.createDocumentFragment();
    r.models.forEach(m => {
      const row = document.createElement('div');
      row.className = 'model-row' + (m.name === r.active ? ' active' : '');
      row.dataset.modelName = m.name;
      row.setAttribute('role', 'radio');
      row.setAttribute('aria-checked', m.name === r.active ? 'true' : 'false');
      row.setAttribute('tabindex', '0');
      row.onclick = async (e) => {
        if (e.target.closest('.model-edit') || e.target.closest('.model-del')) return;
        const curActiveEl = document.querySelector('#modelsList .model-row.active');
        const curActive = curActiveEl ? curActiveEl.dataset.modelName : null;
        if (m.name === curActive) return;
        await activateModel(m.name);
      };
      row.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); }
      });
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.className = 'model-radio';
      radio.name = 'active_model_radio';
      radio.checked = (m.name === r.active);
      radio.setAttribute('aria-label', `Активировать ${m.name}`);
      radio.onclick = (e) => { e.preventDefault(); };
      row.appendChild(radio);
      const name = document.createElement('span');
      name.className = 'model-name'; name.textContent = m.name;
      row.appendChild(name);
      const ci = compat[m.name];
      if (ci && ci.compatible === false && currentProjectMeta && currentProjectMeta.object_class) {
        const warn = document.createElement('span');
        warn.className = 'model-warn';
        warn.dataset.tooltip = `Не знает класс «${currentProjectMeta.object_class}». Авторазметка работать не будет.`;
        warn.setAttribute('aria-label', 'Модель не поддерживает класс проекта');
        warn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
        row.appendChild(warn);
        row.classList.add('model-incompatible');
      }
      const meta = document.createElement('span');
      meta.className = 'model-meta';
      meta.textContent = fmtSize(m.size) + ' · ' + m.created_at.replace('T', ' ').slice(0, 16);
      row.appendChild(meta);
      const editBtn = document.createElement('button');
      editBtn.className = 'model-edit';
      editBtn.setAttribute('aria-label', 'Переименовать модель');
      editBtn.dataset.tooltip = 'Переименовать';
      editBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>';
      editBtn.onclick = async (e) => { e.stopPropagation(); await renameModel(m.name); };
      row.appendChild(editBtn);
      const del = document.createElement('button');
      del.className = 'model-del';
      del.setAttribute('aria-label', 'Удалить модель');
      del.dataset.tooltip = 'Удалить';
      del.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>';
      del.onclick = async (e) => { e.stopPropagation(); await deleteModel(m.name); };
      row.appendChild(del);
      frag.appendChild(row);
    });
    wrap.appendChild(frag);
  } catch (e) {
    wrap.innerHTML = '<div style="font-size:0.8125rem;color:var(--danger);padding:8px 4px;">Ошибка: ' + escapeHtml(e.message) + '</div>';
  }
}
async function activateModel(name) {
  try {
    await api('/api/models/activate', { method: 'POST', body: new URLSearchParams({ name }) });
    document.querySelectorAll('#modelsList .model-row').forEach(row => {
      const isActive = (row.dataset.modelName === name);
      row.classList.toggle('active', isActive);
      row.setAttribute('aria-checked', isActive ? 'true' : 'false');
      const radio = row.querySelector('.model-radio');
      if (radio) radio.checked = isActive;
    });
    invalidateObjectClasses();
    setStatus(t('toast.modelActive', { name }));
    haptic('selection');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function deleteModel(name) {
  const ok = await showConfirm(
    t('confirm.deleteModel.title', { name }),
    t('confirm.deleteModel.text'),
    { okText: t('confirm.deletePerm.ok'), danger: true }
  );
  if (!ok) return;
  haptic('warning');
  try {
    await api(`/api/models/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await loadModelsIntoUI();
    setStatus(t('toast.modelDeleted'));
  } catch (e) {
    if (e.status === 400) setStatus(String(e.message).slice(0, 160));
    else setError('Ошибка: ' + String(e.message).slice(0, 160));
  }
}
async function renameModel(oldName) {
  const stem = oldName.toLowerCase().endsWith('.pt') ? oldName.slice(0, -3) : oldName;
  const newName = await showPrompt('Переименовать модель', {
    text: `Новое имя для «${oldName}»:`,
    defaultValue: stem,
    hint: 'Латиница, цифры, дефис, подчёркивание, точка, пробел, скобки.',
    okText: 'Переименовать',
  });
  if (newName === null) return;
  const nm = String(newName).trim();
  if (!nm) { setStatus('Пустое имя'); return; }
  if (nm === stem) return;
  try {
    const r = await api(`/api/models/${encodeURIComponent(oldName)}/rename`, {
      method: 'POST', body: new URLSearchParams({ new_name: nm }),
    });
    await loadModelsIntoUI();
    setStatus(t('toast.modelRenamed', { old: r.old, name: r.name }));
    haptic('success');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 140)); }
}

/* ===== Training ===== */
// V8.7.0: переключатель задача (detect / pose).
let _trainTask = 'detect';

function getTrainTask() { return _trainTask; }

function setTrainTask(task) {
  if (!['detect', 'pose'].includes(task)) task = 'detect';
  _trainTask = task;
  const seg = document.getElementById('trainTaskSegment');
  if (seg) {
    seg.querySelectorAll('button[data-task]').forEach(b => {
      const active = b.dataset.task === task;
      b.classList.toggle('active', active);
      b.setAttribute('aria-checked', active ? 'true' : 'false');
      b.setAttribute('tabindex', active ? '0' : '-1');
    });
  }
  // Скрываем/показываем предупреждение о данных.
  _refreshTrainDatasetWarn();
  haptic('selection');
}

async function _refreshTrainDatasetWarn() {
  const warnEl = document.getElementById('trainDatasetWarn');
  if (!warnEl || !currentProjectId) return;
  if (_trainTask === 'pose') {
    try {
      const r = await api(`/api/projects/${currentProjectId}/skeletons_count`);
      const n = r.count || 0;
      const min = r.min_required || 30;
      warnEl.style.display = 'block';
      if (n < min) {
        warnEl.style.background = 'rgba(255,59,48,0.12)';
        warnEl.style.color = 'var(--danger)';
        warnEl.innerHTML = t('train.pose.notEnough', { n, min });
      } else if (n < 100) {
        warnEl.style.background = 'rgba(255,149,0,0.12)';
        warnEl.style.color = 'var(--warning)';
        warnEl.innerHTML = t('train.pose.maybeEnough', { n });
      } else {
        warnEl.style.background = 'rgba(52,199,89,0.12)';
        warnEl.style.color = 'var(--success)';
        warnEl.innerHTML = t('train.pose.good', { n });
      }
    } catch (e) { warnEl.style.display = 'none'; }
  } else {
    // Для detect — старая логика из openTrainModal
    try {
      const s = await api(`/api/projects/${currentProjectId}/stats`);
      const annotated = s.annotated_images || 0;
      if (annotated < 30) {
        warnEl.style.display = 'block';
        warnEl.style.background = 'rgba(255,149,0,0.12)';
        warnEl.style.color = 'var(--warning)';
        warnEl.innerHTML = t('train.warnLow', { n: annotated, total: s.total_images });
      } else if (annotated < 100) {
        warnEl.style.display = 'block';
        warnEl.style.background = 'rgba(10,132,255,0.1)';
        warnEl.style.color = 'var(--accent)';
        warnEl.innerHTML = t('train.warnMid', { n: annotated });
      } else {
        warnEl.style.display = 'none';
      }
    } catch (e) { warnEl.style.display = 'none'; }
  }
}

function _installTrainTaskSegment() {
  const seg = document.getElementById('trainTaskSegment');
  if (!seg || seg.__bound) return;
  seg.__bound = true;
  seg.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-task]');
    if (!b) return;
    setTrainTask(b.dataset.task);
  });
}

async function openTrainModal() {
  closeSettings();
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const warnEl = document.getElementById('trainDatasetWarn');
  warnEl.style.display = 'none';
  // V8.7.0: восстановить задачу + предупреждение.
  _installTrainTaskSegment();
  setTrainTask(_trainTask);
  setTimeout(() => { openModal('trainModal'); refreshTrainStatus(); }, 80);
}
function closeTrainModal() {
  closeModal('trainModal');
  if (trainEventSource) { try { trainEventSource.close(); } catch (e) {} trainEventSource = null; }
  // V7.9.3: индикатор сбрасываем при закрытии модалки только если обучение
  // реально не идёт — иначе он должен остаться пульсировать в сайдбаре.
  api('/api/train/status').then(_updateTrainingIndicator).catch(() => {});
}
async function startTraining() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const pretrain = document.getElementById('trainPretrain').value;
  const baseModel = document.getElementById('trainBaseModel').value;
  const customName = document.getElementById('trainModelName').value.trim();
  const epochs = parseInt(document.getElementById('trainEpochs').value, 10) || 50;
  const imgsz = parseInt(document.getElementById('trainImgsz').value, 10) || 640;
  const freeze = parseInt(document.getElementById('trainFreeze').value, 10);
  const lr0 = parseFloat(document.getElementById('trainLr0').value);
  const fd = new FormData();
  fd.append('project_id', String(currentProjectId));
  fd.append('task', _trainTask);   // V8.7.0
  fd.append('base_model', baseModel);
  fd.append('pretrain_dataset', pretrain);
  fd.append('model_name', customName);
  fd.append('epochs', String(epochs));
  fd.append('imgsz', String(imgsz));
  fd.append('freeze', String(isNaN(freeze) ? 8 : Math.min(9, Math.max(0, freeze))));
  fd.append('lr0', String(isNaN(lr0) ? 0.001 : lr0));
  try {
    await api('/api/train/start', { method: 'POST', body: fd });
    // V8.1.0: запрашиваем разрешение на системные уведомления.
    _ensureNotificationPermission();
    document.getElementById('trainForm').style.display = 'none';
    document.getElementById('trainProgressWrap').style.display = '';
    document.getElementById('trainStartBtn').style.display = 'none';
    document.getElementById('trainStopBtn').style.display = '';
    setStatus(t('toast.trainStarted'));
    subscribeTrainEvents();
    haptic('success');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 140)); }
}
async function stopTraining() {
  try {
    await api('/api/train/stop', { method: 'POST' });
    // V7.9.3: спиннер показывает, что процесс идёт; ttl=0 — ждём финального статуса.
    setStatus(`<span class="status-spinner" aria-hidden="true"></span>${t('toast.trainStopping')}`, 0, null, { html: true });
    haptic('warning');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}
async function refreshTrainStatus() {
  try {
    const s = await api('/api/train/status');
    renderTrainState(s);
    if (s.status === 'running' || s.status === 'stopping' || s.status === 'preparing') {
      document.getElementById('trainForm').style.display = 'none';
      document.getElementById('trainProgressWrap').style.display = '';
      document.getElementById('trainStartBtn').style.display = 'none';
      document.getElementById('trainStopBtn').style.display = '';
      subscribeTrainEvents();
    } else {
      document.getElementById('trainForm').style.display = '';
      document.getElementById('trainProgressWrap').style.display = 'none';
      document.getElementById('trainStartBtn').style.display = '';
      document.getElementById('trainStopBtn').style.display = 'none';
    }
  } catch (e) {}
}
function subscribeTrainEvents() {
  _lastLiveEpochs = [];
  _lastRenderedLiveEpochs = null;
  if (trainEventSource) { try { trainEventSource.close(); } catch (e) {} }
  const es = new EventSource('/api/train/events');
  trainEventSource = es;
  es.onmessage = (ev) => {
    try {
      const s = JSON.parse(ev.data);
      renderTrainState(s);
      if (s.status === 'done' || s.status === 'error' || s.status === 'stopped') {
        // V7.9.3: терминальный статус замещает висящий «Останавливаю…»,
        // и через 5–8 секунд глобальная плашка в тулбаре сама гаснет.
        if (s.status === 'stopped') setStatus(s.message || 'Обучение остановлено', 5000);
        else if (s.status === 'done') setSuccess(s.message || 'Обучение завершено', 6000);
        else setError(s.message || 'Ошибка обучения', 8000);
        // V8.1.0: системное уведомление, если вкладка свёрнута/в фоне.
        try {
          if (document.hidden) {
            const t = s.status === 'done' ? 'Обучение завершено'
                    : s.status === 'stopped' ? 'Обучение остановлено'
                    : 'Ошибка обучения';
            _showTrainingNotification(t, s.model_name ? `Модель: ${s.model_name}` : (s.message || ''));
          }
        } catch (e) {}
        es.close(); trainEventSource = null;
        loadModelsIntoUI();
      }
    } catch (e) {}
  };
  es.onerror = () => { try { es.close(); } catch (e) {} trainEventSource = null; };
}
// V7.9.3: индикатор обучения на иконке настроек — виден, даже когда
// модалка обучения закрыта. Пульсирующая точка + смена tooltip.
function _updateTrainingIndicator(s) {
  const btn = document.getElementById('settingsBtn');
  if (!btn) return;
  const isTraining = (s && (s.status === 'running' || s.status === 'stopping' || s.status === 'preparing'));
  btn.classList.toggle('training-pulse', !!isTraining);
  const label = isTraining ? 'Настройки — обучение идёт' : 'Настройки';
  btn.dataset.tooltip = label;
  btn.setAttribute('aria-label', label);
}

function renderTrainState(s) {
  _updateTrainingIndicator(s);
  const badge = document.getElementById('trainStatusBadge');
  const map = {
    idle:      t('train.status.idle'),
    preparing: t('train.status.preparing'),
    running:   t('train.status.running'),
    stopping:  t('train.status.stopping'),
    done:      t('train.status.done'),
    error:     t('train.status.error'),
    stopped:   t('train.status.stopped'),
  };
  badge.textContent = map[s.status] || s.status;
  badge.className = 'train-status-badge ' + (s.status === 'stopping' || s.status === 'preparing' ? 'running' : s.status);
  const pct = Math.round(s.progress || 0);
  document.getElementById('trainProgressFill').style.width = (s.progress || 0) + '%';
  const bar = document.getElementById('trainProgressBar');
  if (bar) bar.setAttribute('aria-valuenow', String(pct));
  document.getElementById('trainEpochText').textContent = `Эпоха ${s.current_epoch || 0} / ${s.total_epochs || 0}`;
  document.getElementById('trainPercentText').textContent = (s.progress || 0).toFixed(1) + '%';
  document.getElementById('trainMessage').textContent = s.message || '';
  document.getElementById('trainModelResult').textContent = s.model_name ? `→ ${s.model_name}` : '';
  const logEl = document.getElementById('trainLog');
  if (logEl && s.log_lines && s.log_lines.length) {
    logEl.textContent = s.log_lines.slice(-80).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
  }
  const live = (s.live_epochs && s.live_epochs.length) ? s.live_epochs : _lastLiveEpochs;
  if (s.live_epochs && s.live_epochs.length) _lastLiveEpochs = s.live_epochs;
  const liveWrap = document.getElementById('trainLiveCharts');
  if (liveWrap) {
    if (live.length >= 2) {
      liveWrap.style.display = '';
      // Перерисовываем только когда данные реально изменились.
      if (live !== _lastRenderedLiveEpochs) {
        _renderLiveTrainCharts(liveWrap, live);
        _lastRenderedLiveEpochs = live;
      }
    } else {
      liveWrap.style.display = 'none';
    }
  }
  if (s.status === 'done' || s.status === 'error' || s.status === 'stopped') {
    document.getElementById('trainStartBtn').style.display = '';
    document.getElementById('trainStopBtn').style.display = 'none';
  }
  const mBtn = document.getElementById('trainMetricsBtn');
  if (mBtn) {
    if (s.status === 'done' || s.status === 'stopped') mBtn.style.display = '';
    else if (s.status === 'idle') mBtn.style.display = 'none';
  }
}
function _renderLiveTrainCharts(wrap, epochs) {
  const W = 400, H = 120, PAD_L = 30, PAD_R = 8, PAD_T = 8, PAD_B = 16;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const n = epochs.length;
  const svgNS = 'http://www.w3.org/2000/svg';
  wrap.innerHTML = '';
  const mk = (title, series, yMax) => {
    const block = document.createElement('div');
    block.className = 'train-live-chart';
    const t = document.createElement('div');
    t.className = 'train-live-title'; t.textContent = title;
    block.appendChild(t);
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    let hi = yMax;
    if (hi == null) {
      hi = 0.01;
      series.forEach(s => { s.values.forEach(v => { if (v != null && v > hi) hi = v; }); });
      hi = hi * 1.1;
    }
    const lo = 0;
    for (let i = 0; i <= 3; i++) {
      const y = PAD_T + plotH - (i / 3) * plotH;
      const ln = document.createElementNS(svgNS, 'line');
      ln.setAttribute('x1', PAD_L); ln.setAttribute('x2', W - PAD_R);
      ln.setAttribute('y1', y); ln.setAttribute('y2', y);
      ln.setAttribute('stroke', 'currentColor');
      ln.setAttribute('stroke-opacity', '0.08');
      svg.appendChild(ln);
      const txt = document.createElementNS(svgNS, 'text');
      txt.setAttribute('x', PAD_L - 4); txt.setAttribute('y', y + 3);
      txt.setAttribute('text-anchor', 'end');
      txt.setAttribute('class', 'metrics-chart-axis');
      const val = lo + (hi - lo) * (i / 3);
      txt.textContent = val < 1 ? val.toFixed(2) : val.toFixed(1);
      svg.appendChild(txt);
    }
    series.forEach(s => {
      let d = '';
      for (let i = 0; i < n; i++) {
        const v = s.values[i];
        if (v == null) continue;
        const x = PAD_L + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
        const y = PAD_T + plotH - ((v - lo) / (hi - lo)) * plotH;
        d += (d ? ' L ' : 'M ') + x.toFixed(1) + ' ' + y.toFixed(1);
      }
      if (!d) return;
      const path = document.createElementNS(svgNS, 'path');
      path.setAttribute('d', d);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', s.color);
      path.setAttribute('stroke-width', '1.8');
      svg.appendChild(path);
    });
    block.appendChild(svg);
    const leg = document.createElement('div');
    leg.className = 'metrics-chart-legend';
    series.forEach(s => {
      const it = document.createElement('span');
      it.className = 'metrics-legend-item';
      it.innerHTML = `<span class="metrics-legend-dot" style="background:${s.color}"></span>${s.label}`;
      leg.appendChild(it);
    });
    block.appendChild(leg);
    wrap.appendChild(block);
  };
  mk('mAP', [
    { label: 'mAP@50', color: 'var(--accent)', values: epochs.map(e => e.mAP50) },
    { label: 'mAP@50-95', color: 'var(--success)', values: epochs.map(e => e.mAP50_95) },
  ], 1);
  mk('Loss', [
    { label: 'train box', color: 'var(--accent)', values: epochs.map(e => e.train_box_loss) },
    { label: 'val box', color: 'var(--danger)', values: epochs.map(e => e.val_box_loss) },
  ], null);
}

/* ===== Batch autolabel ===== */
async function autolabelAllUnlabeled() {
  if (viewMode !== 'main') return;
  if (batchRunning) { setStatus('Батч уже идёт'); return; }
  const unlabeled = allImages.filter(i => i._kind !== 'project' && (i.annotation_count || 0) === 0);
  if (!unlabeled.length) { setStatus('Все уже размечены'); return; }
  const ok = await showConfirm(
    t('confirm.autolabelAll.title', { n: unlabeled.length }),
    t('confirm.autolabelAll.text'),
    { okText: t('confirm.autolabelAll.ok') }
  );
  if (!ok) return;
  const ids = unlabeled.map(i => i.id);
  try {
    await api('/api/autolabel/batch/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_ids: ids, project_id: currentProjectId,
        tta: getTta(), mode: getAutolabelMode(),
      }),
    });
    batchRunning = true;
    subscribeBatchEvents();
  } catch (e) {
    if (e.status === 501) setStatus(t('toast.noModelAutolabel'), 8000);
    else setError('Ошибка: ' + String(e.message).slice(0, 140));
  }
}
function subscribeBatchEvents() {
  if (batchEventSource) { try { batchEventSource.close(); } catch (e) {} }
  const es = new EventSource('/api/autolabel/batch/events');
  batchEventSource = es;
  es.onmessage = (ev) => {
    try {
      const s = JSON.parse(ev.data);
      renderBatchState(s);
      if (s.current_id && !prefersReducedMotion()) {
        const row = document.querySelector(`#imageListInner .img-row[data-image-id="${s.current_id}"]`);
        if (row && !row.classList.contains('batch-processed')) {
          row.classList.add('batch-processed');
          setTimeout(() => row.classList.remove('batch-processed'), 620);
        }
      }
      if (s.status !== 'running') {
        es.close(); batchEventSource = null; batchRunning = false;
        loadImages().then(() => {
          if (currentImageId) {
            api(`/api/images/${currentImageId}/annotations`).then(anns => {
              boxes = anns;
              renderBoxes({ animateIndices: new Set(boxes.map((_, i) => i)) });
              resetHistory(); markClean();
            }).catch(() => {});
          }
        });
      }
    } catch (e) {}
  };
  es.onerror = () => { try { es.close(); } catch (e) {} batchEventSource = null; batchRunning = false; };
}
function renderBatchState(s) {
  const fill = document.getElementById('progressFill');
  const label = document.getElementById('progressLabel');
  const text = document.getElementById('progressText');
  const bar = document.getElementById('progressBar');
  const btn = document.getElementById('batchAutolabelBtn');
  if (s.status === 'running') {
    label.textContent = 'Авторазметка';
    const pct = s.total > 0 ? (s.done / s.total * 100) : 0;
    fill.style.width = pct.toFixed(1) + '%';
    fill.classList.add('batch');
    text.textContent = `${s.done} / ${s.total}`;
    if (bar) bar.setAttribute('aria-valuenow', String(Math.round(pct)));
    btn.disabled = true; btn.style.opacity = '0.5';
    const milestone = Math.floor(pct / 25) * 25;
    if (milestone !== renderBatchState._lastMilestone && milestone > 0) {
      renderBatchState._lastMilestone = milestone;
      setStatus(`Авторазметка: ${milestone}%`, 2000);
    }
  } else {
    btn.disabled = false; btn.style.opacity = '';
    fill.classList.remove('batch');
    renderBatchState._lastMilestone = 0;
    if (s.status === 'done') {
      let _msg = `Авторазметка завершена: ${s.done - s.failed} из ${s.total}`;
      if ((s.mode || 'add') === 'add' && s.added != null) {
        _msg += ` · +${s.added} новых`;
        if (s.skipped) _msg += `, ${s.skipped} пропущено`;
      }
      if (s.failed) _msg += `, ошибок: ${s.failed}`;
      setSuccess(_msg, 6000);
      haptic('success');
    } else if (s.status === 'stopped') {
      setStatus(`Остановлено. Обработано: ${s.done - s.failed}, ошибок: ${s.failed}`, 6000);
    } else if (s.status === 'error') {
      setError('Ошибка батча: ' + s.message, 6000);
    }
    setTimeout(() => updateProgress(), 1500);
  }
}

/* ===== Export ===== */
async function downloadFile(url, fallbackName) {
  try {
    setStatus(t('toast.downloading'), 60000);
    const res = await fetch(url);
    if (!res.ok) {
      let msg = 'Ошибка экспорта';
      try { msg = (await res.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename="?([^"]+)"?/.exec(cd);
    const name = m ? m[1] : fallbackName;
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(objUrl); a.remove(); }, 1000);
    setSuccess('Скачано: ' + name, 4000);
  } catch (e) { setError('Ошибка экспорта: ' + String(e.message).slice(0, 160)); }
}
function toggleExportMenu(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('exportMenu');
  const btn = document.getElementById('exportBtn');
  const isOpen = menu.classList.contains('open');
  closeAllPopovers(null);
  if (isOpen) { btn.setAttribute('aria-expanded', 'false'); return; }
  const r = btn.getBoundingClientRect();
  const MENU_W = 200;
  let left = r.left;
  if (left + MENU_W > window.innerWidth - 8) left = Math.max(8, window.innerWidth - MENU_W - 8);
  menu.style.left = left + 'px';
  menu.style.top = (r.bottom + 6) + 'px';
  menu.classList.add('open');
  btn.setAttribute('aria-expanded', 'true');
}
function exportYolo() { exportFormat = 'yolo'; document.getElementById('exportMenu').classList.remove('open'); openExportModal(); }
function exportCoco() { exportFormat = 'coco'; document.getElementById('exportMenu').classList.remove('open'); openExportModal(); }
function openExportModal() { openModal('exportModal'); }
function closeExportModal() { closeModal('exportModal'); }
async function executeExport() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const naming = (document.querySelector('input[name="export_naming"]:checked') || {}).value || 'numbered';
  const split = (document.querySelector('input[name="export_split"]:checked') || {}).value || 'none';
  closeExportModal();
  const url = `/api/projects/${currentProjectId}/export/${exportFormat}?naming=${encodeURIComponent(naming)}&split=${encodeURIComponent(split)}`;
  const fallback = `${exportFormat}_project_${currentProjectId}.zip`;
  await downloadFile(url, fallback);
}

/* ===== Navigation ===== */
async function navigateImage(direction) {
  if (viewMode !== 'main') return;
  if (!imagesList.length) return;
  let idx = imagesList.findIndex(img => img.id === currentImageId && _isImageItem(img));
  if (idx < 0) idx = direction > 0 ? -1 : imagesList.length;
  idx += direction;
  if (idx < 0) idx = 0;
  if (idx >= imagesList.length) idx = imagesList.length - 1;
  const target = imagesList[idx];
  if (!target || target.id === currentImageId || !_isImageItem(target)) return;
  await selectImage(target.id);
}
async function navigateToNextUnlabeled() {
  if (viewMode !== 'main') return;
  if (!imagesList.length) return;
  const idx = imagesList.findIndex(i => i.id === currentImageId);
  for (let i = idx + 1; i < imagesList.length; i++) {
    if (_isImageItem(imagesList[i]) && (imagesList[i].annotation_count || 0) === 0) { await selectImage(imagesList[i].id, { skipDirtyCheck: true }); return; }
  }
  for (let i = 0; i < Math.max(0, idx); i++) {
    if (_isImageItem(imagesList[i]) && (imagesList[i].annotation_count || 0) === 0) { await selectImage(imagesList[i].id, { skipDirtyCheck: true }); return; }
  }
  setStatus(t('toast.allAnnotated'));
}
async function navigateToPrevUnlabeled() {
  if (viewMode !== 'main') return;
  if (!imagesList.length) return;
  let idx = imagesList.findIndex(i => i.id === currentImageId);
  if (idx < 0) idx = imagesList.length;
  for (let i = idx - 1; i >= 0; i--) {
    if (_isImageItem(imagesList[i]) && (imagesList[i].annotation_count || 0) === 0) { await selectImage(imagesList[i].id, { skipDirtyCheck: true }); return; }
  }
  for (let i = imagesList.length - 1; i > idx; i--) {
    if (_isImageItem(imagesList[i]) && (imagesList[i].annotation_count || 0) === 0) { await selectImage(imagesList[i].id, { skipDirtyCheck: true }); return; }
  }
  setStatus(t('toast.allAnnotated'));
}
async function acceptAndNext() {
  if (!currentImageId) return;
  const savedId = currentImageId;
  try {
    await api(`/api/images/${savedId}/annotations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(boxes),
    });
    markSavedWithPulse();
    // V8.1.0: без loadImages — обновим локально и пойдём дальше.
    _updateImageMeta(savedId);
    updateProgress();
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); return; }
  if (!imagesList.length) return;
  const idx = imagesList.findIndex(i => i.id === currentImageId);
  let next = null;
  for (let i = idx + 1; i < imagesList.length; i++) {
    if (_isImageItem(imagesList[i]) && (imagesList[i].annotation_count || 0) === 0) { next = imagesList[i]; break; }
  }
  if (!next) for (let i = 0; i < idx; i++) {
    if (_isImageItem(imagesList[i]) && (imagesList[i].annotation_count || 0) === 0) { next = imagesList[i]; break; }
  }
  if (!next && idx + 1 < imagesList.length && _isImageItem(imagesList[idx + 1])) next = imagesList[idx + 1];
  if (next) {
    await selectImage(next.id, { skipDirtyCheck: true });
    setStatus(`Принято → ${next.filename}`);
  } else setStatus(t('toast.endOfList'));
}

/* ===== Boxes ===== */
function currentObjectClass() {
  return (currentProjectMeta && currentProjectMeta.object_class) || 'pig';
}
function confColor(conf) {
  if (conf == null) return 'var(--box-manual)';
  if (conf >= 0.75) return 'var(--box-high)';
  if (conf >= 0.5) return 'var(--box-mid)';
  return 'var(--box-low)';
}
function confLabelText(b) {
  if (b.confidence == null) return b.label || currentObjectClass();
  return `${b.label || currentObjectClass()} ${b.confidence.toFixed(2)}`;
}
function _boxAriaLabel(b) {
  const conf = b.confidence != null ? `уверенность ${b.confidence.toFixed(2)}` : 'ручная';
  const frozen = b.frozen ? ', заморожена' : '';
  return `${b.label || currentObjectClass()}, ${conf}${frozen}`;
}
function _createBoxElement(b, i) {
  const div = document.createElement('div');
  div.className = 'box';
  div.setAttribute('role', 'listitem');
  div.setAttribute('tabindex', '0');
  div.setAttribute('aria-label', _boxAriaLabel(b));
  if (b.frozen) div.classList.add('frozen');
  if (i === selectedIndex) div.classList.add('selected');
  if (multiSelected.has(i)) div.classList.add('multi-selected');
  if (b.y * 640 < 26) div.classList.add('label-below');
  div.dataset.idx = i;
  div.style.setProperty('--box-color', confColor(b.confidence));
  div.style.left = (b.x * 640) + 'px';
  div.style.top = (b.y * 640) + 'px';
  div.style.width = (b.w * 640) + 'px';
  div.style.height = (b.h * 640) + 'px';
  const label = document.createElement('span');
  label.className = 'box-label';
  label.setAttribute('aria-hidden', 'true');
  label.textContent = confLabelText(b);
  div.appendChild(label);
  // V8.3.0: бейджи поведения и animal_id.
  if (b.behavior) {
    const bb = document.createElement('span');
    bb.className = 'box-beh-badge';
    bb.dataset.beh = b.behavior;
    bb.setAttribute('aria-hidden', 'true');
    bb.textContent = t('behavior.' + b.behavior);
    div.appendChild(bb);
  }
  if (b.animal_id != null) {
    const ab = document.createElement('span');
    ab.className = 'box-aid-badge';
    ab.setAttribute('aria-hidden', 'true');
    ab.textContent = '#' + b.animal_id;
    div.appendChild(ab);
  }
  if (!b.frozen) {
    ['n', 's', 'w', 'e'].forEach(edge => {
      const ed = document.createElement('div');
      ed.className = 'box-edge box-edge-' + edge;
      ed.setAttribute('aria-hidden', 'true');
      div.appendChild(ed);
    });
    const del = document.createElement('div');
    del.className = 'box-delete';
    del.textContent = '×';
    del.setAttribute('role', 'button');
    del.setAttribute('tabindex', '0');
    del.setAttribute('aria-label', 'Удалить рамку');
    del.dataset.tooltip = 'Удалить';
    del.addEventListener('mousedown', e => e.stopPropagation());
    del.addEventListener('click', e => { e.stopPropagation(); deleteBox(i); });
    del.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); deleteBox(i); }
    });
    div.appendChild(del);
    ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].forEach(h => {
      const hd = document.createElement('div');
      hd.className = 'handle handle-' + h;
      hd.dataset.handle = h;
      div.appendChild(hd);
    });
  } else {
    const fr = document.createElement('span');
    fr.className = 'box-freeze-badge';
    fr.setAttribute('aria-hidden', 'true');
    fr.textContent = '🔒';
    div.appendChild(fr);
  }
  return div;
}
function renderBoxes(opts = {}) {
  const layer = document.getElementById('boxes');
  layer.innerHTML = '';
  const animateIndices = opts.animateIndices || null;
  const settlingIdx = (typeof opts.settlingIdx === 'number') ? opts.settlingIdx : -1;
  const animList = animateIndices ? Array.from(animateIndices) : null;
  boxes.forEach((b, i) => {
    const div = _createBoxElement(b, i);
    if (animList && animList.includes(i) && !prefersReducedMotion()) {
      div.classList.add('box-enter');
      const order = animList.indexOf(i);
      const total = animList.length;
      const step = total <= 10 ? 40 : (total <= 25 ? 20 : 8);
      div.style.animationDelay = Math.min(order * step, 500) + 'ms';
    }
    if (i === settlingIdx && !prefersReducedMotion()) div.classList.add('settling');
    layer.appendChild(div);
  });
  updateDelBoxBtn();
  updateFreezeBtn();
  if (typeof _refreshAttrBar === 'function') _refreshAttrBar();   // V8.3.1
  // V8.8.6: рендеры в очередь, motion vector с debounce.
  scheduleRenderSkeleton();
  scheduleRefreshMotionVectorDebounced(200);
}
function updateBoxInPlace(idx) {
  const el = document.querySelector(`#boxes .box[data-idx="${idx}"]`);
  if (!el) return;
  const b = boxes[idx];
  el.style.left = (b.x * 640) + 'px';
  el.style.top = (b.y * 640) + 'px';
  el.style.width = (b.w * 640) + 'px';
  el.style.height = (b.h * 640) + 'px';
  el.style.setProperty('--box-color', confColor(b.confidence));
  el.setAttribute('aria-label', _boxAriaLabel(b));
  if (b.y * 640 < 26) el.classList.add('label-below'); else el.classList.remove('label-below');
  const lbl = el.querySelector('.box-label');
  if (lbl) lbl.textContent = confLabelText(b);
  // V8.3.0: обновляем бейджи.
  const oldBeh = el.querySelector('.box-beh-badge');
  if (oldBeh) oldBeh.remove();
  const oldAid = el.querySelector('.box-aid-badge');
  if (oldAid) oldAid.remove();
  if (b.behavior) {
    const bb = document.createElement('span');
    bb.className = 'box-beh-badge';
    bb.dataset.beh = b.behavior;
    bb.setAttribute('aria-hidden', 'true');
    bb.textContent = t('behavior.' + b.behavior);
    el.appendChild(bb);
  }
  if (b.animal_id != null) {
    const ab = document.createElement('span');
    ab.className = 'box-aid-badge';
    ab.setAttribute('aria-hidden', 'true');
    ab.textContent = '#' + b.animal_id;
    el.appendChild(ab);
  }
}
function updateSelectionClasses() {
  document.querySelectorAll('#boxes .box').forEach((el, i) => {
    el.classList.toggle('selected', i === selectedIndex);
    el.classList.toggle('multi-selected', multiSelected.has(i));
  });
  updateDelBoxBtn();
  updateFreezeBtn();
  _refreshAttrBar();   // V8.3.0
  // V8.5.7: рендер скелета сам синхронизирует keypoints из boxes.
  if (typeof renderSkeleton === 'function') renderSkeleton();

  // V8.8.2: пересчёт вектора движения после смены выделения.
  if (typeof _refreshMotionVector === 'function') _refreshMotionVector();
}
function updateDelBoxBtn() {
  const btn = document.getElementById('delBoxBtn');
  if (!btn) return;
  const indices = getSelectedIndices();
  const freezable = indices.filter(i => !boxes[i].frozen);
  const ok = freezable.length > 0;
  btn.disabled = !ok; btn.style.opacity = ok ? '' : '0.5';
  btn.innerHTML = (ok && freezable.length > 1)
    ? `Удалить (${freezable.length}) <kbd>D</kbd>`
    : `Удалить рамку <kbd>D</kbd>`;
}
function getSelectedIndices() {
  const set = new Set(multiSelected);
  if (selectedIndex >= 0 && selectedIndex < boxes.length) set.add(selectedIndex);
  return Array.from(set).sort((a, b) => a - b);
}
function deleteBox(idx) {
  if (idx < 0 || idx >= boxes.length) return;
  if (boxes[idx].frozen) { setStatus(t('toast.frozenHint')); return; }
  // V7.9.2: элемент удаляется из DOM — без явного сброса тултип остаётся висеть.
  hideTooltip();
  boxes.splice(idx, 1);
  const newMulti = new Set();
  multiSelected.forEach(i => {
    if (i < idx) newMulti.add(i);
    else if (i > idx) newMulti.add(i - 1);
  });
  multiSelected = newMulti;
  if (selectedIndex === idx) selectedIndex = -1;
  else if (selectedIndex > idx) selectedIndex -= 1;
  renderBoxes(); pushHistory(); markDirty();
}
function deleteSelectedBox() {
  const indices = getSelectedIndices().filter(i => !boxes[i].frozen);
  if (!indices.length) return;
  hideTooltip();
  for (let i = indices.length - 1; i >= 0; i--) boxes.splice(indices[i], 1);
  const removed = indices.length;
  selectedIndex = -1; multiSelected.clear();
  renderBoxes(); pushHistory(); markDirty();
  setStatus(t('toast.deletedN', { n: removed }));
}
async function clearBoxes() {
  if (!boxes.length) return;
  if (boxes.length > 1) {
    const ok = await showConfirm(
      t('confirm.clearBoxes.title'),
      t('confirm.clearBoxes.text', { n: boxes.length }),
      { okText: t('confirm.clearBoxes.ok'), danger: true }
    );
    if (!ok) return;
  }
  boxes = []; selectedIndex = -1; multiSelected.clear();
  renderBoxes(); pushHistory(); markDirty();
}
async function saveAnnotations() {
  if (!currentImageId) return;
  const savedId = currentImageId;
  try {
    // V8.5.1: если скелет активен — синхронизируем в boxes.
    if (skeletonMode) _syncKeypointsToBox();
    await api(`/api/images/${savedId}/annotations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(boxes),
    });
    markSavedWithPulse();
    // V8.1.0: без сетевого рефетча — обновляем состояние одной картинки.
    _updateImageMeta(savedId);
    applyFiltersAndRender();
    _refreshRowMeta(savedId, { flash: true });
    setStatus(t('toast.savedN', { n: boxes.length }));
  } catch (e) { setError('Ошибка сохранения: ' + String(e.message).slice(0, 140)); }
}
async function runAutolabel() {
  if (!currentImageId) return;

  // V7.8.0: debug-режим
  if (getDebugMode()) {
    setStatus('Авторазметка (debug)...', 60000);
    try {
      const mode = getAutolabelMode();
      const r = await api(`/api/images/${currentImageId}/autolabel_debug`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, tta: getTta() }),
      });
      const allDets = r.detections || [];
      // V8.2.1: сервер сам сохранил — клиент только отображает,
      // сохраняем confidence/label/frozen как пришли.
      const _prevAutoBoxes = snapshot();   // V8.2.2: before
      const targetBoxes = (r.saved_boxes || []).map(d => ({
        x: d.x, y: d.y, w: d.w, h: d.h,
        label: d.label || currentObjectClass(),
        confidence: (typeof d.confidence === 'number') ? d.confidence : null,
        frozen: !!d.frozen,
      }));
      boxes = targetBoxes;
      selectedIndex = -1; multiSelected.clear();
      const nonTarget = allDets.filter(d => !d.is_target);
      _renderDebugBoxes(nonTarget);
      const animateIndices = new Set(boxes.map((_, i) => i));
      renderBoxes({ animateIndices });
      // V8.2.1: НЕ POST'им — сервер уже сохранил всё сам.
      // V8.2.2: не resetHistory, а push в историю.
      _restoreHistoryAfterAutolabel(_prevAutoBoxes);
      markSavedWithPulse();
      _updateImageMeta(currentImageId);
      applyFiltersAndRender();
      _refreshRowMeta(currentImageId, { flash: true });
      let msg = `Debug: всего ${r.total}, целевых ${r.target_count}`;
      if (mode === 'add') {
        msg += ` · +${r.added || 0} новых` + (r.skipped ? `, ${r.skipped} пропущено` : '');
      }
      setStatus(msg + ' (сохранено)', 6000, 'success');
      haptic('success');
    } catch (e) {
      haptic('error');
      if (e.status === 501) setStatus(t('toast.noModelAutolabel'), 8000);
      else setError('Debug-авторазметка: ' + String(e.message).slice(0, 180), 6000);
    }
    return;
  }

  const _mode = getAutolabelMode();
  setStatus('Авторазметка...', 60000);
  try {
    const r = await api(`/api/images/${currentImageId}/autolabel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tta: getTta(), mode: _mode }),
    });
    const _oldLen = boxes.length;
    const _prevAutoBoxes = snapshot();   // V8.2.2: before
    boxes = r.boxes || [];
    selectedIndex = -1; multiSelected.clear();
    const animateIndices = new Set(
      _mode === 'add'
        ? boxes.map((_, i) => i).filter(i => i >= _oldLen)
        : boxes.map((_, i) => i)
    );
    renderBoxes({ animateIndices });
    // V8.2.2: не resetHistory, а push в историю (Ctrl+Z откатит).
    _restoreHistoryAfterAutolabel(_prevAutoBoxes);
    markSavedWithPulse();
    _updateImageMeta(currentImageId);
    applyFiltersAndRender();
    _refreshRowMeta(currentImageId, { flash: true });
    if (_mode === 'add') {
      const added = r.added || 0;
      const skipped = r.skipped || 0;
      if (added === 0) {
        setStatus(skipped
          ? `Авторазметка: ничего нового (${skipped} ${plural(skipped, 'дубликат', 'дубликата', 'дубликатов')})`
          : 'Авторазметка: ничего не найдено');
      } else {
        setStatus(`Авторазметка: +${added} новых` +
          (skipped ? `, ${skipped} пропущено` : '') + ' (сохранено)');
      }
    } else {
      setStatus(`Авторазметка: ${boxes.length} рамок (сохранено)`);
    }
  } catch (e) {
    haptic('error');
    if (e.status === 501) setStatus(t('toast.noModelAutolabel'), 8000);
    else if (e.status === 422) setStatus(String(e.detail || 'Класс не поддерживается активной моделью'), 8000);
    else setError('Авторазметка недоступна: ' + String(e.message).slice(0, 160), 5000);
  }
}
async function autolabel() { if (!currentImageId) return; await runAutolabel(); }

/* ===== Sort / filter menus ===== */
function updateSortUI() {
  document.querySelectorAll('#sortMenu button').forEach(b => b.classList.toggle('active', b.dataset.sort === sortMode));
  document.getElementById('sortBtn').classList.toggle('active', sortMode !== 'name_asc');
}
async function setSortMode(mode) {
  if (!VALID_SORTS.includes(mode)) return;
  sortMode = mode;
  localStorage.setItem('pdb_sortMode', mode);
  updateSortUI();
  // V7.9.3: смена сортировки — перезапрос к серверу.
  await loadImages();
}
function setupSortMenu() {
  const btn = document.getElementById('sortBtn');
  const menu = document.getElementById('sortMenu');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.classList.contains('open')) {
      menu.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
      return;
    }
    closeAllPopovers(null);
    menu.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
  });
  menu.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      setSortMode(b.dataset.sort);
      menu.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    });
  });
  updateSortUI();
}
function setupFilterMenu() {
  const btn = document.getElementById('filterBtn');
  const menu = document.getElementById('filterMenu');
  const cbUA = document.getElementById('filterUnannotated');
  const cbLC = document.getElementById('filterLowConf');
  const cbH = document.getElementById('filterHard');
  const cbD = document.getElementById('filterDuplicates');
  cbUA.checked = activeFilter === 'unannotated';
  cbLC.checked = activeFilter === 'lowconf';
  cbH.checked = activeFilter === 'hard';
  if (cbD) cbD.checked = activeFilter === 'duplicates';
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.classList.contains('open')) {
      menu.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
      return;
    }
    closeAllPopovers(null);
    menu.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
  });
  menu.addEventListener('click', (e) => e.stopPropagation());
  async function setFilter(name, checked) {
    cbUA.checked = false; cbLC.checked = false; cbH.checked = false;
    if (cbD) cbD.checked = false;
    if (checked) {
      activeFilter = name;
      if (name === 'unannotated') cbUA.checked = true;
      if (name === 'lowconf') cbLC.checked = true;
      if (name === 'hard') cbH.checked = true;
      if (name === 'duplicates' && cbD) cbD.checked = true;
    } else activeFilter = 'none';
    localStorage.setItem('pdb_filter', activeFilter);
    updateFilterBadge();
    // V7.9.3: смена фильтра — перезапрос к серверу.
    await loadImages();
  }
  cbUA.addEventListener('change', () => setFilter('unannotated', cbUA.checked));
  cbLC.addEventListener('change', () => setFilter('lowconf', cbLC.checked));
  cbH.addEventListener('change', () => setFilter('hard', cbH.checked));
  if (cbD) cbD.addEventListener('change', () => setFilter('duplicates', cbD.checked));
  updateFilterBadge();
}

/* ===== Zoom / Pan ===== */
function getRel(e) {
  const vp = document.getElementById('canvasViewport').getBoundingClientRect();
  const vx = e.clientX - vp.left, vy = e.clientY - vp.top;
  return {
    x: Math.min(Math.max(((vx - panX) / zoom) / 640, 0), 1),
    y: Math.min(Math.max(((vy - panY) / zoom) / 640, 0), 1)
  };
}
function clampBox(b) {
  let w = Math.min(Math.max(b.w, 0.005), 1);
  let h = Math.min(Math.max(b.h, 0.005), 1);
  let x = Math.max(0, Math.min(1 - w, b.x));
  let y = Math.max(0, Math.min(1 - h, b.y));
  // V8.3.0: сохраняем behavior и animal_id.
  return {
    x, y, w, h,
    label: b.label || currentObjectClass(),
    confidence: (b.confidence ?? null),
    frozen: !!b.frozen,
    behavior: b.behavior || null,
    animal_id: (b.animal_id != null) ? b.animal_id : null,
  };
}
function applyTransform() {
  const stage = document.getElementById('canvasStage');
  stage.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  stage.style.setProperty('--inv-zoom', (1 / zoom).toFixed(4));
  const badge = document.getElementById('zoomBadge');
  badge.textContent = Math.round(zoom * 100) + '%';
  badge.setAttribute('aria-label', `Масштаб ${Math.round(zoom * 100)}%`);
  _updateCanvasCursor();
}
function _updateCanvasCursor() {
  const vp = document.getElementById('canvasViewport');
  if (!vp) return;
  if (zoom > 1) vp.classList.add('can-pan');
  else vp.classList.remove('can-pan');
}
function clampPan() {
  const vpSize = 640, stageSize = 640 * zoom;
  if (stageSize <= vpSize) {
    panX = (vpSize - stageSize) / 2;
    panY = (vpSize - stageSize) / 2;
  } else {
    panX = Math.min(0, Math.max(vpSize - stageSize, panX));
    panY = Math.min(0, Math.max(vpSize - stageSize, panY));
  }
}
function zoomAt(vx, vy, factor) {
  const nz = Math.min(Math.max(zoom * factor, ZOOM_MIN), ZOOM_MAX);
  if (nz === zoom) return;
  const k = nz / zoom;
  panX = vx - (vx - panX) * k;
  panY = vy - (vy - panY) * k;
  zoom = nz; clampPan(); applyTransform();
}
function zoomToCenter(f) { zoomAt(320, 320, f); }
function zoomReset() { zoom = 1; panX = 0; panY = 0; clampPan(); applyTransform(); }
function zoomFit() { zoomReset(); }
function zoomToSelection() {
  const indices = getSelectedIndices();
  if (!indices.length) { zoomReset(); setStatus(t('toast.nothingToZoom')); return; }
  let x1 = 1, y1 = 1, x2 = 0, y2 = 0;
  indices.forEach(i => {
    const b = boxes[i];
    if (!b) return;
    x1 = Math.min(x1, b.x);
    y1 = Math.min(y1, b.y);
    x2 = Math.max(x2, b.x + b.w);
    y2 = Math.max(y2, b.y + b.h);
  });
  const bboxW = x2 - x1;
  const bboxH = y2 - y1;
  if (bboxW <= 0 || bboxH <= 0) return;
  const PAD = 0.15;
  const targetW = bboxW * (1 + 2 * PAD);
  const targetH = bboxH * (1 + 2 * PAD);
  const newZoom = Math.max(Math.min(Math.min(1 / targetW, 1 / targetH), ZOOM_MAX), ZOOM_MIN);
  const cx = ((x1 + x2) / 2) * 640;
  const cy = ((y1 + y2) / 2) * 640;
  zoom = newZoom;
  panX = 320 - cx * zoom;
  panY = 320 - cy * zoom;
  clampPan();
  applyTransform();
  haptic('selection');
}

/* ===== Save / undo ===== */
function showCanvas(show) {
  document.getElementById('emptyState').style.display = show ? 'none' : 'flex';
  document.getElementById('canvasCard').style.display = show ? 'inline-block' : 'none';
}
function markDirty() { isDirty = true; updateSaveIndicator(); _invalidateValidateCache(); }
function markClean() { isDirty = false; updateSaveIndicator(); }
function updateSaveIndicator() {
  const el = document.getElementById('saveIndicator');
  if (!el) return;
  el.classList.remove('clean', 'dirty');
  el.classList.add(isDirty ? 'dirty' : 'clean');
  el.setAttribute('aria-label', isDirty ? 'Есть несохранённые изменения' : 'Все изменения сохранены');
  el.setAttribute('title', isDirty ? 'Есть несохранённые изменения' : 'Все изменения сохранены');
}
function pulseSaveIndicator() {
  const el = document.getElementById('saveIndicator');
  if (!el) return;
  el.classList.remove('dirty', 'clean');
  el.classList.add('clean');
  el.classList.remove('saved');
  void el.offsetWidth;
  el.classList.add('saved');
  setTimeout(() => el.classList.remove('saved'), 420);
}
function markSavedWithPulse() { markClean(); pulseSaveIndicator(); haptic('success'); }
// V8.2.2: применяет результат авторазметки, НЕ стирая историю.
// prevBoxes — состояние ДО авторазметки (snapshot() до boxes = ...).
// Если состояние не изменилось — история не трогается.
function _restoreHistoryAfterAutolabel(prevBoxes) {
  const after = JSON.parse(JSON.stringify(boxes));
  if (JSON.stringify(prevBoxes) === JSON.stringify(after)) {
    // Авторазметка не дала изменений — Ctrl+Z должен откатывать
    // предыдущее действие, а не авторазметку.
    return;
  }
  // Обрезаем redo-ветку
  if (historyIndex < history.length - 1) {
    history = history.slice(0, historyIndex + 1);
  }
  // Инвариант: history[historyIndex] = prevBoxes. Если он нарушен
  // (например, из-за resetHistory() где-то выше) — сохраним явно.
  const cur = history[historyIndex];
  if (!cur || JSON.stringify(cur) !== JSON.stringify(prevBoxes)) {
    history.push(JSON.parse(JSON.stringify(prevBoxes)));
  }
  history.push(after);
  while (history.length > HISTORY_LIMIT) history.shift();
  historyIndex = history.length - 1;
}

function snapshot() { return JSON.parse(JSON.stringify(boxes)); }
function resetHistory() { history = [snapshot()]; historyIndex = 0; }
function pushHistory() {
  const snap = snapshot();
  if (historyIndex >= 0 && JSON.stringify(history[historyIndex]) === JSON.stringify(snap)) return;
  if (historyIndex < history.length - 1) history = history.slice(0, historyIndex + 1);
  history.push(snap);
  if (history.length > HISTORY_LIMIT) history.shift();
  historyIndex = history.length - 1;
}
function undo() {
  if (historyIndex <= 0) return;
  historyIndex--;
  boxes = JSON.parse(JSON.stringify(history[historyIndex]));
  // V8.5.5: НЕ сбрасываем selectedIndex — иначе keypoints скелета
  // теряют привязку к рамке. Чистим только выходящие за пределы.
  if (selectedIndex >= boxes.length) selectedIndex = -1;
  if (multiSelected.size) {
    const _keep = new Set();
    multiSelected.forEach(_i => { if (_i < boxes.length) _keep.add(_i); });
    multiSelected = _keep;
  }
  _reloadKeypointsFromBox();
  renderBoxes();
  updateSelectionClasses();
  markDirty();
  setStatus(t('toast.undone')); haptic('selection');
}
function redo() {
  if (historyIndex >= history.length - 1) return;
  historyIndex++;
  boxes = JSON.parse(JSON.stringify(history[historyIndex]));
  // V8.5.5: как в undo — не теряем выделение.
  if (selectedIndex >= boxes.length) selectedIndex = -1;
  if (multiSelected.size) {
    const _keep = new Set();
    multiSelected.forEach(_i => { if (_i < boxes.length) _keep.add(_i); });
    multiSelected = _keep;
  }
  _reloadKeypointsFromBox();
  renderBoxes();
  updateSelectionClasses();
  markDirty();
  setStatus(t('toast.redone')); haptic('selection');
}
window.addEventListener('beforeunload', (e) => {
  if (isDirty) { e.preventDefault(); e.returnValue = ''; return ''; }
});

/* ===== Command Palette ===== */
let _paletteActiveIdx = 0;
let _paletteItems = [];

// V8.1.0: история последних команд (5) + поиск по классам/тегам.
const PALETTE_HISTORY_LIMIT = 5;
let _paletteHistory = [];
try {
  const saved = JSON.parse(localStorage.getItem('pdb_palette_history') || '[]');
  if (Array.isArray(saved)) _paletteHistory = saved.slice(0, PALETTE_HISTORY_LIMIT);
} catch (e) {}
function _pushPaletteHistory(id) {
  _paletteHistory = [id, ..._paletteHistory.filter(x => x !== id)].slice(0, PALETTE_HISTORY_LIMIT);
  try { localStorage.setItem('pdb_palette_history', JSON.stringify(_paletteHistory)); } catch (e) {}
}

function _getCommands() {
  const cmds = [];
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || '');
  const CMD = isMac ? '⌘' : 'Ctrl+';
  const modBackslash = isMac ? '⌘\\' : 'Ctrl+\\';

  cmds.push({ id: 'focus-mode', category: t('cmd.cat.view'),
    title: getFocusMode() ? t('cmd.focus.exit') : t('cmd.focus.enter'),
    keywords: 'focus fullscreen sidebar hide ui', shortcut: modBackslash, action: toggleFocusMode });
  cmds.push({ id: 'theme-auto', category: t('cmd.cat.view'), title: t('cmd.theme.auto'),
    keywords: 'theme auto system', action: () => setThemeMode('auto') });
  cmds.push({ id: 'theme-light', category: t('cmd.cat.view'), title: t('cmd.theme.light'),
    keywords: 'theme light', action: () => setThemeMode('light') });
  cmds.push({ id: 'theme-dark', category: t('cmd.cat.view'), title: t('cmd.theme.dark'),
    keywords: 'theme dark night', action: () => setThemeMode('dark') });
  cmds.push({ id: 'hints', category: t('cmd.cat.view'),
    title: getHideHints() ? t('cmd.hints.show') : t('cmd.hints.hide'),
    keywords: 'hints tips toggle', action: () => setHideHints(!getHideHints()) });

  cmds.push({ id: 'proj-new', category: t('cmd.cat.projects'), title: t('cmd.proj.new'),
    keywords: 'new project create add', action: () => openProjectCreate() });
  _cachedProjectsList.forEach(p => {
    if (p.id === currentProjectId) return;
    cmds.push({
      id: 'proj-switch-' + p.id,
      category: t('cmd.cat.projects'),
      title: t('cmd.proj.open', { name: p.name }),
      keywords: 'switch open project ' + p.name + ' ' + (p.object_class || ''),
      action: () => {
        const el = document.querySelector(`#projects > div[data-project-id="${p.id}"]`);
        if (el) el.click();
      },
    });
  });
  if (currentProjectId) {
    cmds.push({ id: 'proj-settings', category: t('cmd.cat.projects'), title: t('cmd.proj.settings'),
      keywords: 'project settings class object', action: () => {
      const el = document.querySelector(`#projects > div[data-project-id="${currentProjectId}"]`);
      if (el) { const b = el.querySelector('.proj-settings'); if (b) b.click(); }
    }});
    cmds.push({ id: 'proj-backup', category: t('cmd.cat.projects'), title: t('cmd.proj.backup'),
      keywords: 'backup zip export save', action: () => doBackup() });
    cmds.push({ id: 'proj-delete', category: t('cmd.cat.projects'), title: t('cmd.proj.delete'),
      keywords: 'delete project remove trash', action: () => {
      if (!currentProjectMeta) return;
      confirmDeleteProject(currentProjectMeta.id, currentProjectMeta.name, currentProjectMeta.images_count || 0);
    }});
  }

  cmds.push({ id: 'filter-none', category: t('cmd.cat.filters'), title: t('cmd.filter.reset'),
    keywords: 'filter reset clear', action: () => {
    activeFilter = 'none'; activeTagIds.clear();
    try { localStorage.setItem('pdb_filter', 'none'); } catch (e) {}
    document.getElementById('filterUnannotated').checked = false;
    document.getElementById('filterLowConf').checked = false;
    document.getElementById('filterHard').checked = false;
    updateFilterBadge(); loadImages();
  }});
  cmds.push({ id: 'filter-un', category: t('cmd.cat.filters'), title: t('cmd.filter.un'),
    keywords: 'filter unannotated empty', action: () => {
    activeFilter = 'unannotated';
    document.getElementById('filterUnannotated').checked = true;
    document.getElementById('filterLowConf').checked = false;
    document.getElementById('filterHard').checked = false;
    try { localStorage.setItem('pdb_filter', 'unannotated'); } catch (e) {}
    updateFilterBadge(); loadImages();
  }});
  cmds.push({ id: 'filter-hard', category: t('cmd.cat.filters'), title: t('cmd.filter.hard'),
    keywords: 'filter hard flag', action: () => {
    activeFilter = 'hard';
    document.getElementById('filterUnannotated').checked = false;
    document.getElementById('filterLowConf').checked = false;
    document.getElementById('filterHard').checked = true;
    try { localStorage.setItem('pdb_filter', 'hard'); } catch (e) {}
    updateFilterBadge(); loadImages();
  }});
  cmds.push({ id: 'filter-low', category: t('cmd.cat.filters'), title: t('cmd.filter.low'),
    keywords: 'filter low conf', action: () => {
    activeFilter = 'lowconf';
    document.getElementById('filterUnannotated').checked = false;
    document.getElementById('filterLowConf').checked = true;
    document.getElementById('filterHard').checked = false;
    try { localStorage.setItem('pdb_filter', 'lowconf'); } catch (e) {}
    updateFilterBadge(); loadImages();
  }});

  const sortLabels = {
    name_asc: t('cmd.sort.nameAsc'), name_desc: t('cmd.sort.nameDesc'),
    type_asc: t('cmd.sort.typeAsc'), type_desc: t('cmd.sort.typeDesc'),
    conf_asc: t('cmd.sort.confAsc'), conf_desc: t('cmd.sort.confDesc'),
    date_desc: t('cmd.sort.dateDesc'), date_asc: t('cmd.sort.dateAsc'),
    size_desc: t('cmd.sort.sizeDesc'), size_asc: t('cmd.sort.sizeAsc'),
  };
  Object.entries(sortLabels).forEach(([k, l]) => {
    cmds.push({ id: 'sort-' + k, category: t('cmd.cat.sort'), title: l, keywords: 'sort order ' + k, action: () => setSortMode(k) });
  });

  if (currentImageId) {
    cmds.push({ id: 'act-autolabel', category: t('cmd.cat.actions'), title: t('cmd.act.autolabel'), keywords: 'autolabel detect auto', shortcut: 'A', action: () => autolabel() });
    cmds.push({ id: 'act-save', category: t('cmd.cat.actions'), title: t('cmd.act.save'), keywords: 'save store', shortcut: CMD + 'S', action: () => saveAnnotations() });
    cmds.push({ id: 'act-clear', category: t('cmd.cat.actions'), title: t('cmd.act.clear'), keywords: 'clear reset boxes', shortcut: 'C', action: () => clearBoxes() });
    cmds.push({ id: 'act-hard', category: t('cmd.cat.actions'), title: t('cmd.act.hard'), keywords: 'hard flag difficult', shortcut: 'F', action: () => toggleHardCurrent() });
    cmds.push({ id: 'act-zoomsel', category: t('cmd.cat.actions'), title: t('cmd.act.zoomsel'), keywords: 'zoom selection fit', shortcut: 'Z', action: () => zoomToSelection() });
    cmds.push({ id: 'act-sam', category: t('cmd.cat.actions'), title: samMode ? t('cmd.act.samOff') : t('cmd.act.samOn'), keywords: 'sam segment mask click', shortcut: 'M', action: () => toggleSamMode() });
    cmds.push({ id: 'act-metrics', category: t('cmd.cat.actions'), title: t('cmd.act.metrics'), keywords: 'metrics map chart confusion', action: () => openMetricsModal() });
  cmds.push({ id: 'act-compare', category: t('cmd.cat.actions'), title: 'Сравнить модели (side-by-side)', keywords: 'compare models runs mAP diff', action: () => openModelCompare() });
  }
  cmds.push({ id: 'act-batch', category: t('cmd.cat.actions'), title: t('cmd.act.batch'), keywords: 'batch all autolabel', action: () => autolabelAllUnlabeled() });
  cmds.push({ id: 'act-stats', category: t('cmd.cat.actions'), title: t('cmd.act.stats'), keywords: 'stats statistics charts', action: () => openStats() });
  cmds.push({ id: 'act-validate', category: t('cmd.cat.actions'), title: t('cmd.act.validate'), keywords: 'validate check issues', action: () => openValidateModal() });
  cmds.push({ id: 'act-train', category: t('cmd.cat.actions'), title: t('cmd.act.train'), keywords: 'train model yolo', action: () => { closeSettings(); setTimeout(() => openTrainModal(), 100); }});
  cmds.push({ id: 'extract-frames', category: t('cmd.cat.actions'), title: t('cmd.act.extract'), keywords: 'video extract frames mp4', action: () => triggerVideoExtract() });
  cmds.push({
    id: 'toggle-debug',
    category: t('cmd.cat.actions'),
    title: getDebugMode() ? t('cmd.act.debugOff') : t('cmd.act.debugOn'),
    keywords: 'debug yolo show all classes',
    action: () => setDebugMode(!getDebugMode()),
  });

  cmds.push({ id: 'file-rename', category: t('cmd.cat.files'), title: t('cmd.file.rename'), keywords: 'rename bulk mask pattern', action: () => openBulkRename() });
  cmds.push({ id: 'file-move', category: t('cmd.cat.files'), title: t('cmd.file.move'), keywords: 'move transfer project', action: () => openMoveCopyDialog('move') });
  cmds.push({ id: 'file-copy', category: t('cmd.cat.files'), title: t('cmd.file.copy'), keywords: 'copy duplicate project', action: () => openMoveCopyDialog('copy') });
  cmds.push({ id: 'file-dups', category: t('cmd.cat.files'), title: t('cmd.file.dups'), keywords: 'duplicates phash similar find', action: () => openDuplicatesModal() });
  cmds.push({ id: 'file-csv', category: t('cmd.cat.files'), title: t('cmd.file.csv'), keywords: 'csv export files list', action: () => downloadFilesCsv() });

  cmds.push({ id: 'import-url', category: t('cmd.cat.import'), title: t('cmd.imp.url'), keywords: 'import url link zip http s3 gcs', action: () => importFromUrl() });
  cmds.push({ id: 'import-roboflow', category: t('cmd.cat.import'), title: t('cmd.imp.roboflow'), keywords: 'import roboflow api', action: () => importFromRoboflow() });
  cmds.push({ id: 'import-supervisely', category: t('cmd.cat.import'), title: t('cmd.imp.supervisely'), keywords: 'import supervisely api', action: () => importFromSupervisely() });
  cmds.push({ id: 'import-folder', category: t('cmd.cat.import'), title: t('cmd.imp.folder'), keywords: 'import folder local path', action: () => importFromLocalFolder() });
  cmds.push({ id: 'import-labelbox', category: t('cmd.cat.import'), title: t('cmd.imp.labelbox'), keywords: 'import labelbox api', action: () => importFromLabelbox() });
  cmds.push({ id: 'import-scale', category: t('cmd.cat.import'), title: t('cmd.imp.scale'), keywords: 'import scale ai nucleus', action: () => importFromScale() });
  cmds.push({ id: 'import-darwin', category: t('cmd.cat.import'), title: t('cmd.imp.darwin'), keywords: 'import darwin v7', action: () => importFromDarwin() });

  cmds.push({ id: 'exp-yolo', category: t('cmd.cat.export'), title: t('cmd.exp.yolo'), keywords: 'export yolo download zip', action: () => { exportFormat = 'yolo'; openExportModal(); }});
  cmds.push({ id: 'exp-coco', category: t('cmd.cat.export'), title: t('cmd.exp.coco'), keywords: 'export coco download zip', action: () => { exportFormat = 'coco'; openExportModal(); }});
  cmds.push({ id: 'exp-csv', category: t('cmd.cat.export'), title: t('cmd.exp.csv'), keywords: 'csv stats export', action: () => downloadStatsCsv() });

  cmds.push({ id: 'nav-trash', category: t('cmd.cat.nav'),
    title: viewMode === 'trash' ? t('cmd.nav.trashExit') : t('cmd.nav.trashEnter'),
    keywords: 'trash bin deleted', action: () => toggleTrash() });
  cmds.push({ id: 'nav-settings', category: t('cmd.cat.nav'), title: t('cmd.nav.settings'), keywords: 'settings preferences options', action: () => openSettings() });
  cmds.push({ id: 'storage-backup', category: t('cmd.cat.nav'), title: t('cmd.nav.backup'), keywords: 'backup database storage db download', action: () => { openSettings(); setTimeout(() => _refreshStorageInfo(), 200); }});
  cmds.push({ id: 'storage-migrate', category: t('cmd.cat.nav'), title: t('cmd.nav.migrate'), keywords: 'migrate sqlite mysql move switch local-first', action: () => {
    openSettings();
    setTimeout(async () => {
      _refreshStorageInfo();
      setTimeout(() => {
        const btns = document.querySelectorAll('#storageMigrateBlock .btn-primary');
        if (btns.length) btns[0].click();
      }, 400);
    }, 200);
  }});
  cmds.push({ id: 'nav-shortcuts', category: t('cmd.cat.nav'), title: t('cmd.nav.shortcuts'), keywords: 'shortcuts keys hotkeys', shortcut: '?', action: () => openShortcuts() });
  cmds.push({ id: 'nav-logs', category: t('cmd.cat.nav'), title: t('cmd.nav.logs'), keywords: 'logs history events', action: () => openLogs() });
  cmds.push({ id: 'nav-versions', category: t('cmd.cat.nav'), title: t('cmd.nav.versions'), keywords: 'versions changelog release', action: () => openVersions() });

  // V8.1.0: классы и теги текущего проекта — быстрый переход.
  if (currentProjectId) {
    (projectTags || []).forEach(tag => {
      cmds.push({
        id: 'tag-filter-' + tag.id,
        category: 'Теги',
        title: `Фильтр: ${tag.name} (${tag.count})`,
        keywords: 'tag тег фильтр ' + tag.name,
        action: () => {
          if (activeTagIds.has(tag.id)) activeTagIds.delete(tag.id);
          else activeTagIds.add(tag.id);
          updateFilterBadge(); loadImages();
        },
      });
    });
    const cls = (currentProjectMeta && currentProjectMeta.object_class) || 'pig';
    cmds.push({
      id: 'class-show',
      category: 'Классы',
      title: `Текущий класс: ${cls}`,
      keywords: 'class класс object object_class ' + cls,
      action: () => { openProjectEdit(currentProjectId); },
    });
    (objectClassesCache.classes || []).slice(0, 30).forEach((name) => {
      if (name === cls) return;
      cmds.push({
        id: 'class-set-' + name,
        category: 'Классы',
        title: `Класс проекта: ${name}`,
        keywords: 'class класс ' + name,
        action: async () => {
          if (!currentProjectId) return;
          try {
            await api(`/api/projects/${currentProjectId}/settings`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ object_class: name, object_class_source: 'list' }),
            });
            await loadProjects();
            setStatus(`Класс проекта: ${name}`);
          } catch (e) { setError(String(e.message).slice(0, 160)); }
        },
      });
    });
  }
  // История — наверх списка
  if (_paletteHistory.length) {
    const byId = new Map(cmds.map(c => [c.id, c]));
    _paletteHistory.forEach(hid => {
      const c = byId.get(hid);
      if (!c) return;
      cmds.unshift({ ...c, category: 'Недавние' });
    });
  }
  return cmds;
}
function openCommandPalette() {  return cmds;
}
function openCommandPalette() {
  if (isModalOpen('commandPaletteModal')) return;
  const input = document.getElementById('commandInput');
  if (input) input.value = '';
  _paletteActiveIdx = 0;
  renderCommandPalette('');
  openModal('commandPaletteModal');
  setTimeout(() => { try { input.focus(); } catch (e) {} }, 60);
}
function closeCommandPalette() { closeModal('commandPaletteModal'); }
function _filterCommands(cmds, query) {
  if (!query) return cmds;
  const q = query.toLowerCase().trim();
  const scored = [];
  for (const c of cmds) {
    const title = (c.title || '').toLowerCase();
    const kw = (c.keywords || '').toLowerCase();
    const cat = (c.category || '').toLowerCase();
    let score = 0;
    if (title.startsWith(q)) score = 100;
    else if (title.includes(q)) score = 60;
    else if (kw.includes(q)) score = 40;
    else if (cat.includes(q)) score = 20;
    if (score > 0) scored.push({ c, score });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, 100).map(x => x.c);
}
function renderCommandPalette(query) {
  const all = _getCommands();
  const filtered = _filterCommands(all, query);
  _paletteItems = filtered;
  if (_paletteActiveIdx >= filtered.length) _paletteActiveIdx = Math.max(0, filtered.length - 1);
  const list = document.getElementById('commandList');
  list.innerHTML = '';
  if (!filtered.length) {
    const e = document.createElement('div');
    e.className = 'command-empty';
    e.textContent = 'Ничего не найдено';
    list.appendChild(e);
    return;
  }
  const groups = new Map();
  filtered.forEach((c, idx) => {
    const cat = c.category || 'Прочее';
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat).push({ c, idx });
  });
  groups.forEach((items, cat) => {
    const groupEl = document.createElement('div');
    groupEl.className = 'command-group';
    const t = document.createElement('div');
    t.className = 'command-group-title'; t.textContent = cat;
    groupEl.appendChild(t);
    items.forEach(({ c, idx }) => {
      const row = document.createElement('div');
      row.className = 'command-item' + (idx === _paletteActiveIdx ? ' active' : '');
      row.dataset.idx = String(idx);
      row.setAttribute('role', 'option');
      const title = document.createElement('span');
      title.className = 'command-item-title'; title.textContent = c.title;
      row.appendChild(title);
      if (c.shortcut) {
        const s = document.createElement('kbd');
        s.className = 'command-item-shortcut'; s.textContent = c.shortcut;
        row.appendChild(s);
      }
      row.addEventListener('click', (e) => { e.stopPropagation(); _runCommand(idx); });
      row.addEventListener('mousemove', () => {
        if (_paletteActiveIdx !== idx) { _paletteActiveIdx = idx; _highlightPaletteItem(); }
      });
      groupEl.appendChild(row);
    });
    list.appendChild(groupEl);
  });
  _highlightPaletteItem();
}
function _highlightPaletteItem() {
  const list = document.getElementById('commandList');
  list.querySelectorAll('.command-item').forEach(el => {
    const idx = parseInt(el.dataset.idx, 10);
    el.classList.toggle('active', idx === _paletteActiveIdx);
  });
  const active = list.querySelector('.command-item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}
function _runCommand(idx) {
  const cmd = _paletteItems[idx];
  if (!cmd) return;
  _pushPaletteHistory(cmd.id);
  closeCommandPalette();
  setTimeout(() => {
    try { cmd.action(); } catch (e) { console.error(e); setError('Ошибка: ' + String(e.message || e)); }
  }, 60);
}
function _installCommandPaletteListeners() {
  const input = document.getElementById('commandInput');
  if (!input || input.__paletteBound) return;
  input.__paletteBound = true;
  input.addEventListener('input', () => {
    _paletteActiveIdx = 0;
    renderCommandPalette(input.value);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _paletteActiveIdx = Math.min(_paletteActiveIdx + 1, Math.max(0, _paletteItems.length - 1));
      _highlightPaletteItem();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _paletteActiveIdx = Math.max(_paletteActiveIdx - 1, 0);
      _highlightPaletteItem();
    } else if (e.key === 'Enter') {
      e.preventDefault(); e.stopPropagation();
      _runCommand(_paletteActiveIdx);
    } else if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      closeCommandPalette();
    } else if (e.key === 'Home') {
      e.preventDefault(); _paletteActiveIdx = 0; _highlightPaletteItem();
    } else if (e.key === 'End') {
      e.preventDefault(); _paletteActiveIdx = Math.max(0, _paletteItems.length - 1); _highlightPaletteItem();
    }
  });
  const backdrop = document.getElementById('commandPaletteModal');
  if (backdrop) {
    backdrop.addEventListener('mousedown', (e) => {
      if (e.target.id === 'commandPaletteModal') closeCommandPalette();
    });
  }
}

/* ===== Pointer / Touch / Mouse ===== */
const viewport = document.getElementById('canvasViewport');
let preDragSnapshot = null;
const _activePointers = new Map();
let _pinchStart = null;
let _drawDotEl = null;
let _drawDotTimer = null;

function flashDrawDot(x, y) {
  if (prefersReducedMotion()) return;
  const boxesEl = document.getElementById('boxes');
  if (!boxesEl) return;
  if (!_drawDotEl || !_drawDotEl.parentNode) {
    _drawDotEl = document.createElement('div');
    _drawDotEl.className = 'draw-dot';
    _drawDotEl.setAttribute('aria-hidden', 'true');
    boxesEl.appendChild(_drawDotEl);
  }
  _drawDotEl.style.left = (x * 640) + 'px';
  _drawDotEl.style.top = (y * 640) + 'px';
  _drawDotEl.style.animation = 'none';
  void _drawDotEl.offsetWidth;
  _drawDotEl.style.animation = '';
  clearTimeout(_drawDotTimer);
  _drawDotTimer = setTimeout(() => {
    if (_drawDotEl && _drawDotEl.parentNode) _drawDotEl.parentNode.removeChild(_drawDotEl);
    _drawDotEl = null;
  }, 180);
}
function _distTwoPointers() {
  const pts = Array.from(_activePointers.values());
  if (pts.length < 2) return 0;
  return Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);
}
function _midTwoPointers() {
  const pts = Array.from(_activePointers.values());
  if (pts.length < 2) return { x: 0, y: 0 };
  return { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
}
function _handlePinch() {
  if (!_pinchStart || _activePointers.size < 2) return;
  const vp = viewport.getBoundingClientRect();
  const dist = _distTwoPointers();
  const mid = _midTwoPointers();
  const mx = mid.x - vp.left, my = mid.y - vp.top;
  const mxs = _pinchStart.midClientX - vp.left;
  const mys = _pinchStart.midClientY - vp.top;
  const factor = _pinchStart.distance > 0 ? dist / _pinchStart.distance : 1;
  const targetZoom = Math.min(Math.max(_pinchStart.zoom * factor, ZOOM_MIN), ZOOM_MAX);
  const k = targetZoom / _pinchStart.zoom;
  panX = mx - (mxs - _pinchStart.panX) * k;
  panY = my - (mys - _pinchStart.panY) * k;
  zoom = targetZoom;
  clampPan(); applyTransform();
}
viewport.addEventListener('pointerdown', e => {
  if (!currentImageId) return;
  if (e.target.closest && e.target.closest('.zoom-controls')) return;
  if (e.target.closest && e.target.closest('.zoom-badge')) return;
  if (e.pointerType === 'mouse' && e.button !== 0 && e.button !== 1) return;
  e.preventDefault();
  _activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (_activePointers.size === 2) {
    if (dragState) { dragState = null; const dp = document.getElementById('drawPreview'); if (dp) dp.remove(); }
    if (isPanning) { isPanning = false; viewport.classList.remove('panning'); }
    const mid = _midTwoPointers();
    _pinchStart = { distance: _distTwoPointers(), midClientX: mid.x, midClientY: mid.y, zoom: zoom, panX: panX, panY: panY };
    return;
  }
  if (_activePointers.size > 2) return;

  const t = e.target;
  const isDelete = t.classList && t.classList.contains('box-delete');
  if (isDelete) return;

  if (samMode) {
    const p = getRel(e);
    _samClickAt(p.x, p.y);
    return;
  }

  // V8.5.1: skeleton-режим.
  if (skeletonMode) {
    // V8.6.11: pan работает и в скелете — Space / СКМ / zoom>1 на пустом.
    const _skelEmpty = !t.closest || !t.closest('.box');
    const _wantPan = spacePressed || e.button === 1
                     || (zoom > 1 && _skelEmpty && !e.shiftKey
                         && !(t.classList && t.classList.contains('skeleton-point')));
    if (_wantPan) {
      isPanning = true;
      panStart = { x: e.clientX - panX, y: e.clientY - panY };
      viewport.classList.add('panning');
      try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
      return;
    }
    const _isKp = t.classList && t.classList.contains('skeleton-point');
    if (_isKp) {
      // Drag точки
      keypointDragIdx = parseInt(t.dataset.kpIdx, 10);
      try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
      return;
    }
    // V8.5.2: если ничего не выделено — клик по рамке её выделяет.
    const _boxEl = t.closest ? t.closest('.box') : null;
    const _hasSel = _targetAnnotationId() >= 0;
    if (_boxEl && !_hasSel) {
      const _bi = +_boxEl.dataset.idx;
      selectedIndex = _bi;
      multiSelected.clear();
      updateSelectionClasses();
      return;
    }
    if (e.button === 2) {
      _removeLastKeypoint();
      e.preventDefault();
      return;
    }
    if (e.button === 0) {
      if (!_hasSel) {
        setStatus(t('skeleton.status.selectFirst'), 2000);
        haptic('warning');
        return;
      }
      const p = getRel(e);
      // V8.5.2: Shift+клик — точка со скрытой видимостью (visibility=0).
      _placeNextKeypoint(p.x, p.y, e.shiftKey ? 0.0 : 1.0);
      return;
    }
    return;
  }

  const isHandle = t.classList && t.classList.contains('handle') && !!t.dataset.handle;
  const isEdge = t.classList && t.classList.contains('box-edge');
  const boxEl = t.closest ? t.closest('.box') : null;
  const isEmpty = !boxEl;
  const shouldPan = spacePressed || e.button === 1 || (zoom > 1 && isEmpty && !e.shiftKey);
  if (shouldPan) {
    isPanning = true;
    panStart = { x: e.clientX - panX, y: e.clientY - panY };
    viewport.classList.add('panning');
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    return;
  }
  preDragSnapshot = snapshot();
  if (isHandle && boxEl) {
    const idx = +boxEl.dataset.idx;
    if (boxes[idx].frozen) return;
    if (e.shiftKey) toggleMultiSelect(idx);
    else { selectedIndex = idx; multiSelected.clear(); }
    const p = getRel(e);
    const o = boxes[idx];
    dragState = { mode: 'resize', handle: t.dataset.handle, idx, startX: p.x, startY: p.y,
                  orig: { x: o.x, y: o.y, w: o.w, h: o.h } };
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    updateSelectionClasses();
    return;
  }
  if (isEdge && boxEl) {
    const idx = +boxEl.dataset.idx;
    if (e.shiftKey) toggleMultiSelect(idx);
    else { selectedIndex = idx; multiSelected.clear(); }
    if (boxes[idx].frozen) { updateSelectionClasses(); return; }
    const p = getRel(e);
    const o = boxes[idx];
    dragState = { mode: 'move', idx, startX: p.x, startY: p.y,
                  orig: { x: o.x, y: o.y, w: o.w, h: o.h },
                  moveAll: multiSelected.size > 0 };
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    updateSelectionClasses();
    return;
  }
  selectedIndex = -1;
  multiSelected.clear();
  updateSelectionClasses();
  const p = getRel(e);
  dragState = { mode: 'draw', startX: p.x, startY: p.y };
  const prev = document.createElement('div');
  prev.id = 'drawPreview';
  prev.className = 'box preview';
  prev.setAttribute('aria-hidden', 'true');
  document.getElementById('boxes').appendChild(prev);
  dragState.previewEl = prev;
  flashDrawDot(p.x, p.y);
  try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
});
function toggleMultiSelect(idx) {
  if (multiSelected.has(idx)) {
    multiSelected.delete(idx);
    if (selectedIndex === idx) selectedIndex = -1;
  } else {
    if (selectedIndex >= 0) { multiSelected.add(selectedIndex); selectedIndex = -1; }
    multiSelected.add(idx);
  }
}
document.addEventListener('pointerdown', e => {
  if (!currentImageId) return;
  if (selectedIndex < 0 && multiSelected.size === 0) return;
  const path = (e.composedPath && e.composedPath()) || [];
  if (path.includes(viewport)) return;
  const tb = document.querySelector('.toolbar');
  if (tb && path.includes(tb)) return;
  // V8.3.2: панель атрибутов и чипсы тегов НЕ сбрасывают выделение.
  const attrBar = document.getElementById('attrBar');
  if (attrBar && path.includes(attrBar)) return;
  const tagChipsBar = document.getElementById('tagChipsBar');
  if (tagChipsBar && path.includes(tagChipsBar)) return;
  if (path.some(el => el && el.classList && (el.classList.contains('modal-backdrop') || el.classList.contains('sidebar')))) return;
  selectedIndex = -1;
  multiSelected.clear();
  updateSelectionClasses();
});
window.addEventListener('pointermove', e => {
  if (_activePointers.has(e.pointerId)) _activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  // V8.5.1: drag keypoint
  if (keypointDragIdx >= 0 && keypointDragIdx < keypoints.length) {
    const p = getRel(e);
    keypoints[keypointDragIdx].x = p.x;
    keypoints[keypointDragIdx].y = p.y;
    _syncKeypointsToBox();
    renderSkeleton();
    return;
  }
  if (_pinchStart && _activePointers.size >= 2) { e.preventDefault(); _handlePinch(); return; }
  if (isPanning) {
    panX = e.clientX - panStart.x;
    panY = e.clientY - panStart.y;
    clampPan(); applyTransform();
    return;
  }
  if (!dragState) return;
  const p = getRel(e);
  if (dragState.mode === 'move') {
    const o = dragState.orig;
    const dx = p.x - dragState.startX, dy = p.y - dragState.startY;
    if (dragState.moveAll) {
      const indices = getSelectedIndices().filter(i => !boxes[i].frozen);
      const snap = preDragSnapshot;
      indices.forEach(i => {
        const so = snap[i];
        // V8.4.1: сохраняем behavior и animal_id.
        boxes[i] = clampBox({
          x: so.x + dx, y: so.y + dy, w: so.w, h: so.h,
          label: so.label, confidence: so.confidence, frozen: so.frozen,
          behavior: so.behavior || null,
          animal_id: (so.animal_id != null) ? so.animal_id : null,
        });
        updateBoxInPlace(i);
      });
    } else {
      const b = boxes[dragState.idx];
      // V8.4.1: сохраняем behavior и animal_id.
      boxes[dragState.idx] = clampBox({
        x: o.x + dx, y: o.y + dy, w: o.w, h: o.h,
        label: b.label, confidence: b.confidence, frozen: b.frozen,
        behavior: b.behavior || null,
        animal_id: (b.animal_id != null) ? b.animal_id : null,
      });
      updateBoxInPlace(dragState.idx);
    }
    return;
  }
  if (dragState.mode === 'resize') {
    const o = dragState.orig;
    const dx = p.x - dragState.startX, dy = p.y - dragState.startY;
    let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
    const h = dragState.handle;
    if (h.includes('w')) x1 = o.x + dx;
    if (h.includes('e')) x2 = o.x + o.w + dx;
    if (h.includes('n')) y1 = o.y + dy;
    if (h.includes('s')) y2 = o.y + o.h + dy;
    if (x1 > x2) { const t = x1; x1 = x2; x2 = t; }
    if (y1 > y2) { const t = y1; y1 = y2; y2 = t; }
    x1 = Math.max(0, x1); y1 = Math.max(0, y1);
    x2 = Math.min(1, x2); y2 = Math.min(1, y2);
    const b = boxes[dragState.idx];
    // V8.4.1: сохраняем behavior и animal_id.
    boxes[dragState.idx] = {
      x: x1, y: y1,
      w: Math.max(0, x2 - x1), h: Math.max(0, y2 - y1),
      label: b.label, confidence: b.confidence, frozen: b.frozen,
      behavior: b.behavior || null,
      animal_id: (b.animal_id != null) ? b.animal_id : null,
    };
    updateBoxInPlace(dragState.idx);
    return;
  }
  if (dragState.mode === 'draw') {
    const prev = dragState.previewEl;
    if (!prev) return;
    const x = Math.min(dragState.startX, p.x);
    const y = Math.min(dragState.startY, p.y);
    const w = Math.abs(p.x - dragState.startX);
    const h = Math.abs(p.y - dragState.startY);
    prev.style.transform = `translate(${x * 640}px, ${y * 640}px)`;
    prev.style.width = (w * 640) + 'px';
    prev.style.height = (h * 640) + 'px';
  }
}, { passive: false });
function _endPointer(e) {
  // V8.5.1: завершение drag keypoint
  if (keypointDragIdx >= 0) {
    keypointDragIdx = -1;
    pushHistory();   // V8.5.3
    markDirty();
    haptic('selection');
  }
  _activePointers.delete(e.pointerId);
  if (_activePointers.size < 2) _pinchStart = null;
  if (isPanning) { isPanning = false; viewport.classList.remove('panning'); return; }
  if (!dragState) return;
  let changed = false;
  let settlingIdx = -1;
  if (dragState.mode === 'draw') {
    if (dragState.previewEl) { dragState.previewEl.remove(); dragState.previewEl = null; }
    const p = getRel(e);
    const x = Math.min(dragState.startX, p.x);
    const y = Math.min(dragState.startY, p.y);
    const w = Math.abs(p.x - dragState.startX);
    const h = Math.abs(p.y - dragState.startY);
    if (w > 0.01 && h > 0.01) {
      boxes.push({ x, y, w, h, label: currentObjectClass(), confidence: null, frozen: false });
      selectedIndex = boxes.length - 1;
      multiSelected.clear();
      changed = true;
      settlingIdx = boxes.length - 1;
      const layer = document.getElementById('boxes');
      const newBoxEl = _createBoxElement(boxes[settlingIdx], settlingIdx);
      if (!prefersReducedMotion()) {
        newBoxEl.classList.add('settling', 'box-enter');
        setTimeout(() => newBoxEl.classList.remove('settling', 'box-enter'), 400);
      }
      layer.appendChild(newBoxEl);
      updateSelectionClasses(); updateDelBoxBtn(); updateFreezeBtn();
    }
  } else if (dragState.mode === 'move' || dragState.mode === 'resize') {
    if (preDragSnapshot && JSON.stringify(preDragSnapshot) !== JSON.stringify(boxes)) {
      changed = true;
      if (dragState.mode === 'move' && dragState.moveAll) {
        getSelectedIndices().forEach(i => { if (boxes[i] && !boxes[i].frozen) { boxes[i].confidence = null; updateBoxInPlace(i); } });
      } else if (boxes[dragState.idx]) {
        boxes[dragState.idx].confidence = null;
        updateBoxInPlace(dragState.idx);
      }
    }
  }
  dragState = null;
  preDragSnapshot = null;
  if (changed) { pushHistory(); markDirty(); }
}
window.addEventListener('pointerup', _endPointer);
window.addEventListener('pointercancel', _endPointer);
viewport.addEventListener('wheel', (e) => {
  if (!currentImageId) return;
  // V8.4.2: Ctrl/Cmd + колесо → zoom к курсору.
  // Обычное колесо / трекпад → НЕ перехватываем — страница скроллится.
  // Pan — только ЛКМ+drag (см. pointerdown). Pinch на трекпаде — эмулируется
  // браузером как Ctrl+wheel и работает автоматически.
  if (!(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  const vp = viewport.getBoundingClientRect();
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  zoomAt(e.clientX - vp.left, e.clientY - vp.top, factor);
}, { passive: false });

// V8.5.1: правый клик в skeleton-режиме не должен вызывать браузерное меню.
// V8.5.3: правый клик удаляет последнюю точку.
viewport.addEventListener('contextmenu', (e) => {
  if (skeletonMode && currentImageId) {
    e.preventDefault();
    if (e.button === 2 || e.which === 3) {
      _removeLastKeypoint();
    }
  }
});

/* ===== Keyboard ===== */
document.addEventListener('keydown', e => {
  const isMod = e.ctrlKey || e.metaKey;

  // V7.8.1: SAM preview — наивысший приоритет
  if (samPreview && (e.code === 'Enter' || e.code === 'NumpadEnter')) {
    e.preventDefault();
    e.stopPropagation();
    _confirmSamPreview();
    return;
  }
  if (samPreview && e.code === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    _clearSamPreview();
    return;
  }

  // V7.9.3: Escape в диалоге подтверждения закрывает его даже из input.
  if (isModalOpen('dialogModal') && e.code === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    _skipFocusReturnOnce = true;
    _closeDialog(null);
    return;
  }

  if (isMod && e.code === 'KeyK') {
    e.preventDefault();
    if (isModalOpen('commandPaletteModal')) closeCommandPalette();
    else openCommandPalette();
    return;
  }
  if (isModalOpen('commandPaletteModal')) return;

  // V8.1.0: Shift+Ctrl+Z / Ctrl+Y для списка (не для холста).
  if (isMod && e.shiftKey && e.code === 'KeyZ' && MODAL_STACK.length === 0) {
    e.preventDefault(); redoListAction(); return;
  }
  // V8.8.1: Alt+← / Alt+→ — навигация по треку (animal_id текущего выделения).
  if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
    if (e.code === 'ArrowRight') { e.preventDefault(); _navigateWithAid('next'); return; }
    if (e.code === 'ArrowLeft')  { e.preventDefault(); _navigateWithAid('prev'); return; }
  }
  if (isMod && e.code === 'Backslash') {
    e.preventDefault();
    toggleFocusMode();
    return;
  }

  // V7.9.2: Ctrl+Z / Ctrl+Y обрабатываются раньше остальных проверок,
  // чтобы не блокироваться открытой модалкой или фокусом в не-related input.
  // Исключение: фокус в поле ввода — там Ctrl+Z = undo текста.
  {
    const _t = (e.target && e.target.tagName || '').toLowerCase();
    const _inInput = (_t === 'input' || _t === 'textarea' || _t === 'select');
    if (isMod && !_inInput) {
      if (e.code === 'KeyZ' && !e.shiftKey) {
        e.preventDefault();
        // V8.1.1: сначала undo рамок (если есть история),
        // иначе — undo удаления изображений.
        if (historyIndex > 0) undo();
        else if (_listUndoStack.length) undoListAction();
        else undo();
        return;
      }
      if (e.code === 'KeyY' || (e.shiftKey && e.code === 'KeyZ')) {
        e.preventDefault();
        if (_listRedoStack.length) redoListAction();
        else redo();
        return;
      }
    }
  }

  // V7.9.3: Ctrl+S в модалке настроек сохраняет параметры, даже если
  // фокус в поле ввода (там Ctrl+S не занят браузером).
  if (isMod && e.code === 'KeyS' && isModalOpen('settingsModal')) {
    e.preventDefault();
    saveSettings();
    return;
  }

  const tag = (e.target && e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') {
    if (e.key === 'Escape') {
      const popover = document.querySelector('.sort-menu.open, .custom-select.open, .color-picker-menu.open, .class-search.open');
      if (popover) { e.preventDefault(); closeAllPopovers(null); return; }
    }
    return;
  }
  if (isModalOpen('dialogModal')) {
    if (e.code === 'Escape') {
      e.preventDefault();
      _skipFocusReturnOnce = true;
      _closeDialog(null);
      return;
    }
    if (e.code === 'Enter' || e.code === 'NumpadEnter') {
      // V8.2.3: onBtn = кнопка ВНУТРИ модалки (а не где-то в UI).
      const _dlg = document.getElementById('dialogModal');
      const _act = document.activeElement;
      const _tag = (_act && _act.tagName || '').toLowerCase();
      const _onBtnInside = _dlg && _act && _dlg.contains(_act) && _tag === 'button';
      if (_onBtnInside) return;   // браузер сам кликнет (OK или Отмена)
      if (_tag !== 'input' && _tag !== 'textarea' && _tag !== 'select') {
        e.preventDefault();
        _closeDialog(true);
        return;
      }
    }
    return;
  }
  const isHKey = e.code === 'KeyH';
  const isQuestionByCode = e.code === 'Slash' && e.shiftKey;
  const isQuestionByKey = e.key === '?';
  if ((isHKey || isQuestionByCode || isQuestionByKey) && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (isModalOpen('shortcutsModal')) { e.preventDefault(); closeShortcuts(); return; }
    if (MODAL_STACK.length === 0) { e.preventDefault(); openShortcuts(); return; }
    return;
  }
  if (MODAL_STACK.length) {
    // V8.2.3: Enter → click по главной кнопке модалки.
    // Работает, когда фокус НЕ в поле и НЕ на кнопке.
    if (e.code === 'Enter' || e.code === 'NumpadEnter') {
      const _topId = MODAL_STACK[MODAL_STACK.length - 1];
      const _noEnter = { importModal: 1, importSourceModal: 1 };
      if (!_noEnter[_topId]) {
        const _topEl = document.getElementById(_topId);
        const _act = document.activeElement;
        const _tag = (_act && _act.tagName || '').toLowerCase();
        const _inField = _tag === 'input' || _tag === 'textarea' || _tag === 'select';
        // V8.2.3: onBtn — только если кнопка ВНУТРИ активной модалки.
        const _onBtn = _topEl && _act && _topEl.contains(_act) && _tag === 'button';
        if (_topEl && !_inField && !_onBtn) {
          const _btn =
            _topEl.querySelector('.modal-actions .btn-primary:not([disabled])')
            || _topEl.querySelector('.modal-actions .btn-danger:not([disabled])')
            || _topEl.querySelector('.modal-actions .btn:not(.btn-ghost):not([disabled])')
            || _topEl.querySelector('[data-autofocus]:not([disabled])');
          if (_btn && typeof _btn.click === 'function') {
            e.preventDefault();
            _btn.click();
            return;
          }
        }
      }
    }
    if (e.code === 'Escape') {
      e.preventDefault();
      _skipFocusReturnOnce = true;
      const top = MODAL_STACK[MODAL_STACK.length - 1];
      if (top === 'previewModal') closePreview();
      else if (top === 'statsModal') closeStats();
      else if (top === 'settingsModal') closeSettings();
      else if (top === 'exportModal') closeExportModal();
      else if (top === 'validateModal') closeValidateModal();
      else if (top === 'tagsManagerModal') closeTagsManager();
      else if (top === 'importModal') closeImportModal();
      else if (top === 'importSourceModal') closeImportSourceModal();
      else if (top === 'tracksModal') closeTracksModal();   // V8.8.1
      else if (top === 'trackPlayerModal') closeTrackPlayer();   // V8.8.4
      else if (top === 'trainModal') closeTrainModal();
      else if (top === 'similarModal') closeSimilarModal();
      else if (top === 'shortcutsModal') closeShortcuts();
      else if (top === 'tagCreateModal') closeTagCreate();
      else if (top === 'versionsModal') closeVersions();
      else if (top === 'logsModal') closeLogs();
      else if (top === 'metricsModal') closeMetricsModal();
      else if (top === 'duplicatesModal') closeDuplicatesModal();
      else if (top === 'projectModal') closeProjectModal();
      else if (top === 'ffmpegHelpModal') closeFfmpegHelp();
      else closeModal(top);
    }
    return;
  }

  if (e.key === 'Escape') {
    const openPopovers = document.querySelectorAll('.sort-menu.open, .custom-select.open, .color-picker-menu.open, .class-search.open');
    if (openPopovers.length) { e.preventDefault(); closeAllPopovers(null); return; }
  }
  const code = e.code || '';
  if (code === 'Space' && !spacePressed) {
    e.preventDefault(); spacePressed = true;
    viewport.classList.add('space-held');
    return;
  }
  if ((e.ctrlKey || e.metaKey) && code === 'KeyS') { e.preventDefault(); saveAnnotations(); return; }
  if ((e.ctrlKey || e.metaKey) && code === 'KeyZ' && !e.shiftKey) { e.preventDefault(); undo(); return; }
  if ((e.ctrlKey || e.metaKey) && (code === 'KeyY' || (e.shiftKey && code === 'KeyZ'))) { e.preventDefault(); redo(); return; }
  if ((e.ctrlKey || e.metaKey) && code === 'KeyA') {
    e.preventDefault();
    if (boxes.length) {
      multiSelected = new Set(boxes.map((_, i) => i));
      selectedIndex = -1;
      updateSelectionClasses();
      setStatus(`Выделено рамок: ${boxes.length}`);
    }
    return;
  }
  if (!e.ctrlKey && !e.metaKey && !e.altKey) {
    // V8.4.0: хоткеи для поведения (1..6) и ID (0 / Shift+0).
    const BEH_KEYS = {
      Digit1: 'eat', Digit2: 'walk', Digit3: 'lie',
      Digit4: 'drink', Digit5: 'stand', Digit6: 'active',
    };
    if (BEH_KEYS[code] && !e.shiftKey) {
      e.preventDefault();
      _applyBehaviorToTargets(BEH_KEYS[code]);
      return;
    }
    if (code === 'Digit0' && e.shiftKey) {
      e.preventDefault();
      _applyAnimalIdToTargets(null);
      return;
    }
    if (code === 'Digit0' && !e.shiftKey) {
      e.preventDefault();
      _assignNextAnimalId();
      return;
    }
    if (code === 'KeyA') { e.preventDefault(); autolabel(); return; }
    if (code === 'KeyS') { e.preventDefault(); saveAnnotations(); return; }
    if (code === 'KeyD') { e.preventDefault(); deleteSelectedBox(); return; }
    if (code === 'KeyC') { e.preventDefault(); clearBoxes(); return; }
    if (code === 'KeyF') { e.preventDefault(); toggleHardCurrent(); return; }
    if (code === 'KeyL') { e.preventDefault(); toggleFreezeSelected(); return; }
    if (code === 'KeyM') { e.preventDefault(); toggleSamMode(); return; }
    if (code === 'KeyZ') { e.preventDefault(); zoomToSelection(); return; }
    if (code === 'KeyG' && e.shiftKey) { e.preventDefault(); setDebugMode(!getDebugMode()); return; }
    if (code === 'KeyK' && e.shiftKey) { e.preventDefault(); toggleSkeletonMode(); return; }
    if (code === 'KeyR') { e.preventDefault(); runAutolabel(); return; }
    if (code === 'KeyN') { e.preventDefault(); navigateToNextUnlabeled(); return; }
    if (code === 'KeyP') { e.preventDefault(); navigateToPrevUnlabeled(); return; }
    if (code === 'Enter' || code === 'NumpadEnter') { e.preventDefault(); acceptAndNext(); return; }
    if (code === 'Equal' || code === 'NumpadAdd') { e.preventDefault(); zoomToCenter(1.25); return; }
    if (code === 'Minus' || code === 'NumpadSubtract') { e.preventDefault(); zoomToCenter(0.8); return; }
    if (code === 'Digit0' || code === 'Numpad0') { e.preventDefault(); zoomReset(); return; }
    if (code === 'Escape') {
      if (samPreview) { e.preventDefault(); _clearSamPreview(); return; }
      if (samMode) { e.preventDefault(); setSamMode(false); return; }
      selectedIndex = -1;
      multiSelected.clear();
      updateSelectionClasses();
      document.querySelectorAll('.sort-menu').forEach(m => m.classList.remove('open'));
      return;
    }
  }
  if (code.startsWith('Arrow')) {
    const indices = getSelectedIndices().filter(i => !boxes[i].frozen);
    if (indices.length) {
      e.preventDefault();
      const step = e.shiftKey ? 0.02 : 0.005;
      let dx = 0, dy = 0;
      if (code === 'ArrowRight') dx = step;
      if (code === 'ArrowLeft') dx = -step;
      if (code === 'ArrowDown') dy = step;
      if (code === 'ArrowUp') dy = -step;
      // V8.4.1: при nudge сохраняем behavior и animal_id.
      const _keepAttrs = (b) => ({
        behavior: b.behavior || null,
        animal_id: (b.animal_id != null) ? b.animal_id : null,
      });
      if (indices.length > 1) {
        indices.forEach(i => {
          const b = boxes[i];
          boxes[i] = clampBox({
            x: b.x + dx, y: b.y + dy, w: b.w, h: b.h,
            label: b.label, confidence: null, frozen: false,
            ..._keepAttrs(b),
          });
        });
      } else if (e.shiftKey) {
        const i = indices[0]; const b = boxes[i];
        boxes[i] = clampBox({
          x: b.x, y: b.y, w: b.w + dx, h: b.h + dy,
          label: b.label, confidence: null, frozen: false,
          ..._keepAttrs(b),
        });
      } else {
        const i = indices[0]; const b = boxes[i];
        boxes[i] = clampBox({
          x: b.x + dx, y: b.y + dy, w: b.w, h: b.h,
          label: b.label, confidence: null, frozen: false,
          ..._keepAttrs(b),
        });
      }
      renderBoxes(); pushHistory(); markDirty();
      return;
    }
    if (code === 'ArrowRight' || code === 'ArrowDown') { e.preventDefault(); navigateImage(1); return; }
    if (code === 'ArrowLeft' || code === 'ArrowUp') { e.preventDefault(); navigateImage(-1); return; }
  }
  if (code === 'Delete' || code === 'Backspace') {
    const freezable = getSelectedIndices().filter(i => !boxes[i].frozen);
    if (freezable.length) { e.preventDefault(); deleteSelectedBox(); }
  }
});
document.addEventListener('keyup', e => {
  if (e.code === 'Space') { spacePressed = false; viewport.classList.remove('space-held'); }
});

/* ===== Theme radiogroup ===== */
function _installThemeRadiogroup() {
  const seg = document.getElementById('themeSegment');
  if (!seg) return;
  seg.addEventListener('keydown', (e) => {
    const buttons = Array.from(seg.querySelectorAll('button[data-mode]'));
    const idx = buttons.indexOf(document.activeElement);
    if (idx < 0) return;
    let nextIdx = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') nextIdx = (idx + 1) % buttons.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') nextIdx = (idx - 1 + buttons.length) % buttons.length;
    else if (e.key === 'Home') nextIdx = 0;
    else if (e.key === 'End') nextIdx = buttons.length - 1;
    if (nextIdx >= 0) {
      e.preventDefault();
      buttons[nextIdx].focus();
      setThemeMode(buttons[nextIdx].dataset.mode);
    }
  });
}

/* ===== Drag-n-drop ===== */
function _installDropZone() {
  const main = document.querySelector('.main');
  if (!main) return;
  const overlay = document.createElement('div');
  overlay.className = 'drop-overlay';
  overlay.setAttribute('aria-hidden', 'true');
  overlay.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="17 8 12 3 7 8"/>
      <line x1="12" y1="3" x2="12" y2="15"/>
    </svg>
    <div class="drop-overlay-text">Отпусти файлы, чтобы добавить</div>
    <div class="drop-overlay-hint">Изображения или .zip с разметкой</div>
  `;
  main.appendChild(overlay);
  let dragCounter = 0;
  function isFileDrag(e) {
    if (!e.dataTransfer) return false;
    return Array.from(e.dataTransfer.types || []).includes('Files');
  }
  main.addEventListener('dragenter', (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault(); dragCounter++;
    overlay.classList.add('visible');
  });
  main.addEventListener('dragover', (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });
  main.addEventListener('dragleave', (e) => {
    if (!isFileDrag(e)) return;
    dragCounter--;
    if (dragCounter <= 0) { dragCounter = 0; overlay.classList.remove('visible'); }
  });
  main.addEventListener('drop', async (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    dragCounter = 0;
    overlay.classList.remove('visible');
    if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
    if (viewMode !== 'main') { setStatus('Выйди из корзины, чтобы загружать'); return; }
    const files = Array.from(e.dataTransfer.files || []);
    if (!files.length) return;
    const images = files.filter(f => /\.(jpe?g|png|bmp|webp|tiff?|avif|heic|heif|gif)$/i.test(f.name));
    const zips = files.filter(f => /\.zip$/i.test(f.name));
    if (images.length) await _uploadFilesViaDrag(images);
    for (const z of zips) await _importZipViaDrag(z);
  });
}
async function _uploadFilesViaDrag(files) {
  if (viewMode !== 'main') { viewMode = 'main'; updateSectionUI(); }
  setStatus(`Загрузка ${files.length} ${pluralImages(files.length)}…`, 60000);
  let added = 0, dup = 0, failed = 0;
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch(`/api/projects/${currentProjectId}/images`, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'DatasetBuilder' } });
      if (res.status === 409) dup++;
      else if (res.ok) added++;
      else failed++;
    } catch (e) { failed++; }
  }
  await loadImages();
  const parts = [`Загружено: ${added}`];
  if (dup) parts.push(`дубликатов: ${dup}`);
  if (failed) parts.push(`ошибок: ${failed}`);
  setStatus(parts.join(', '), 6000);
  if (added > 0) haptic('success');
}
async function _importZipViaDrag(file) {
  setStatus(`Импорт ${file.name}…`, 300000);
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`/api/projects/${currentProjectId}/import`, { method: 'POST', body: fd, headers: { 'X-Requested-With': 'DatasetBuilder' } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError('Ошибка импорта: ' + (data.detail || '')); return; }
    await loadImages();
    setSuccess(`Импорт: +${data.imported_images || 0} фото, ${data.added_annotations || 0} рамок`, 6000);
    haptic('success');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 120)); }
}

/* ===== Init ===== */
async function checkModelsAvailability() {
  try {
    const r = await api('/api/models');
    if (!r.models.length) {
      try {
        const bs = await api('/api/models/bootstrap/status');
        if (bs.status === 'downloading') return;
      } catch (e) {}
      setStatus('Моделей нет — авторазметка выключена. Скачай или обучи модель в Настройках.', 8000);
    }
  } catch (e) {}
}

function _installLangSegment() {
  const seg = document.getElementById('langSegment');
  if (!seg) return;
  function _sync() {
    const cur = getLang();
    seg.querySelectorAll('button[data-lang]').forEach(b => {
      const active = b.dataset.lang === cur;
      b.classList.toggle('active', active);
      b.setAttribute('aria-checked', active ? 'true' : 'false');
      b.setAttribute('tabindex', active ? '0' : '-1');
    });
  }
  seg.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-lang]');
    if (!b) return;
    setLang(b.dataset.lang);
    _sync();
  });
  window.addEventListener('pdb-lang-change', _sync);
  _sync();
}

document.addEventListener('DOMContentLoaded', () => {
  _installTooltipObserver();
  _installThemeRadiogroup();
  _installDropZone();
  _installLangSegment();
  applyI18nToDOM();
  applyTheme();
  setHideHints(getHideHints());
  showCanvas(false);
  initCustomSelects();
  initColorPickers();
  setupSortMenu();
  setupFilterMenu();
  updateSaveIndicator();
  updateBulkBar();
  updateTrashBar();
  updateSectionUI();
  applyTransform();

  loadObjectClasses().catch(() => {});

  api('/api/version').then(v => {
    if (v && v.version) {
      APP_VERSION = v.version;
      document.querySelectorAll('.version-badge').forEach(b => { b.textContent = v.version; });
    }
  }).catch(() => {});

  document.getElementById('selectAllCheck').addEventListener('change', toggleSelectAll);
  document.getElementById('themeSegment').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-mode]');
    if (!b) return;
    setThemeMode(b.dataset.mode);
  });
  document.getElementById('hideHintsToggle').addEventListener('change', (e) => setHideHints(e.target.checked));

  // V8.3.0: панель атрибутов
  _installAttrBar();
  _refreshAttrBar();
  // V8.5.1: скелет
  loadKeypointSchema().catch(() => {});
  _installSkeletonDblClick();   // V8.5.3

  // V8.2.0: сегмент режима авторазметки
  const alSeg = document.getElementById('autolabelModeSegment');
  if (alSeg) {
    setAutolabelMode(getAutolabelMode());
    alSeg.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-mode]');
      if (!b) return;
      setAutolabelMode(b.dataset.mode);
    });
    alSeg.addEventListener('keydown', (e) => {
      const btns = Array.from(alSeg.querySelectorAll('button[data-mode]'));
      const idx = btns.indexOf(document.activeElement);
      if (idx < 0) return;
      let next = -1;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (idx + 1) % btns.length;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (idx - 1 + btns.length) % btns.length;
      if (next >= 0) {
        e.preventDefault();
        btns[next].focus();
        setAutolabelMode(btns[next].dataset.mode);
      }
    });
  }
  const ttaEl = document.getElementById('ttaToggle');
  if (ttaEl) {
    ttaEl.checked = getTta();
    ttaEl.addEventListener('change', (e) => setTta(e.target.checked));
  }
  const dbgToggleEl = document.getElementById('debugModeToggle');
  if (dbgToggleEl) {
    dbgToggleEl.checked = getDebugMode();
    dbgToggleEl.addEventListener('change', (e) => setDebugMode(e.target.checked));
  }

  const skipLink = document.querySelector('.skip-link');
  if (skipLink) {
    skipLink.addEventListener('click', (e) => {
      const main = document.getElementById('mainContent');
      if (main) {
        e.preventDefault();
        main.focus();
        main.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
      }
    });
  }

  const si = document.getElementById('searchInput');
  const sc = document.getElementById('searchClear');
  // V7.9.3: поиск с debounce 300 мс — не бомбим сервер на каждую букву.
  let _searchDebounce = null;
  si.addEventListener('input', () => {
    searchQuery = si.value.trim().toLowerCase();
    sc.classList.toggle('visible', !!searchQuery);
    if (_searchDebounce) clearTimeout(_searchDebounce);
    _searchDebounce = setTimeout(() => {
      _searchDebounce = null;
      loadImages();
    }, 300);
  });

  const _listEl = document.getElementById('imageList');
  const _listScroller = _listEl.closest('.sidebar-body') || _listEl;
  _listScroller.addEventListener('scroll', onListScroll, { passive: true });
  window.addEventListener('resize', () => renderImageList());

  const lvlF = document.getElementById('logsLevelFilter');
  const catF = document.getElementById('logsCategoryFilter');
  if (lvlF) lvlF.addEventListener('change', () => refreshLogs());
  if (catF) catF.addEventListener('change', () => refreshLogs());
  const autoCb = document.getElementById('logsAutoRefresh');
  if (autoCb) autoCb.addEventListener('change', () => {
    if (autoCb.checked) startLogsAutoRefresh(); else stopLogsAutoRefresh();
  });

  const closeHandlers = {
    dialogModal: () => _closeDialog(null),
    exportModal: () => closeExportModal(),
    tagsManagerModal: () => closeTagsManager(),
    trainModal: () => closeTrainModal(),
    similarModal: () => closeSimilarModal(),
    statsModal: () => closeStats(),
    validateModal: () => closeValidateModal(),
    settingsModal: () => closeSettings(),
    previewModal: () => closePreview(),
    importModal: () => {
      if (document.getElementById('importCloseBtn').style.display !== 'none') closeImportModal();
    },
    importSourceModal: () => closeImportSourceModal(),
    tagCreateModal: () => closeTagCreate(),
    shortcutsModal: () => closeShortcuts(),
    versionsModal: () => closeVersions(),
    logsModal: () => closeLogs(),
    projectModal: () => closeProjectModal(),
    metricsModal: () => closeMetricsModal(),
    duplicatesModal: () => closeDuplicatesModal(),
    ffmpegHelpModal: () => closeFfmpegHelp(),
    tracksModal: () => closeTracksModal(),   // V8.8.1
    trackPlayerModal: () => closeTrackPlayer(),   // V8.8.4
  };
  Object.entries(closeHandlers).forEach(([id, fn]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('mousedown', (e) => { if (e.target.id === id) fn(); });
  });

  const projCancelBtn = document.getElementById('projectModalCancel');
  if (projCancelBtn) projCancelBtn.onclick = () => closeProjectModal();
  const projOkBtn = document.getElementById('projectModalOk');
  if (projOkBtn) projOkBtn.onclick = () => submitProjectModal();
  const projClearBtn = document.getElementById('projectClearAnnBtn');
  if (projClearBtn) projClearBtn.onclick = () => clearProjectAnnotations();

  const projNameInput = document.getElementById('projectNameInput');
  if (projNameInput) {
    projNameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const ok = document.getElementById('projectModalOk');
        if (ok && !ok.disabled) submitProjectModal();
      }
    });
  }

  const ttlInp = document.getElementById('projectTtlInput');
  if (ttlInp) ttlInp.addEventListener('input', () => {
    const v = ttlInp.value.trim();
    if (!v) { _projectTtlOverride = null; }
    else {
      const n = parseInt(v, 10);
      _projectTtlOverride = (isNaN(n) || n < 0) ? null : Math.min(3650, n);
    }
    _validateProjectForm();
  });
  const thumbSel = document.getElementById('projectThumbSelect');
  if (thumbSel) thumbSel.addEventListener('change', () => {
    const v = thumbSel.value;
    _projectThumbSize = v === '' ? null : parseInt(v, 10);
    _validateProjectForm();
  });
  const zoomSel = document.getElementById('projectZoomSelect');
  if (zoomSel) zoomSel.addEventListener('change', () => {
    const v = zoomSel.value;
    _projectDefaultZoom = v === '' ? null : parseFloat(v);
    _validateProjectForm();
  });

  document.getElementById('newTagNameInline').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); createTagInline(); }
  });

  document.addEventListener('click', (e) => {
    document.querySelectorAll('.sort-menu').forEach(m => {
      if (m.id === 'exportMenu') {
        const btn = document.getElementById('exportBtn');
        if (btn && btn.contains(e.target)) return;
        if (m.contains(e.target)) return;
      }
      m.classList.remove('open');
    });
    if (!e.target.closest('.custom-select')) {
      document.querySelectorAll('.custom-select.open').forEach(w => w.classList.remove('open'));
    }
  });

  applyFocusMode();
  _installCommandPaletteListeners();
  _checkSamModel();
  checkVideoCapabilities();
  _installVideoListeners();

  loadProjects();
  subscribeBootstrapEvents();
  api('/api/train/status')
    .then(s => {
      _updateTrainingIndicator(s);
      if (s.status === 'running' || s.status === 'stopping' || s.status === 'preparing') subscribeTrainEvents();
    })
    .catch(() => {});
  api('/api/autolabel/batch/status')
    .then(s => { if (s.status === 'running') { batchRunning = true; subscribeBatchEvents(); } })
    .catch(() => {});
  setTimeout(checkModelsAvailability, 1500);
});