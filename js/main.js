import { initEventDelegation } from './events.js';
// @ts-check
import { api, downloadFile } from './api.js';
import { VERSION_HISTORY } from './changelog.js';
import { State, subscribe } from './store.js';
import {
  haptic, escapeHtml, plural, pluralImages, pluralProjects, pluralGroups,
  onActivate, getExt, getStem, fmtSize, _fmtBytes, animateNumber
} from './utils.js';
import { getRel, clampBox, applyTransform, clampPan, zoomAt, zoomToCenter, zoomReset, zoomFit, zoomToSelection, installCanvasListeners } from './canvas.js';
import { installKeyboardListeners } from './keyboard.js';
import {
  getThemeMode, applyTheme, setThemeMode, updateThemeSegment,
  getHideHints, setHideHints, getFocusMode, setFocusMode, toggleFocusMode, applyFocusMode
} from './theme.js';
import {
  openCommandPalette, closeCommandPalette, _installCommandPaletteListeners,
  _paletteHistory, _pushPaletteHistory
} from './command_palette.js';
import {
  MODAL_STACK, openModal, closeModal, isModalOpen, trapFocus,
  showAlert, showConfirm, showPrompt, _openDialog, _closeDialog, _openCustomDialog,
  _installTooltipObserver, hideTooltip, convertTitlesIn
} from './ui.js';
/* ===========================================
   Dataset Builder — JavaScript
   V11.2.0
   =========================================== */

/**
 * @typedef {Object} BoxData
 * @property {number} x
 * @property {number} y
 * @property {number} w
 * @property {number} h
 * @property {string} label
 * @property {number|null} confidence
 * @property {boolean} frozen
 * @property {string|null} behavior
 * @property {number|null} animal_id
 * @property {Array<Object>} keypoints
 */

let APP_VERSION = "unknown"; // обновится через /api/version

/* ==== Reduced Motion ==== */
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
/* ==== Popover helpers ==== */
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
    if (!exceptEl || !w.contains(exceptEl)) {
      if (w.__close) w.__close();
      else w.classList.remove('open');
    }
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

/* ==== Utils ==== */
// V11.12.0: Функции вынесены в js/utils.js и импортированы выше.

/* ==== V8.1.0: Browser Notifications ==== */
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

/* ==== Custom Select ==== */
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
  wrap.__close = close;
  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.custom-select.open').forEach(w => {
      if (w !== wrap && w.__close) w.__close();
    });
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

/* ==== Color Picker ==== */
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

/* ===================================================
   Object class search
   =================================================== */
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
  inputEl.placeholder = opts.placeholder || t('projectModal.classSearchPlaceholder');
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
// [FIX:v1341-frontend] project-aware schema cache
let _kpSchemaProjectId = 'unset';
async function loadKeypointSchema(projectId = null, force = false) {
  if (!force && keypointSchema && _kpSchemaProjectId === String(projectId)) {
    return keypointSchema;
  }
  try {
    const url = projectId
      ? `/api/keypoint_schema?project_id=${encodeURIComponent(projectId)}`
      : '/api/keypoint_schema';
    keypointSchema = await api(url);
    _kpSchemaProjectId = String(projectId);
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

/* ==== Status ==== */
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

/* ==== V10.4.1: управление долгими операциями ====
   Универсальный механизм: startOperation(type, cancelFn) показывает кнопку
   отмены в тулбаре; endOperation() прячет её. cancelActiveOperation()
   вызывает переданный cancelFn один раз и блокирует кнопку от повторных
   кликов. Используется для batch-автолейбла, трекинга и импорта. */
let _activeOp = null;
function startOperation(type, cancelFn) {
  _activeOp = { type: type, cancelFn: cancelFn };
  const btn = document.getElementById('cancelOpBtn');
  if (btn) { btn.style.display = ''; btn.disabled = false; }
}
function endOperation() {
  _activeOp = null;
  const btn = document.getElementById('cancelOpBtn');
  if (btn) btn.style.display = 'none';
}
async function cancelActiveOperation() {
  if (!_activeOp) return;
  const btn = document.getElementById('cancelOpBtn');
  if (btn) btn.disabled = true;
  try {
    if (typeof _activeOp.cancelFn === 'function') {
      await _activeOp.cancelFn();
    }
  } catch (e) {
    console.warn('cancel operation failed:', e);
  }
}

/* ==== State ==== */
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
// V11.10.1: Удалена старая декларация currentImageId (используем State)
let imagesList = [];
let allImages = [];
// V7.9.3: пагинация списка изображений
const IMAGES_PAGE_SIZE = 200;
let _imagesTotalInProject = 0;
let _imagesAnnotatedInProject = 0;
let _imagesHasMore = false;
let _imagesLoadingMore = false;
// V11.5.0: Reactive State Store
window.AppState = State;
window.State = State; // V11.10.7: Привязка для focus listener

/** @type {BoxData[]} */
let boxes = State.boxes;
let selectedIndex = State.selectedIndex;
let multiSelected = State.multiSelected;
let currentImageId = State.currentImageId;

subscribe((prop, val) => {
  if (prop === 'boxes') boxes = val;
  if (prop === 'selectedIndex') selectedIndex = val;
  if (prop === 'multiSelected') multiSelected = val;
  if (prop === 'currentImageId') { currentImageId = val; window.currentImageId = val; }  // V11.10.16: sync currentImageId to window
});
// V11.10.16: initial sync — canvas.js/keyboard.js читают window.currentImageId
window.currentImageId = currentImageId;
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
if (!['none', 'unannotated', 'lowconf', 'hard', 'duplicates', 'uncertain'].includes(activeFilter)) activeFilter = 'none';

let searchQuery = '';
let activeTagIds = new Set();
let projectTags = [];
let projectTagsMap = new Map();
let currentImageTagIds = new Set();

// zoom/panX/panY moved to window.AppState
const ZOOM_MIN = 0.5, ZOOM_MAX = 8;

let spacePressed = false;
let isPanning = false;
let panStart = null;

let history = []; let historyIndex = -1;
const _historyMap = new Map(); // V11.8.3: history per image
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
// [FIX:v1341-frontend]
let _projectAutoBlurEnabled = false;
let _projectAutoBlurClasses = ['person'];
let _projectGlobalTtl = 30;

// V8.0.0: кэш результата валидатора — не пересчитываем при каждом открытии.
let _validateCache = null;   // { projectId, data }
function _invalidateValidateCache() { _validateCache = null; }

// V8.5.1: скелет.
let skeletonMode = false;
// V11.8.2: sync module skeletonMode → window.skeletonMode (canvas.js checks it)
window.skeletonMode = false;
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


/* ==== Helpers: sections / debug ==== */
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

  // [FIX:SECTIONS-TOGGLE-V3]
  let group = false;
  try { group = localStorage.getItem('pdb_group_sections') === '1'; } catch(e) {}
  if (!group) return sorted;

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

/* ==== V7.8.0: debug-режим YOLO ==== */
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

/* ==== SSE bootstrap ==== */
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

/* ==== Projects ==== */
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
    e.textContent = t('sidebar.projects.empty');
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
      allImages = []; imagesList = []; // [PERF:gc-memory]
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

  titleEl.textContent = t('projectModal.titleCreate');
  nameLabel.textContent = t('projectModal.nameLabel');
  classLabel.textContent = t('projectModal.classLabel');
  nameInput.disabled = false;
  nameInput.value = '';
  warnEl.style.display = 'none';
  clearBtn.style.display = 'none';
  if (advBlock) advBlock.style.display = 'none';
  // [V13.2.1:calibration-hide-create]
  const calibCreate = document.getElementById('projectCalibrationGroup');
  if (calibCreate) calibCreate.style.display = 'none';
  const kpCreate = document.getElementById('projectKeypointSchemaGroup');
  if (kpCreate) kpCreate.style.display = 'none';
  okBtn.textContent = t('projectModal.create');
  okBtn.disabled = true;
  _projectThumbSize = null;
  _projectDefaultZoom = null;
  _projectTtlOverride = null;
  _projectAutoBlurEnabled = false;
  _projectAutoBlurClasses = ['person'];

  if (_projectClassSearch) _projectClassSearch.destroy();
  _projectClassSearch = createClassSearch(classHost, {
    initialValue: '',
    initialSource: 'list',
    disabled: false,
    placeholder: t('projectModal.classPlaceholder'),
    onChange: () => _validateProjectForm(),
  });

  nameInput.oninput = () => _validateProjectForm();
  openModal('projectModal');
  setTimeout(() => { try { nameInput.focus(); } catch (e) {} }, 100);

  const status = objectClassesCache;
  if (status.source === 'empty') {
    warnEl.style.display = 'block';
    warnEl.className = 'project-warn warn-info';
    warnEl.textContent = t('projectModal.classWarnEmpty');
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

  titleEl.textContent = t('projectModal.titleEdit');
  nameLabel.textContent = t('projectModal.nameLabel');
  classLabel.textContent = t('projectModal.classLabel');
  nameInput.disabled = false;
  nameInput.value = info.name || '';
  okBtn.textContent = t('projectModal.save');
  okBtn.disabled = true;

  const annsCount = info.annotations_count || 0;
  const isClassLocked = annsCount > 0;

  if (_projectClassSearch) _projectClassSearch.destroy();
  _projectClassSearch = createClassSearch(classHost, {
    initialValue: info.object_class || 'pig',
    initialSource: info.object_class_source === 'custom' ? 'custom' : 'list',
    disabled: isClassLocked,
    placeholder: t('projectModal.classSearchPlaceholder'),
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
    warnEl.textContent = t('projectModal.classWarnEmpty');
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
  // [V13.2.1:calibration-hide-create]
  const calibEdit = document.getElementById('projectCalibrationGroup');
  if (calibEdit) calibEdit.style.display = '';
  _fillProjectAdvancedSettings(info);
  // [FRONTEND:kp-schema-load]
  const kpEdit = document.getElementById('projectKeypointSchemaGroup');
  if (kpEdit) kpEdit.style.display = '';
  _loadKeypointSchemaForProject(info.id).catch(() => {});
  // [FIX:v1341-frontend]
  _refreshClassifierMeta(info.id).catch(() => {});
  openModal('projectModal');
  _validateProjectForm();
}

function _fillProjectAdvancedSettings(info) {
  _projectGlobalTtl = info.global_trash_ttl != null ? info.global_trash_ttl : 30;
  _projectTtlOverride = info.trash_ttl_days_override ?? null;
  _projectThumbSize = info.thumbnail_size ?? null;
  _projectDefaultZoom = info.default_zoom ?? null;

  // [FIX:v1341-frontend] Auto-blur
  _projectAutoBlurEnabled = !!info.auto_blur_enabled;
  try {
    const raw = info.auto_blur_classes;
    const arr = raw ? (typeof raw === 'string' ? JSON.parse(raw) : raw) : null;
    _projectAutoBlurClasses = (Array.isArray(arr) && arr.length) ? arr : ['person'];
  } catch (e) { _projectAutoBlurClasses = ['person']; }
  const abToggle = document.getElementById('autoBlurToggle');
  if (abToggle) abToggle.checked = _projectAutoBlurEnabled;
  const abBlock = document.getElementById('autoBlurClassesBlock');
  if (abBlock) abBlock.style.display = _projectAutoBlurEnabled ? 'flex' : 'none';
  document.querySelectorAll('[data-blur-class]').forEach(cb => {
    cb.checked = _projectAutoBlurClasses.includes(cb.dataset.blurClass);
  });

  const ttlInput = document.getElementById('projectTtlInput');
  if (ttlInput) {
    ttlInput.value = _projectTtlOverride != null ? String(_projectTtlOverride) : '';
    ttlInput.placeholder = t('projectModal.ttlPlaceholder');
  }
  const ttlHint = document.getElementById('projectTtlHint');
  if (ttlHint) ttlHint.textContent = t('projectModal.ttlHint.dynamic', { n: _projectGlobalTtl });

  // [PATCH:STAGE1_DATA_RETENTION_FILL]
  const _retentionInput = document.getElementById('projectRetentionInput');
  if (_retentionInput) {
    const _rv = (info.data_retention_days ?? 0);
    _retentionInput.value = (_rv > 0) ? String(_rv) : '';
  }

  const thumbSel = document.getElementById('projectThumbSelect');
  if (thumbSel) thumbSel.value = _projectThumbSize != null ? String(_projectThumbSize) : '';

  const zoomSel = document.getElementById('projectZoomSelect');
  if (zoomSel) zoomSel.value = _projectDefaultZoom != null ? String(_projectDefaultZoom) : '';
}

function _validateProjectForm() {
  const nameInput = document.getElementById('projectNameInput');
  const okBtn = document.getElementById('projectModalOk');
  if (!nameInput || !okBtn) return;

  const nameOk = nameInput.value.trim().length > 0;
  const classVal = _projectClassSearch ? _projectClassSearch.getValue() : { value: '', source: 'list' };
  const classOk = !!classVal.value;
  okBtn.disabled = !(nameOk && classOk);

  if (_projectModalMode === 'edit' && _projectModalTarget) {
    const target = _projectModalTarget;
    const sameClass = (t.object_class || 'pig') === classVal.value &&
      ((t.object_class_source || 'list') === classVal.source);
    const sameName = (t.name || '') === nameInput.value.trim();
    const sameTtl = (t.trash_ttl_days_override ?? null) === _projectTtlOverride;
    const sameThumb = (t.thumbnail_size ?? null) === _projectThumbSize;
    const sameZoom = (t.default_zoom ?? null) === _projectDefaultZoom;
    // [FIX:v1341-frontend] auto-blur diff
    const _normAb = (v) => {
      try {
        const a = v ? (typeof v === 'string' ? JSON.parse(v) : v) : [];
        return Array.isArray(a) ? [...a].sort() : [];
      } catch (e) { return []; }
    };
    const sameAutoBlur = (!!t.auto_blur_enabled === !!_projectAutoBlurEnabled)
      && JSON.stringify(_normAb(target.auto_blur_classes))
        === JSON.stringify(_normAb(_projectAutoBlurClasses));
    const advancedChanged = !(sameTtl && sameThumb && sameZoom && sameAutoBlur);
    if (sameClass && sameName && !advancedChanged) okBtn.disabled = true;
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
  if (!classVal.value) { setStatus(t('projectModal.pickClass')); return; }

  if (_projectModalMode === 'create') {
    const name = nameInput.value.trim();
    if (!name) { setStatus(t('projectModal.enterName')); return; }
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
      setError(t('error.prefix') + String(e.message).slice(0, 160));
    }
    return;
  }

  if (_projectModalMode === 'edit' && _projectModalTarget) {
    okBtn.disabled = true;
    okBtn.textContent = 'Сохраняем…';
    try {
      const target = _projectModalTarget;
      const body = {
        object_class: classVal.value,
        object_class_source: classVal.source,
      };
      const newName = nameInput.value.trim();
      if (newName && newName !== target.name) {
        body.name = newName;
      }
      if ((target.thumbnail_size ?? null) !== _projectThumbSize) {
        if (_projectThumbSize != null) body.thumbnail_size = _projectThumbSize;
        else body.clear_thumbnail_size = true;
      }
      if ((target.default_zoom ?? null) !== _projectDefaultZoom) {
        if (_projectDefaultZoom != null) body.default_zoom = _projectDefaultZoom;
        else body.clear_default_zoom = true;
      }
      if ((target.trash_ttl_days_override ?? null) !== _projectTtlOverride) {
        if (_projectTtlOverride != null) body.trash_ttl_days_override = _projectTtlOverride;
        else body.clear_ttl_override = true;
      }
      // // [PATCH:STAGE1_DATA_RETENTION_SUBMIT]
      const _retentionEl = document.getElementById('projectRetentionInput');
      if (_retentionEl) {
        const _rv = parseInt(_retentionEl.value, 10);
        const _rn = (isNaN(_rv) || _rv < 0) ? 0 : Math.min(3650, _rv);
        const _prev = (t.data_retention_days ?? 0) || 0;
        if (_rn !== _prev) body.data_retention_days = _rn;
      }
      // [/PATCH:STAGE1_DATA_RETENTION_SUBMIT]
      // [FIX:v1341-frontend] auto-blur fields
      if (!!target.auto_blur_enabled !== !!_projectAutoBlurEnabled) {
        body.auto_blur_enabled = !!_projectAutoBlurEnabled;
      }
      const _normAb2 = (v) => {
        try {
          const a = v ? (typeof v === 'string' ? JSON.parse(v) : v) : [];
          return Array.isArray(a) ? [...a].sort() : [];
        } catch (e) { return []; }
      };
      if (JSON.stringify(_normAb2(t.auto_blur_classes))
          !== JSON.stringify(_normAb2(_projectAutoBlurClasses))) {
        body.auto_blur_classes = Array.isArray(_projectAutoBlurClasses)
          ? _projectAutoBlurClasses : ['person'];
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
      else setError(t('error.prefix') + String(e.message).slice(0, 160));
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
        try { State.boxes = await api(`/api/images/${currentImageId}/annotations`); }
        catch (e) { State.boxes = []; }
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
      State.currentImageId = null; State.boxes = []; State.selectedIndex = -1; multiSelected.clear();
      _rememberProjectId(null);   // V8.5.3
      const imgEl = document.getElementById('image');
      if (imgEl) imgEl.removeAttribute('src');
      renderBoxes(); showCanvas(false); resetHistory(); markClean();
    }
    await loadProjects();
    setStatus(t('toast.projectDeleted', { name }));
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}
async function restoreProject(id) {
  try {
    const r = await api(`/api/projects/${id}/restore`, { method: 'POST' });
    setStatus(t('toast.projectRestored', { name: r.name }));
    haptic('success');
    if (viewMode === 'trash') await loadImages();
    await loadProjects();
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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
      State.currentImageId = null; State.boxes = []; State.selectedIndex = -1; multiSelected.clear();
      const imgEl = document.getElementById('image');
      if (imgEl) imgEl.removeAttribute('src');
      renderBoxes(); showCanvas(false); resetHistory(); markClean();
    }
    if (viewMode === 'trash') await loadImages();
    await loadProjects();
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}

/* ==== Trash ==== */
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
  State.currentImageId = null;
  State.boxes = []; State.selectedIndex = -1; multiSelected.clear();
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

/* ==== Logs ==== */
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}

/* ==== Backup ==== */
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

/* ==== Tags ==== */
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
    else setError(t('error.prefix') + String(e.message).slice(0, 120));
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}
function openTagsManagerFromSettings() { closeSettings(); setTimeout(() => openTagsManager(), 80); }
function openTagsManager() { renderTagsManager(); openModal('tagsManagerModal'); }
function closeTagsManager() { closeModal('tagsManagerModal'); }

/* ==== Tag chips ==== */
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
    else setError(t('error.prefix') + String(e.message).slice(0, 120));
  }
}

/* ==== Bulk-tag menu ==== */
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 140)); }
}

/* ==== Filters / sort ==== */
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
  // [PERF:skip-client-sort] При серверной сортировке не тратим CPU клиента
  const _isServerSort = ['date_asc','date_desc','size_asc','size_desc','name_asc','name_desc','type_asc','type_desc'].includes(sortMode);
  if (!_isServerSort && activeFilter === 'none') {
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

  // [FRONTEND:uncertain-branch]
  if (activeFilter === 'uncertain') {
    await _loadUncertainImages();
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
  // [PERF:frontend-paging]
  const usePaging = (sortMode.startsWith('date_') || sortMode.startsWith('size_') || sortMode.startsWith('name_') || sortMode.startsWith('type_'))
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

/* ==== Sidebar-scroll adapter ==== */
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

/* ==== Virtual scroll + FLIP ==== */
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
    if (viewMode === 'trash') e.textContent = t('sidebar.images.empty.trash');
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

/* ==== Progress / bars ==== */
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
    el.textContent = t('sidebar.images.empty.trash');
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
function clearListSelection() {
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
/* ===================================================
   V8.3.0: панель атрибутов (поведение + номер животного)
   =================================================== */
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
    const same = targets.every(i => boxes[i] && (boxes[i].behavior || null) === beh &&  // V11.10.16: guard boxes[i]
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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
          bbox: { x: job.box.x, y: job.box.y, w: job.box.w, h: job.box.h },  // [STAGE1-A:behavior-bbox-relative]
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
    // V11.4.0: Перезагружаем аннотации с сервера напрямую (keypoints уже внутри)
    try {
      State.boxes = await api(`/api/images/${currentImageId}/annotations`);
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
    // V10.4.1: кнопка "Отменить" на всё время трекинга.
    startOperation('track', () => api('/api/videos/' + videoId + '/track/stop', { method: 'POST' }));
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
    endOperation();   // V10.4.1
    if (s.status === 'done') {
      setStatus(t('attr.track.done', {
        tracks: s.tracks, assignments: s.assignments,
      }), 6000);
      haptic('success');
      // Обновляем список кадров и текущий кадр.
      loadImages();
      if (currentImageId) {
        api('/api/images/' + currentImageId + '/annotations')
          .then(anns => { State.boxes = anns || []; renderBoxes(); })
          .catch(() => {});
      }
    } else if (s.status === 'stopped') {
      setStatus(t('attr.track.stopped'), 4000);
    } else {
      setStatus(t('attr.track.error') + ': ' + (s.message || ''), 6000);
      haptic('error');
    }
  };
  es.onerror = () => {
    try { es.close(); } catch (e) {}
    _trackEventSource = null;
    endOperation();   // V10.4.1
  };
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
      State.boxes = await api(`/api/images/${currentImageId}/annotations`);
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

// [STAGE1-B:track-mgmt-ui]
async function openTrackMgmtModal() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  const body = document.getElementById('trackMgmtBody');
  body.innerHTML = '<p style="color:var(--text-secondary);">Загрузка…</p>';
  openModal('trackMgmtModal');
  try {
    const [q, tracks] = await Promise.all([
      api(`/api/projects/${currentProjectId}/tracks/quality`),
      api(`/api/projects/${currentProjectId}/tracks`),
    ]);
    body.innerHTML = '';
    const summary = document.createElement('div');
    summary.style.cssText = 'padding:10px 12px;background:var(--bg-hover);border-radius:10px;margin-bottom:12px;font-size:0.8125rem;';
    summary.innerHTML = `<div>Треков: <b>${q.total_tracks}</b></div>
      <div>Треков из 1 кадра: <b style="color:var(--warning)">${q.single_frame_tracks.length}</b> (${q.single_frame_pct.toFixed(1)}%)</div>
      <div>Разрывов &gt; 3: <b style="color:var(--warning)">${q.big_gaps.length}</b></div>`;
    body.appendChild(summary);
    // [PATCH:STAGE2_1:track-metrics-btn]
    const _metricsRow = document.createElement('div');
    _metricsRow.style.cssText = 'padding:8px 0 12px;';
    const _metricsBtn = document.createElement('button');
    _metricsBtn.className = 'btn btn-primary btn-sm';
    _metricsBtn.textContent = '📊 Рассчитать метрики (MOTA/IDF1)';
    _metricsBtn.onclick = () => window._computeTrackMetrics();
    _metricsRow.appendChild(_metricsBtn);
    body.appendChild(_metricsRow);
    // [/PATCH:STAGE2_1:track-metrics-btn]

    (tracks.items || []).forEach(it => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--hairline);flex-wrap:wrap;';
      const nm = document.createElement('span');
      nm.style.flex = '1 1 120px'; nm.style.minWidth = '120px';
      nm.textContent = `#${it.animal_id} — ${it.frames_count} кадров`;
      row.appendChild(nm);
      const btns = document.createElement('div');
      btns.style.cssText = 'display:flex;gap:6px;flex:none;';
      const rb = document.createElement('button');
      rb.className = 'btn btn-ghost btn-sm';
      rb.textContent = t('tracks.mgmt.reassign');
      rb.onclick = async () => {
        const nv = await showPrompt('Новый ID', { defaultValue: String(it.animal_id), okText: 'OK' });
        if (!nv) return;
        const nn = parseInt(nv, 10);
        if (isNaN(nn) || nn <= 0) return;
        try {
          await api(`/api/projects/${currentProjectId}/tracks/reassign`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_animal_id: it.animal_id, new_animal_id: nn }),
          });
          setStatus(`#${it.animal_id} → #${nn}`);
          openTrackMgmtModal();
        } catch (e) { setError(String(e.message).slice(0, 160)); }
      };
      btns.appendChild(rb);
      const mb = document.createElement('button');
      mb.className = 'btn btn-ghost btn-sm';
      mb.textContent = t('tracks.mgmt.merge');
      mb.onclick = async () => {
        const tv = await showPrompt(`Слить #${it.animal_id} в ID`, { defaultValue: String(it.animal_id), okText: 'Слить' });
        if (!tv) return;
        const tn = parseInt(tv, 10);
        if (isNaN(tn) || tn <= 0 || tn === it.animal_id) return;
        try {
          await api(`/api/projects/${currentProjectId}/tracks/merge`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_animal_ids: [it.animal_id], target_animal_id: tn }),
          });
          setStatus(`#${it.animal_id} → #${tn}`);
          openTrackMgmtModal();
        } catch (e) { setError(String(e.message).slice(0, 160)); }
      };
      btns.appendChild(mb);
      const db_ = document.createElement('button');
      db_.className = 'btn btn-ghost btn-sm';
      db_.style.color = 'var(--danger)';
      db_.textContent = t('tracks.mgmt.delete');
      db_.onclick = async () => {
        if (!await showConfirm('Удалить трек?', `animal_id=${it.animal_id} будет очищен у всех рамок.`, { danger: true, okText: 'Удалить' })) return;
        try {
          await api(`/api/projects/${currentProjectId}/tracks/${it.animal_id}`, { method: 'DELETE' });
          setStatus(`Трек #${it.animal_id} удалён`);
          openTrackMgmtModal();
        } catch (e) { setError(String(e.message).slice(0, 160)); }
      };
      btns.appendChild(db_);
      row.appendChild(btns);
      body.appendChild(row);
    });
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger);">Ошибка: ' + escapeHtml(String(e.message)) + '</p>';
  }
}

function closeTrackMgmtModal() { closeModal('trackMgmtModal'); }
window.openTrackMgmtModal = openTrackMgmtModal;
window.closeTrackMgmtModal = closeTrackMgmtModal;


// [STAGE1-C:video-player-ui]
// [V13.1.0:video-custom]
async function openVideoPlayer(videoId) {
  const el = document.getElementById('videoPlayerEl');
  const canvas = document.getElementById('videoPlayerCanvas');
  const meta = document.getElementById('videoPlayerMeta');
  const seekBar = document.getElementById('vpSeekBar');
  const timeEl = document.getElementById('vpTime');
  const playBtn = document.getElementById('vpPlayBtn');
  const interpCb = document.getElementById('vpInterpolateToggle');

  el.src = `/api/videos/${videoId}/stream`;
  openModal('videoPlayerModal');

  let frameAnns = {};
  let currentKey = null;
  let _vidInfo = null;

  try {
    const r = await api(`/api/videos/${videoId}/frame_annotations`);
    frameAnns = r.frames || {};
  } catch (e) {}

  async function awaitVidInfo() {
    if (_vidInfo) return _vidInfo;
    try { _vidInfo = await api(`/api/videos/${videoId}`); } catch (e) { _vidInfo = {}; }
    return _vidInfo;
  }

  // [FIX:v1341-frontend] Обратный letterbox: bbox (в 640×640) → координаты видео.
  function _annBboxToVideo(b, vw, vh) {
    const FW = 640, FH = 640;
    const s = Math.min(FW / vw, FH / vh);
    const iw = vw * s;
    const ih = vh * s;
    const ox = (FW - iw) / 2;
    const oy = (FH - ih) / 2;
    return {
      x: (b.x * FW - ox) / iw,
      y: (b.y * FH - oy) / ih,
      w: (b.w * FW) / iw,
      h: (b.h * FH) / ih,
    };
  }

  function draw() {
    const W = el.clientWidth, H = el.clientHeight;
    if (!W || !H || !el.videoWidth || !el.videoHeight) return;
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);

    const videoRatio = el.videoWidth / el.videoHeight;
    const containerRatio = W / H;
    let drawW, drawH, offX = 0, offY = 0;
    if (videoRatio > containerRatio) {
      drawW = W; drawH = W / videoRatio; offY = (H - drawH) / 2;
    } else {
      drawH = H; drawW = H * videoRatio; offX = (W - drawW) / 2;
    }

    const vid = _vidInfo || {};
    if (!vid.fps || !el.duration) return;

    const _showBoxesEl = document.getElementById('vpShowBoxesToggle');
    const showBoxes = _showBoxesEl ? _showBoxesEl.checked : true;
    if (!showBoxes) return;

    const extractFps = vid.extract_fps || vid.fps;
    const currentFrame = el.currentTime * extractFps;

    const keys = Object.keys(frameAnns).map(Number).sort((a,b)=>a-b);
    if (!keys.length) return;

    let k1 = keys[0], k2 = keys[0];
    for (let i=0; i<keys.length; i++) {
      if (keys[i] <= currentFrame) k1 = keys[i];
      if (keys[i] >= currentFrame) { k2 = keys[i]; break; }
    }
    if (k1 === k2) k2 = k1;

    let t = 0;
    if (k1 !== k2) t = (currentFrame - k1) / (k2 - k1);

    const isInterp = interpCb && interpCb.checked;
    const anns1 = frameAnns[String(k1)] || [];
    const anns2 = isInterp ? (frameAnns[String(k2)] || []) : anns1;
    const _vw = el.videoWidth, _vh = el.videoHeight;

    anns1.forEach(a => {
      const ca = _annBboxToVideo(a, _vw, _vh);
      let b;
      if (isInterp) {
        const match = anns2.find(x => x.animal_id === a.animal_id || x.ann_id === a.ann_id);
        if (match) {
          const cm = _annBboxToVideo(match, _vw, _vh);
          b = {
            x: ca.x + (cm.x - ca.x) * t,
            y: ca.y + (cm.y - ca.y) * t,
            w: ca.w + (cm.w - ca.w) * t,
            h: ca.h + (cm.h - ca.h) * t,
            animal_id: a.animal_id, behavior: a.behavior,
          };
        } else {
          b = { ...ca, animal_id: a.animal_id, behavior: a.behavior };
        }
      } else {
        b = { ...ca, animal_id: a.animal_id, behavior: a.behavior };
      }
      const BEH_COLORS = {eat:'#34c759',walk:'#0a84ff',lie:'#8e8e93',drink:'#5ac8fa',stand:'#ffcc00',active:'#ff3b30'};
      ctx.strokeStyle = b.behavior ? (BEH_COLORS[b.behavior] || '#0a84ff') : '#ff9500';
      ctx.lineWidth = 2;
      ctx.strokeRect(offX + b.x * drawW, offY + b.y * drawH, b.w * drawW, b.h * drawH);
      if (b.animal_id != null) {
        ctx.fillStyle = 'rgba(0,0,0,0.7)';
        ctx.fillRect(offX + b.x * drawW, offY + b.y * drawH - 18, 60, 16);
        ctx.fillStyle = '#fff'; ctx.font = '11px sans-serif';
        ctx.fillText('#' + b.animal_id, offX + b.x * drawW + 4, offY + b.y * drawH - 6);
      }
    });
  }

  // [FIX:v1341-frontend] toggle showBoxes
  window.vpToggleBoxes = () => draw();

  el.addEventListener('timeupdate', () => {
    if (!el.duration) return;
    seekBar.value = (el.currentTime / el.duration) * 100;
    const m = Math.floor(el.currentTime / 60), s = Math.floor(el.currentTime % 60);
    const dm = Math.floor(el.duration / 60), ds = Math.floor(el.duration % 60);
    timeEl.textContent = `${m}:${s.toString().padStart(2,'0')} / ${dm}:${ds.toString().padStart(2,'0')}`;
    draw();
  });

  el.onclick = () => { el.paused ? el.play() : el.pause(); };
  el.addEventListener('play', () => playBtn.textContent = '⏸');
  el.addEventListener('pause', () => playBtn.textContent = '▶');

  seekBar.oninput = () => { if(el.duration) el.currentTime = (seekBar.value/100) * el.duration; };

  window.vpTogglePlay = () => { el.paused ? el.play() : el.pause(); };
  window.vpStep = (dir) => {
    const vid = _vidInfo || {};
    if (!vid.fps) return;
    el.pause();
    el.currentTime += dir / vid.fps;
  };
  window.vpSetSpeed = (e) => { el.playbackRate = parseFloat(e.target.value); };
  window.vpToggleInterp = () => draw();

  await awaitVidInfo();
  el.play().catch(()=>{});
}

function closeVideoPlayer() {
  const el = document.getElementById('videoPlayerEl');
  if (el) { el.pause(); el.removeAttribute('src'); el.load(); }
  closeModal('videoPlayerModal');
}

async function playerOpenVideo() {
  if (!_playerTrack) return;
  const cur = _playerTrack.frames[_playerTrack.currentIdx];
  if (!cur || !cur.video_id) { setStatus('У кадра нет video_id'); return; }
  closeTrackPlayer();
  await openVideoPlayer(cur.video_id);
}

async function openVideoPlayerFromCurrent() {
  let videoId = null;
  if (currentImageId) {
    const meta = allImages.find(i => i.id === currentImageId);
    if (meta && meta.video_id) videoId = meta.video_id;
  }
  if (!videoId && currentProjectId) {
    try {
      const vids = await api(`/api/projects/${currentProjectId}/videos`);
      if (vids.length > 0) videoId = vids[0].id;
    } catch(e) {}
  }
  if (!videoId) { setStatus(t('video.noVideoFound')); return; }
  await openVideoPlayer(videoId);
}

window.openVideoPlayer = openVideoPlayer;
window.closeVideoPlayer = closeVideoPlayer;
window.playerOpenVideo = playerOpenVideo;
window.openVideoPlayerFromCurrent = openVideoPlayerFromCurrent;


// [STAGE1-C:interpolate-dialog]
async function openInterpolateDialog() {
  if (!currentProjectId || !currentImageId) { setStatus(t('toast.pickProject')); return; }
  const sel = getSelectedIndices();
  if (!sel.length) { setStatus('Сначала выдели рамку'); return; }
  const box = boxes[sel[0]];
  if (box.animal_id == null) { setStatus('У рамки нет animal_id'); return; }
  const annId = (currentImageId && window._currentAnnIds) ? window._currentAnnIds[sel[0]] : null;
  if (!annId) { setStatus('Нет ann_id — выдели рамку заново'); return; }
  const tid = await showPrompt('ID конечной рамки (to_ann_id)', { okText: 'Интерполировать' });
  if (!tid) return;
  const toId = parseInt(tid, 10);
  if (isNaN(toId)) return;
  try {
    const r = await api(`/api/projects/${currentProjectId}/interpolate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ animal_id: box.animal_id, from_ann_id: annId, to_ann_id: toId }),
    });
    setStatus(`Интерполировано кадров: ${r.interpolated_frames}`);
    haptic('success');
  } catch (e) { setError(String(e.message).slice(0, 160)); }
}
window.openInterpolateDialog = openInterpolateDialog;



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
      if (item.frame_gap > 2) continue; // [FIX] Не рисуем длинные вектора
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
      setStatus(t('attr.vector.status.none', { total: s.total_with_aid }), 5000);
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

// V10.5.0: умное копирование из похожего кадра.
async function _handleSmartCopy() {
  if (!currentImageId) return;

  // V10.5.3: автосохранение, чтобы не потерять несохранённые скелеты
  if (isDirty) {
    try {
      await saveAnnotations();
    } catch (e) {
      setError('Не удалось сохранить перед копированием: ' + String(e.message || e).slice(0, 140));
      haptic('error');
      return;
    }
  }

  // 1. Ищем похожие
  let data;
  try {
    data = await api(`/api/projects/${currentProjectId}/similar/${currentImageId}`);
  } catch (e) {
    setError(t('attr.smartCopy.error') + ': ' + String(e.message).slice(0, 120));
    return;
  }
  const items = (data && data.items) || [];
  if (!items.length) {
    setStatus(t('attr.smartCopy.none'), 3500);
    haptic('warning');
    return;
  }

  // 2. Выбор источника (если >1)
  let sourceId = null;
  let sourceName = '';
  if (items.length === 1) {
    sourceId = items[0].id;
    sourceName = items[0].filename;
  } else {
    const chosen = await _pickSmartCopySource(items);
    if (!chosen) return;
    sourceId = chosen.id;
    sourceName = chosen.filename;
  }

  // 3. Анализ текущего фото
  const hasBoxes = boxes.length > 0;
  const hasSkeletons = boxes.some(b => {
    const k = b.keypoints || [];
    return k.length > 0;
  });

  let mode = null;
  if (!hasBoxes) {
    mode = 'clone_all';
    const ok = await showConfirm(
      t('attr.smartCopy.confirmTitle'),
      t('attr.smartCopy.confirmClone', { name: sourceName }),
      { okText: t('attr.smartCopy.btnClone') }
    );
    if (!ok) return;
  } else if (!hasSkeletons) {
    mode = 'fill_empty';
    const ok = await showConfirm(
      t('attr.smartCopy.confirmTitle'),
      t('attr.smartCopy.confirmFill', { name: sourceName }),
      { okText: t('attr.smartCopy.btnFill') }
    );
    if (!ok) return;
  } else {
    mode = await _showSmartCopyCaseCDialog(sourceName);
    if (!mode) return;
  }

  // 4. Выполняем
  setStatus(t('attr.smartCopy.progress'), 60000);
  try {
    const r = await api(`/api/images/${currentImageId}/smart_copy_from/${sourceId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode }),
    });

    // 5. Обновляем стейт и историю
    await _reloadAllAfterSmartCopy();

    setStatus(t('attr.smartCopy.done', {
      boxes: r.copied_boxes,
      kps: r.copied_kps,
      matched: r.matched
    }), 5000);
    haptic('success');
  } catch (e) {
    setError(t('attr.smartCopy.error') + ': ' + String(e.message).slice(0, 140));
  }
}

async function _reloadAllAfterSmartCopy() {
  // Сначала обновляем аннотации (рамки)
  try {
    State.boxes = await api(`/api/images/${currentImageId}/annotations`);
  } catch (e) {}
  // V10.5.2: keypoints уже внутри boxes
  boxes.forEach(b => { if (!b.keypoints) b.keypoints = []; });
  const selIdx = _targetAnnotationId();
  if (selIdx >= 0 && Array.isArray(boxes[selIdx].keypoints)) {
    keypoints = boxes[selIdx].keypoints.map(p => ({...p}));
  }

  // Отрисовка + история
  renderBoxes();
  pushHistory(); // <--- Ctrl+Z будет работать
  markDirty();
  _refreshAttrBar();
  _updateImageMeta(currentImageId);
  _refreshRowMeta(currentImageId, { flash: true });
}

function _showSmartCopyCaseCDialog(sourceName) {
  return new Promise((resolve) => {
    const titleEl = document.getElementById('dialogTitle');
    const textEl = document.getElementById('dialogText');
    const inputWrap = document.getElementById('dialogInputWrap');
    const cancelBtn = document.getElementById('dialogCancel');
    const okBtn = document.getElementById('dialogOk');
    const actionsRow = okBtn.parentNode;

    titleEl.textContent = t('attr.smartCopy.caseCTitle');
    textEl.innerHTML = t('attr.smartCopy.caseCText', { name: sourceName });
    textEl.style.display = '';
    inputWrap.style.display = 'none';

    cancelBtn.style.display = 'none';
    okBtn.style.display = 'none';

    // Очищаем старое
    actionsRow.innerHTML = '';
    actionsRow.style.display = 'flex';
    actionsRow.style.flexDirection = 'column';
    actionsRow.style.alignItems = 'stretch';
    actionsRow.style.gap = '8px';
    actionsRow.style.width = '100%';

    const mkBtn = (txt, cls, handler) => {
      const b = document.createElement('button');
      b.className = `btn ${cls}`;
      b.textContent = txt;
      b.style.width = '100%';
      b.style.justifyContent = 'center';
      b.onclick = handler;
      return b;
    };

    const btnFill = mkBtn(t('attr.smartCopy.btnFill'), 'btn-secondary', () => finish('fill_empty'));
    const btnReplaceSkel = mkBtn(t('attr.smartCopy.btnReplaceSkel'), 'btn-secondary', () => finish('replace_skeleton'));
    const btnReplaceAll = mkBtn(t('attr.smartCopy.btnReplaceAll'), 'btn-primary', () => finish('replace_all'));
    const btnCancel = mkBtn(t('common.cancel'), 'btn-ghost', () => finish(null));

    actionsRow.appendChild(btnReplaceAll);
    actionsRow.appendChild(btnReplaceSkel);
    actionsRow.appendChild(btnFill);
    actionsRow.appendChild(btnCancel);

    const finish = (result) => {
      actionsRow.innerHTML = '';
      actionsRow.style.flexDirection = '';
      actionsRow.appendChild(cancelBtn);
      actionsRow.appendChild(okBtn);
      cancelBtn.style.display = '';
      okBtn.style.display = '';
      _closeDialog(true);
      resolve(result);
    };

    openModal('dialogModal');
  });
}


function _pickSmartCopySource(items) {
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
      meta.textContent = `Hamming ${it.distance} · рамок: ${it.annotation_count || 0}`;
      info.appendChild(meta);
      row.appendChild(info);
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'smart_copy_pick';
      radio.style.cssText = 'flex:none;margin-right:6px;';
      if (idx === 0) radio.checked = true;
      row.appendChild(radio);
      previews.push({ it, radio });
      row.onclick = () => { previews.forEach(p => p.radio.checked = false); radio.checked = true; };
      wrap.appendChild(row);
    });
    _openCustomDialog({
      title: t('attr.smartCopy.pickTitle'),
      bodyText: t('attr.smartCopy.pickHint'),
      selectorEl: wrap,
      okText: t('attr.smartCopy.btnNext'),
    }).then((res) => {
      if (!res) { resolve(null); return; }
      const chosen = previews.find(p => p.radio.checked);
      resolve(chosen ? chosen.it : null);
    });
  });
}

async function _deleteSkeleton() {
  const idx = _targetAnnotationId();
  if (idx < 0) {
    setStatus(t('attr.deleteSkeleton.selectFirst') || 'Сначала выдели рамку', 2500);
    return;
  }
  // V10.5.3: запоминаем для отката
  const prevKps = Array.isArray(boxes[idx].keypoints) ? boxes[idx].keypoints.map(p => ({...p})) : [];
  if (!prevKps.length) {
    setStatus(t('attr.deleteSkeleton.empty') || 'У этой рамки нет скелета', 2000);
    return;
  }
  boxes[idx].keypoints = [];
  keypoints = [];
  // V10.5.3: синхронная перерисовка (не через rAF), чтобы сразу скрыть
  renderSkeleton();
  pushHistory();
  markDirty();
  try {
    await saveAnnotations();
    setStatus(t('attr.deleteSkeleton.done') || 'Скелет удалён', 2000);
    haptic('success');
  } catch (e) {
    // V10.5.3: откат если сохранение упало
    boxes[idx].keypoints = prevKps;
    keypoints = prevKps.map(p => ({...p}));
    renderSkeleton();
    setError('Не удалось сохранить удаление: ' + String(e.message).slice(0, 100));
    haptic('error');
  }
}

function _installAttrBar() {
  const bar = document.getElementById('attrBar');
  if (!bar || bar.__bound) return;
  bar.__bound = true;

  // [PATCH:STAGE3_1:validate-button]
  (function _addValidateButton() {
    const actions = bar.querySelector('.attr-actions');
    if (!actions) return;
    if (document.getElementById('attrValidateBehBtn')) return;
    const vb = document.createElement('button');
    vb.type = 'button';
    vb.className = 'attr-btn attr-btn-wide';
    vb.id = 'attrValidateBehBtn';
    vb.title = 'Валидировать поведение (Ground Truth)';
    vb.textContent = '✅ валидация';
    vb.addEventListener('click', function () {
      if (typeof window._validateBehavior === 'function') window._validateBehavior();
    });
    actions.appendChild(vb);
  })();
  // [/PATCH:STAGE3_1:validate-button]

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
  const delSkelBtn = document.getElementById('attrDeleteSkelBtn');
  if (delSkelBtn) delSkelBtn.addEventListener('click', () => _deleteSkeleton());
  const smartCopyBtn = document.getElementById('attrSmartCopyBtn');
  if (smartCopyBtn) smartCopyBtn.addEventListener('click', () => _handleSmartCopy());
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

/* ==== Upload / import ==== */
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

  // [V13.1.0:import-poll]
  const poll = setInterval(async () => {
    try {
      const s = await api(`/api/import/status?project_id=${currentProjectId}`);
      if (s.stage === 'idle') { clearInterval(poll); return; }
      const pct = s.total > 0 ? Math.round(s.done / s.total * 100) : 0;
      if (progressPhase) progressPhase.textContent = `${t('import.' + s.stage) || s.stage}... (${s.done}/${s.total})`;
      if (progressFill) progressFill.style.width = pct + '%';
      if (progressText) progressText.textContent = pct + '%';
    } catch(e){}
  }, 500);
  
  // V10.4.1: AbortController + кооперативная отмена на сервере.
  const ac = new AbortController();
  startOperation('import', async () => {
    try {
      await fetch('/api/import/cancel', {
        method: 'POST',
        headers: { 'X-Requested-With': 'DatasetBuilder' },
      });
    } catch (e) {}
    try { ac.abort(); } catch (e) {}
  });
  try {
    const res = await fetch(`/api/projects/${currentProjectId}/import`, {
      method: 'POST', body: fd,
      headers: { 'X-Requested-With': 'DatasetBuilder' },
      signal: ac.signal,
    });
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
    if (e && e.name === 'AbortError') {
      // V10.4.1: пользователь нажал «Отменить» — это не ошибка.
      if (progressWrap) progressWrap.style.display = 'none';
      status.textContent = 'Импорт отменён';
      status.style.color = 'var(--warning)';
      result.style.display = 'block';
      result.innerHTML = '<div>Импорт отменён пользователем. Уже загруженные файлы остались в проекте.</div>';
      try { await loadImages(); } catch (er) {}
    } else {
      if (progressWrap) progressWrap.style.display = 'none';
      status.textContent = 'Ошибка сети';
      status.style.color = 'var(--danger)';
      result.style.display = 'block';
      result.textContent = String(e.message || e);
    }
  } finally {
    clearInterval(poll);
    endOperation();
  }
  closeBtn.style.display = 'inline-flex';
}
function closeImportModal() { closeModal('importModal'); }

/* ==== External imports ==== */
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

/* ==== Select / delete / rename ==== */
let _selectToken = 0;
async function selectImage(id, { autoAutolabel = false, skipDirtyCheck = false } = {}) {
  if (viewMode !== 'main') return;
  // V7.9.3: клик по уже активному изображению ничего не делает.
  // Иначе пользователь получает перезагрузку файла и запрос
  // «перейти без сохранения?», хотя никуда не уходит.
  if (id === currentImageId && !autoAutolabel) return;
  if (!skipDirtyCheck && isDirty && currentImageId && currentImageId !== id) {
    // V11.0.0: Seamless UX. Silent auto-save instead of blocking confirm.
    try {
      if (skeletonMode) _syncKeypointsToBox();
      await saveAnnotations({ silent: true });
    } catch (e) {
      console.warn("Auto-save before switch failed:", e);
      const ok = await showConfirm(
        t('confirm.unsaved.title'),
        t('confirm.unsaved.text') + ' (Автосохранение не удалось)',
        { okText: t('confirm.unsaved.ok'), danger: true }
      );
      if (!ok) return;
    }
  }
  const token = ++_selectToken;
  State.currentImageId = id;
  State.selectedIndex = -1; multiSelected.clear(); dragState = null;
  showCanvas(true);
  updateDelBoxBtn();
  scrollListToImage(id);
  renderImageList();

  const img = document.getElementById('image');
  // [FIX:MISSING-IMG] Удаляем заглушку, если она была от предыдущей картинки
  if (img.parentNode) {
    img.parentNode.querySelectorAll('.missing-image-placeholder').forEach(el => el.remove());
  }
  img.style.display = '';
  if (img.__selectAbort) { try { img.__selectAbort.abort(); } catch (_) {} }
  const controller = new AbortController();
  img.__selectAbort = controller;

  img.style.transition = 'none';
  img.style.opacity = '0';
  const imgLoadPromise = new Promise((resolve) => {
    const onDone = () => resolve();
    img.onload = onDone;
    // V10.5.1: placeholder вместо битой иконки.
    img.onerror = () => {
      setError(t('error.fileMissing') || 'Файл изображения отсутствует на диске', 5000);
      img.onerror = null;
      img.style.display = 'none';
      const ph = document.createElement('div');
      ph.className = 'missing-image-placeholder';
      ph.textContent = '❌ Файл отсутствует';
      ph.style.width = '640px';
      ph.style.height = '640px';
      ph.style.display = 'flex';
      ph.style.alignItems = 'center';
      ph.style.justifyContent = 'center';
      ph.style.background = 'var(--bg-hover)';
      ph.style.color = 'var(--text-secondary)';
      ph.style.fontSize = '1.25rem';
      ph.style.fontWeight = '600';
      img.parentNode.appendChild(ph);
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
  img.style.transition = 'none'; // Убираем старый transition
  img.classList.remove('img-fade-in');
  void img.offsetWidth; // Сброс анимации
  img.classList.add('img-fade-in');
  img.style.opacity = '1';

  State.boxes = anns;
  window._currentAnnIds = (anns || []).map(a => a.id || null);  // [STAGE1-C:interpolate-ui] for interpolation
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
  // V11.4.0: _kpByIndex полностью удален. Скелеты берутся из boxes[].keypoints.
  if (skeletonMode) {
    await loadKeypointSchema(currentProjectId);
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
    if (State.currentImageId === id) {
      currentImageId = null; State.boxes = []; State.selectedIndex = -1; multiSelected.clear();
      document.getElementById('image').removeAttribute('src');
      _clearDebugBoxes();
      renderBoxes(); showCanvas(false); resetHistory(); markClean(); updateDelBoxBtn();
    }
    await loadImages();
    await renderTagChips();
    setStatus(t('toast.imageDeleted'));
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}

/* ==== Hard / freeze ==== */
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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

/* ==== Batch ==== */
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
      State.currentImageId = null; State.boxes = []; State.selectedIndex = -1; multiSelected.clear();
      document.getElementById('image').removeAttribute('src');
      _clearDebugBoxes();
      renderBoxes(); showCanvas(false); resetHistory(); markClean(); updateDelBoxBtn();
    }
    selectedForDelete.clear();
    _pushListUndo({ type: 'delete', ids: _undoIds });
    await loadImages();
    await renderTagChips();
    setStatus(t('toast.toTrashN', { n: r.deleted }));
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}

/* ==== Preview / Stats / Validate ==== */
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
    const [s, skel] = await Promise.all([
      api(`/api/projects/${currentProjectId}/stats`),
      api(`/api/projects/${currentProjectId}/skeletons_count`).catch(() => ({ count: 0 })),
    ]);
    const skelCnt = (skel && typeof skel.count === 'number') ? skel.count : 0;
    const skelBlock = document.getElementById('statSkeletons');
    if (skelBlock) skelBlock.textContent = skelCnt;
    const skelCard = document.getElementById('statSkeletonsCard');
    if (skelCard) skelCard.style.display = '';
    document.getElementById('statTotal').textContent = s.total_images;
    document.getElementById('statAnnotated').textContent = s.annotated_images;
    document.getElementById('statUnannotated').textContent = s.unannotated_images;
    document.getElementById('statBoxes').textContent = s.total_boxes;

    // [V13.1.0:stats-ui]
    const behList = document.getElementById('statsBehList');
    if (behList && s.behavior_dist) {
      behList.innerHTML = Object.entries(s.behavior_dist).map(([b, c]) =>
        `<span class="tag-chip" style="pointer-events:none;background:var(--bg-hover);">${t('behavior.'+b) || b}: <b>${c}</b></span>`
      ).join('');
    }
    const trkList = document.getElementById('statsTracksList');
    if (trkList && s.track_stats) {
      trkList.innerHTML = `
        <div class="stat-card" style="flex:1;"><div class="stat-value">${s.track_stats.total}</div><div class="stat-label">Всего</div></div>
        <div class="stat-card" style="flex:1;"><div class="stat-value" style="color:var(--success)">${s.track_stats.long}</div><div class="stat-label" data-i18n="stats.tracks.long">Полных</div></div>
        <div class="stat-card" style="flex:1;"><div class="stat-value" style="color:var(--warning)">${s.track_stats.single}</div><div class="stat-label" data-i18n="stats.tracks.single">Одиночных</div></div>
      `;
    }
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
    html += `<div class="stat-card filter-card" data-filter-type="small_box" style="cursor:pointer;"><div class="stat-value" style="color:var(--box-low)">${bt.small_box || 0}</div><div class="stat-label">${t('validate.small')}</div></div>`;
    html += `<div class="stat-card filter-card" data-filter-type="overlap" style="cursor:pointer;"><div class="stat-value" style="color:var(--warning)">${bt.overlap || 0}</div><div class="stat-label">${t('validate.overlap')}</div></div>`;
    html += `<div class="stat-card filter-card" data-filter-type="out_of_bounds" style="cursor:pointer;"><div class="stat-value" style="color:var(--danger)">${bt.out_of_bounds || 0}</div><div class="stat-label">${t('validate.outOfBounds')}</div></div>`;
    html += `</div>`;
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card filter-card" data-filter-type="nested_box" style="cursor:pointer;"><div class="stat-value" style="color:#ff375f">${bt.nested_box || 0}</div><div class="stat-label">${t('validate.nested')}</div></div>`;
    html += `<div class="stat-card filter-card" data-filter-type="aspect" style="cursor:pointer;"><div class="stat-value">${bt.aspect || 0}</div><div class="stat-label">${t('validate.aspect')}</div></div>`;
    html += `<div class="stat-card filter-card" data-filter-type="unannotated" style="cursor:pointer;"><div class="stat-value">${r.unannotated.length}</div><div class="stat-label">${t('validate.unannotated')}</div></div>`;
    html += `</div>`;
    // [PATCH:VALIDATOR_CARDS]
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card filter-card" data-filter-type="blurry" style="cursor:pointer;"><div class="stat-value" style="color:var(--warning)">${bt.blurry || 0}</div><div class="stat-label">Блюр</div></div>`;
    html += `<div class="stat-card filter-card" data-filter-type="occluded_keypoint" style="cursor:pointer;"><div class="stat-value" style="color:#ff375f">${bt.occluded_keypoint || 0}</div><div class="stat-label">Окклюзия</div></div>`;
    html += `</div>`;
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card filter-card" data-filter-type="all" style="grid-column: 1 / -1; cursor:pointer;"><div class="stat-value" style="color:${r.total_issues ? 'var(--danger)' : 'var(--success)'}">${r.total_issues}</div><div class="stat-label">${t('validate.totalIssues')}</div></div>`; // [PATCH:VALIDATOR_TOTAL_CLICKABLE]
    html += `</div>`;
    if (!r.total_issues && !r.unannotated.length) {
      html += `<p style="color:var(--success);font-size:0.875rem;text-align:center;padding:20px 0;">${t('validate.ok')}</p>`;
    } else {
      if (r.issues.length) {
        html += `<div class="stats-section-title">${t('validate.problems')}</div>`;
        // [PATCH:VALIDATOR_TYPENAME]
        const typeName = {
          small_box: t('validate.small'),
          overlap: t('validate.overlap'),
          out_of_bounds: t('validate.outOfBounds'),
          aspect: t('validate.aspect'),
          nested_box: t('validate.nested'),
          blurry: 'Блюр',
          occluded_keypoint: 'Окклюзия'
        };
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
          html += `<div class="validator-issue unannotated" data-image-id="${it.id}" role="button" tabindex="0">`;
          html += `<span class="vi-type">${t('validate.empty')}</span>`;
          html += `<span class="vi-name">${escapeHtml(it.filename)}</span>`;
          html += `</div>`;
        });
      }
    }
    body.innerHTML = html;
    body.querySelectorAll('.filter-card').forEach(card => {
        card.addEventListener('click', () => {
            const type = card.dataset.filterType;
            const isActive = card.classList.contains('active');
            body.querySelectorAll('.filter-card').forEach(c => c.classList.remove('active'));
            body.querySelectorAll('.validator-issue').forEach(el => {
                // [PATCH:VALIDATOR_RESET_FILTER]
                if (isActive || type === 'all' || !type || el.classList.contains(type)) {
                    el.style.display = '';
                } else {
                    el.style.display = 'none';
                }
            });
            if (!isActive && type && type !== 'all') card.classList.add('active');
        });
    });
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

/* ==== Similar ==== */

function toggleSkeletonMode() {
  setSkeletonMode(!skeletonMode);
}

function setSkeletonMode(on) {
  skeletonMode = !!on;
  window.skeletonMode = skeletonMode;  // V11.8.2: sync for canvas.js
  const btn = document.getElementById('skeletonModeBtn');
  if (btn) {
    btn.classList.toggle('active', skeletonMode);
    btn.setAttribute('aria-pressed', skeletonMode ? 'true' : 'false');
  }
  if (skeletonMode) {
    loadKeypointSchema(currentProjectId).then(() => renderSkeleton());
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
  const lbl = meta ? (window.getLang() === 'en' ? meta.label_en : meta.label_ru) : kp.name;
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
    
      // V11.9.1: Stagger animation
      dot.classList.add('skeleton-pop');
      dot.style.animationDelay = `${i * 25}ms`;
      if (isSelected) dot.dataset.kpIdx = String(i);
    dot.style.left = (p.x * 640) + 'px';
    dot.style.top = (p.y * 640) + 'px';
    const meta = _schemaName(p.name);
    const lbl = meta ? (window.getLang() === 'en' ? meta.label_en : meta.label_ru) : p.name;
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
  const layer = document.getElementById('skeletonLayer');
  if (!layer) return;
  // V10.5.3: всегда очищаем, чтобы не оставалось призраков
  layer.innerHTML = '';
  _clearSkeletonHint();
  if (!skeletonMode || !keypointSchema) return;

  const selIdx = _targetAnnotationId();

  if (selIdx >= 0) {
    keypoints = (Array.isArray(boxes[selIdx].keypoints)
                 ? boxes[selIdx].keypoints.map(p => ({...p}))
                 : []);
  } else {
    keypoints = [];
  }

  // Рисуем только из boxes (никаких _kpByIndex)
  boxes.forEach((b, bi) => {
    let kps = null;
    if (bi === selIdx) {
      kps = keypoints;
    } else if (Array.isArray(b.keypoints) && b.keypoints.length) {
      kps = b.keypoints;
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
    const lbl = meta ? (window.getLang() === 'en' ? meta.label_en : meta.label_ru) : next;
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
    const idx = _targetAnnotationId();
    if (idx >= 0 && boxes[idx].keypoints) keypoints = boxes[idx].keypoints.map(p => ({...p}));
    else keypoints = [];
  } catch (e) {
    console.warn('keypoints_by_index failed:', e);
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
  const lbl = meta ? (window.getLang() === 'en' ? meta.label_en : meta.label_ru) : next;
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
  const lbl = meta ? (window.getLang() === 'en' ? meta.label_en : meta.label_ru) : removed.name;
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
    behavior: null, animal_id: null, keypoints: [],
  });
  State.selectedIndex = boxes.length - 1;
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

/* ==== Active learning ==== */
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

/* ==== Metrics ==== */
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
  if (runFolder && typeof runFolder === 'object') runFolder = null; // V11.8.3: ignore event
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

/* ==== Storage ==== */
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
    setError(t('error.prefix') + String(e.message || e).slice(0, 180));
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

/* ==== File operations ==== */
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
    setError(t('error.prefix') + String(e.message).slice(0, 160));
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
    setError(t('error.prefix') + String(e.message).slice(0, 180));
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

/* ==== FFmpeg ==== */
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
    setError(t('error.prefix') + String(e.message).slice(0, 160));
  }
}

/* ==== V7.7.0: извлечение кадров из видео ==== */
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

/* ==== Version history (moved to changelog.js) ==== */

function openGuide() {
  openModal('guideModal');
}
function closeGuide() {
  closeModal('guideModal');
}

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

/* ==== Shortcuts / Settings ==== */
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
  _updateDownloadSelects();

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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}
async function setModelMode(use_single) {
  try {
    await api('/api/settings/model_mode', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_single }),
    });
    await loadModelsIntoUI();
    haptic('selection');
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}

// [FIX:train-ui-v2] Синхронизация полей формы обучения
function _updateTrainSelects() {
  const famEl = document.getElementById('trainFamily');
  const baseModelEl = document.getElementById('trainBaseModel');
  const pretrainEl = document.getElementById('trainPretrain');
  const nameInput = document.getElementById('trainModelName');
  if (!famEl || !baseModelEl || !pretrainEl) return;

  const fam = famEl.value;
  const isActive = fam === '__active__';
  const task = window.getTrainTask();
  const famName = fam === 'v11' ? 'YOLO11' : 'YOLOv8';

  // 1. Блокируем размер и предобучение, если выбрано дообучение
  const setDisabled = (el, disabled) => {
    el.disabled = disabled;
    const wrap = el.closest('.custom-select');
    if (wrap) {
      wrap.style.opacity = disabled ? '0.5' : '1';
      wrap.style.pointerEvents = disabled ? 'none' : '';
    }
  };
  setDisabled(baseModelEl, isActive);
  setDisabled(pretrainEl, isActive);

  // 2. Обновляем текст размеров (YOLOv8n -> YOLO11n)
  Array.from(baseModelEl.options).forEach(opt => {
    if (opt.value === 'n') opt.textContent = `${famName}n (nano — быстрая)`;
    if (opt.value === 's') opt.textContent = `${famName}s (small)`;
    if (opt.value === 'm') opt.textContent = `${famName}m (medium)`;
  });

  // 3. Прячем OIV7 для YOLO11 и Pose (вызывая ре-рендер кастомного селекта)
  const oiv7Opt = pretrainEl.querySelector('option[value="oiv7"]');
  if (fam === 'v11' || task === 'pose') {
    if (oiv7Opt) {
      if (pretrainEl.value === 'oiv7') pretrainEl.value = 'coco';
      oiv7Opt.remove();
    }
  } else {
    if (!pretrainEl.querySelector('option[value="oiv7"]')) {
      const opt = document.createElement('option');
      opt.value = 'oiv7';
      opt.textContent = 'OpenImages V7 (601 класс, есть Pig) — рекомендовано';
      pretrainEl.insertBefore(opt, pretrainEl.firstChild);
      pretrainEl.value = 'oiv7';
    }
  }

  // 4. Меняем подсказку в имени модели для Pose
  if (nameInput) {
    nameInput.placeholder = task === 'pose' ? 'например, pig_v1_pose' : 'например, pig_v1';
  }
}
window._updateTrainSelects = _updateTrainSelects;window._updateTrainSelects = _updateTrainSelects;

function _updateDownloadSelects() {
  const famEl = document.getElementById('downloadFamily');
  const tskEl = document.getElementById('downloadTask');
  const preEl = document.getElementById('downloadPretrain');
  if (!famEl || !tskEl || !preEl) return;
  const isV11Detect = (famEl.value === 'v11' && tskEl.value === 'detect');
  const oiv7Opt = preEl.querySelector('option[value="oiv7"]');
  
  if (isV11Detect) {
    if (oiv7Opt) {
      oiv7Opt.remove(); // Удаляем из DOM, чтобы кастомный селект перестроился
      if (preEl.value === 'oiv7') {
        preEl.value = 'coco';
        preEl.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  } else {
    if (!oiv7Opt) {
      const newOpt = document.createElement('option');
      newOpt.value = 'oiv7';
      newOpt.textContent = 'OpenImages V7';
      preEl.insertBefore(newOpt, preEl.firstChild);
      preEl.value = 'oiv7';
      preEl.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }
}

async function downloadModel() {
  const family = document.getElementById('downloadFamily').value;
  const task = document.getElementById('downloadTask').value;
  let pretrain = document.getElementById('downloadPretrain').value;
  const size = document.getElementById('downloadSize').value;
  try {
    await api('/api/models/download', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ size, pretrain, family, task }),
    });
    const prefix = family === 'v11' ? 'yolo11' : 'yolov8';
    const suffix = task === 'pose' ? '-pose' : (pretrain === 'oiv7' ? '-oiv7' : '');
    setStatus(`<span class="status-spinner" aria-hidden="true"></span>Скачиваем ${prefix}${size}${suffix}.pt…`, 0, null, { html: true });
    subscribeBootstrapEvents();
    haptic('light');
  } catch (e) {
    if (e.status === 409) setStatus('Уже идёт скачивание другой модели');
    else setError(t('error.prefix') + String(e.message).slice(0, 140));
  }
}
async function loadModelsIntoUI() {
  const wrap = document.getElementById('modelsList');
  wrap.innerHTML = '<div style="font-size:0.8125rem;color:var(--text-secondary);padding:8px 4px;">Загрузка…</div>';
  try {
    const r = await api('/api/models');
    const single = r.use_single;
    const singleCb = document.getElementById('useSingleModelToggle');
    if (singleCb) singleCb.checked = single;

    const models = r.models.map(m => ({
      ...m,
      kind: (m.name.toLowerCase().endsWith('-pose.pt') || m.name.toLowerCase().endsWith('_pose.pt') ||
             m.name.toLowerCase().endsWith('-pose.onnx') || m.name.toLowerCase().endsWith('_pose.onnx')) ? 'pose' : 'detect'
    }));
    let compat = {};
    if (currentProjectMeta && currentProjectMeta.object_class) {
      try {
        compat = await api('/api/models/compatibility?object_class=' + encodeURIComponent(currentProjectMeta.object_class));
      } catch (e) { compat = {}; }
    }
    wrap.innerHTML = '';
    if (!models.length) {
      wrap.innerHTML = '<div style="font-size:0.8125rem;color:var(--text-secondary);padding:8px 4px;">Моделей нет.</div>';
      return;
    }

    const renderSec = (title, list, activeName) => {
      const sec = document.createElement('div');
      sec.className = 'models-section';
      if (title) sec.innerHTML = `<div class="models-section-title">${title}</div>`;
      if (!list.length) {
        const e = document.createElement('div'); e.className = 'models-section-empty'; e.textContent = t('settings.models.empty');
        sec.appendChild(e);
        if (title === t('settings.models.pose')) {
          const dlBtn = document.createElement('button');
          dlBtn.className = 'btn btn-ghost btn-sm';
          dlBtn.style.marginTop = '8px';
          dlBtn.textContent = t('settings.models.download.pose');
          dlBtn.onclick = () => {
            const fam = document.getElementById('downloadFamily');
            const tsk = document.getElementById('downloadTask');
            if (fam) fam.value = 'v11';
            if (tsk) tsk.value = 'pose';
            window.downloadModel();
          };
          sec.appendChild(dlBtn);
        }
        return sec;
      }
      list.forEach(m => {
        const row = document.createElement('div');
        row.className = 'model-row' + (m.name === activeName ? ' active' : '');
        row.dataset.modelName = m.name;
        row.setAttribute('role', 'radio');
        row.setAttribute('aria-checked', m.name === activeName ? 'true' : 'false');
        row.setAttribute('tabindex', '0');
        row.onclick = async (ev) => {
          if (ev.target.closest('.model-actions-wrap')) return;
          if (m.name === activeName) return;
          await activateModel(m.name, m.kind);
        };
        row.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); row.click(); }
        });

        const radio = document.createElement('input');
        radio.type = 'radio'; radio.className = 'model-radio';
        radio.name = 'active_model_radio_' + m.kind;
        radio.checked = (m.name === activeName);
        radio.onclick = (ev) => { ev.preventDefault(); };
        row.appendChild(radio);

        const name = document.createElement('span');
        name.className = 'model-name'; name.textContent = m.name;
        row.appendChild(name);

        const ci = compat[m.name];
        if (ci && ci.compatible === false && currentProjectMeta && currentProjectMeta.object_class) {
          const warn = document.createElement('span');
          warn.className = 'model-warn';
          warn.dataset.tooltip = `Не знает класс «${currentProjectMeta.object_class}». Авторазметка работать не будет.`;
          warn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
          row.appendChild(warn);
          row.classList.add('model-incompatible');
        }

        const meta = document.createElement('span');
        meta.className = 'model-meta';
        meta.textContent = fmtSize(m.size) + ' · ' + m.created_at.replace('T', ' ').slice(0, 16);
        row.appendChild(meta);

        // Выпадающее меню (используем класс sort-menu, как у экспорта)
        const actionsWrap = document.createElement('div');
        actionsWrap.className = 'model-actions-wrap';
        actionsWrap.style.position = 'relative';

        const actionsBtn = document.createElement('button');
        actionsBtn.className = 'model-actions-btn';
        actionsBtn.style.cssText = 'width:26px;height:26px;display:flex;align-items:center;justify-content:center;border-radius:8px;background:transparent;border:none;color:var(--text-secondary);cursor:pointer;';
        actionsBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>';

        actionsBtn.onclick = (ev) => {
            ev.stopPropagation();
            closeAllPopovers(null);
            const menu = document.createElement('div');
            menu.className = 'sort-menu model-actions-menu open';
            menu.style.position = 'fixed';
            menu.style.zIndex = '999999';
            menu.style.minWidth = '180px';

            const mkBtn = (svg, text, onClick, isDanger) => {
                const b = document.createElement('button');
                b.style.color = isDanger ? 'var(--danger)' : 'var(--text-primary)';
                b.innerHTML = svg + ' <span>' + text + '</span>';
                b.onclick = (e) => { e.stopPropagation(); menu.remove(); onClick(); };
                return b;
            };

            menu.appendChild(mkBtn(
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>',
                t('model.menu.rename'), () => renameModel(m.name)
            ));
            menu.appendChild(mkBtn(
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
                t('model.menu.onnx'), () => window.exportModelOnnx(m.name)
            ));

            menu.appendChild(mkBtn(
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
                'Скачать Edge-пакет', () => window.downloadEdgePackage(m.name)
            ));

            menu.appendChild(mkBtn(
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
                t('model.menu.reveal'), () => {
                    api('/api/models/' + encodeURIComponent(m.name) + '/reveal', { method: 'POST' }).catch(e => setError(e.message));
                }
            ));
            menu.appendChild(mkBtn(
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>',
                t('model.menu.delete'), () => deleteModel(m.name), true
            ));

            document.body.appendChild(menu);
            const rect = actionsBtn.getBoundingClientRect();
            menu.style.top = (rect.bottom + 6) + 'px';
            menu.style.right = (window.innerWidth - rect.right) + 'px';

            setTimeout(() => {
                const closeHandler = (e) => {
                    if (!menu.contains(e.target)) {
                        menu.remove();
                        document.removeEventListener('click', closeHandler);
                    }
                };
                document.addEventListener('click', closeHandler);
            }, 10);
        };

        actionsWrap.appendChild(actionsBtn);
        row.appendChild(actionsWrap);
        sec.appendChild(row);
      });
      return sec;
    };
    if (single) {
      wrap.appendChild(renderSec(null, models, r.active));
    } else {
      wrap.appendChild(renderSec(t('settings.models.detect'), models.filter(m => m.kind === 'detect'), r.active_detect));
      wrap.appendChild(renderSec(t('settings.models.pose'), models.filter(m => m.kind === 'pose'), r.active_pose));
    }
  } catch (e) {
    wrap.innerHTML = '<div style="font-size:0.8125rem;color:var(--danger);padding:8px 4px;">Ошибка: ' + escapeHtml(e.message) + '</div>';
  }
}

async function activateModel(name, kind = 'auto') {
  try {
    await api('/api/models/activate', { method: 'POST', body: new URLSearchParams({ name, kind }) });
    await loadModelsIntoUI();
    invalidateObjectClasses();
    setStatus(t('toast.modelActive', { name }));
    haptic('selection');
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}
async function deleteModel(name) {
  const ok = await showConfirm(
    t('confirm.deleteModel.title', { name }),
    t('confirm.deleteModel.text'),
    { okText: t('confirm.deletePerm.ok'), danger: true }
  );
  if (!ok) return;
  haptic('warning');

  // V11.8.3: optimistic delete
  const _row = document.querySelector(`#modelsList .model-row[data-model-name="${name}"]`);
  if (_row) _row.style.opacity = '0.4';

  try {
    await api(`/api/models/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (_row) _row.remove();
    await loadModelsIntoUI();
    setStatus(t('toast.modelDeleted'));
  } catch (e) {
    if (_row) _row.style.opacity = '1';
    if (e.status === 400) setStatus(String(e.message).slice(0, 160));
    else setError(t('error.prefix') + String(e.message).slice(0, 160));
  }
}
async function renameModel(oldName) {
  const stem = oldName.toLowerCase().endsWith('.pt') ? oldName.slice(0, -3) : oldName;
  const newName = await showPrompt(t('prompt.renameModel.title'), {
    text: t('prompt.renameModel.text', { name: oldName }),
    defaultValue: stem,
    hint: t('prompt.renameModel.hint'),
    okText: t('prompt.renameModel.ok'),
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 140)); }
}

/* ==== Training ==== */
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
  _updateTrainSelects(); // [FIX:train-ui-v2]
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
  _updateTrainSelects(); // [FIX:train-ui]
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
  fd.append('task', _trainTask);
  const _famEl = document.getElementById('trainFamily');
  const _famVal = _famEl ? _famEl.value : 'v8';
  fd.append('family', _famVal);
  fd.append('base_model', _famVal === '__active__' ? '__active__' : baseModel);
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 140)); }
}
async function stopTraining() {
  try {
    await api('/api/train/stop', { method: 'POST' });
    // V7.9.3: спиннер показывает, что процесс идёт; ttl=0 — ждём финального статуса.
    setStatus(`<span class="status-spinner" aria-hidden="true"></span>${t('toast.trainStopping')}`, 0, null, { html: true });
    haptic('warning');
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
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

/* ==== Batch autolabel ==== */
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
    // V10.4.1: показываем кнопку "Отменить" пока идёт батч.
    startOperation('batch', () => api('/api/autolabel/batch/stop', { method: 'POST' }));
  } catch (e) {
    if (e.status === 501) setStatus(t('toast.noModelAutolabel'), 8000);
    else setError(t('error.prefix') + String(e.message).slice(0, 140));
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
        endOperation();   // V10.4.1
        loadImages().then(() => {
          if (currentImageId) {
            api(`/api/images/${currentImageId}/annotations`).then(anns => {
              State.boxes = anns;
              renderBoxes({ animateIndices: new Set(boxes.map((_, i) => i)) });
              resetHistory(); markClean();
            }).catch(() => {});
          }
        });
      }
    } catch (e) {}
  };
  es.onerror = () => {
    try { es.close(); } catch (e) {}
    batchEventSource = null; batchRunning = false;
    endOperation();   // V10.4.1
  };
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
  // [PATCH:STAGE1_EXPORT_META]
  const includeMeta = !!(document.getElementById('exportIncludeMeta') || {}).checked;

  closeExportModal();
  const url = `/api/projects/${currentProjectId}/export/${exportFormat}?naming=${encodeURIComponent(naming)}&split=${encodeURIComponent(split)}${includeMeta ? '&include_meta=true' : ''}`;
  const fallback = `${exportFormat}_project_${currentProjectId}.zip`;
  await downloadFile(url, fallback);
}

/* ==== Navigation ==== */
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); return; }
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

/* ==== Boxes ==== */
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
function _boxAriaLabel(b, index) {
  const conf = b.confidence != null ? `уверенность ${b.confidence.toFixed(2)}` : 'ручная';
  const frozen = b.frozen ? ', заморожена' : '';
  const beh = b.behavior ? `, поведение: ${t('behavior.' + b.behavior)}` : '';
  const aid = b.animal_id != null ? `, номер: ${b.animal_id}` : '';
  return `Рамка ${index + 1}: ${b.label || currentObjectClass()}, ${conf}${frozen}${beh}${aid}`;
}
function _createBoxElement(b, i) {
  const div = document.createElement('div');
  div.className = 'box';
  div.setAttribute('role', 'listitem');
  div.setAttribute('tabindex', '0');
  div.setAttribute('aria-label', _boxAriaLabel(b, i));
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

  // V11.6.0: При фокусе с клавиатуры — автоматически выделяем рамку
  div.addEventListener('focus', () => {
    if (window.State.selectedIndex !== i) {
      window.State.selectedIndex = i;
      window.State.multiSelected.clear();
      window.updateSelectionClasses();
    }
  });

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
    const isSel = (i === selectedIndex && selectedIndex !== -1);
    const isMulti = (multiSelected.has(i) && selectedIndex !== -1);
    el.classList.toggle('selected', isSel);
    el.classList.toggle('multi-selected', isMulti);
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
/**
 * V11.2.0: A11y - создание рамки в центре экрана (Shift+N).
 * Позволяет работать без мыши, двигая рамку стрелками.
 */
function createBoxInCenter() {
  if (!currentImageId) return;
  const newBox = {
    x: 0.4, y: 0.4, w: 0.2, h: 0.2,
    label: currentObjectClass(), confidence: null, frozen: false,
    behavior: null, animal_id: null, keypoints: []
  };
  boxes.push(newBox);
  State.selectedIndex = boxes.length - 1;
  multiSelected.clear();
  renderBoxes();
  pushHistory();
  markDirty();
  setStatus('Создана рамка в центре. Двигайте стрелками, Shift+стрелки — ресайз.', 4000);
  haptic('selection');
}

function getSelectedIndices() {
  const set = new Set();
  if (window.State && window.State.multiSelected) {
    window.State.multiSelected.forEach(i => set.add(i));
  }
  const si = window.State ? window.State.selectedIndex : -1;
  if (si >= 0 && si < (window.AppState ? window.AppState.boxes.length : 0)) {
    set.add(si);
  }
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
  State.multiSelected = newMulti;
  if (State.selectedIndex === idx) selectedIndex = -1;
  else if (selectedIndex > idx) selectedIndex -= 1;
  renderBoxes(); pushHistory(); markDirty();
}
function deleteSelectedBox() {
  const indices = getSelectedIndices().filter(i => !boxes[i].frozen);
  if (!indices.length) return;
  hideTooltip();
  for (let i = indices.length - 1; i >= 0; i--) boxes.splice(indices[i], 1);
  const removed = indices.length;
  State.selectedIndex = -1; multiSelected.clear();
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
  State.boxes = []; State.selectedIndex = -1; multiSelected.clear();
  renderBoxes(); pushHistory(); markDirty();
}
async function saveAnnotations(opts = {}) {
  if (!currentImageId) return;
  const savedId = currentImageId;
  try {
    if (skeletonMode) _syncKeypointsToBox();

    const payload = boxes.map(b => {
      let safeKps = [];
      if (Array.isArray(b.keypoints)) {
        safeKps = b.keypoints.filter(k => k && typeof k.x === 'number' && typeof k.y === 'number').map(k => ({
          name: String(k.name || ''), x: Number(k.x), y: Number(k.y), visibility: Number(k.visibility ?? 1)
        }));
      }
      return {
        x: b.x, y: b.y, w: b.w, h: b.h,
        label: b.label, confidence: b.confidence, frozen: b.frozen,
        behavior: b.behavior || null, animal_id: (b.animal_id ?? null),
        keypoints: safeKps
      };
    });

    await api(`/api/images/${savedId}/annotations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    markClean(); // V11.0.0
    _updateImageMeta(savedId); // Сначала обновляем данные
    if (!opts.silent) {
      markSavedWithPulse();
      applyFiltersAndRender();
      _refreshRowMeta(savedId, { flash: true });
      setStatus(t('toast.savedN', { n: boxes.length }));
    }
  } catch (e) {
    setError('Ошибка сохранения: ' + String(e.message).slice(0, 140));
    throw e; // V11.0.0: пробрасываем ошибку для selectImage
  }
}

async function runAutolabel() {
  if (!currentImageId) return;

  // [FIX] Принудительно сохраняем скелеты и разметку перед авторазметкой
  if (isDirty) {
    try {
      if (skeletonMode) _syncKeypointsToBox();
      await saveAnnotations({ silent: true });
    } catch (e) {
      setError('Не удалось автосохранить перед авторазметкой');
      return;
    }
  }


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
      const targetBoxes = (r.saved_boxes || []).map(d => {
        const ob = _prevAutoBoxes.find(x => (Math.abs(x.x - d.x) < 0.1 && Math.abs(x.y - d.y) < 0.1));
        return {
          x: d.x, y: d.y, w: d.w, h: d.h,
          label: d.label || currentObjectClass(),
          confidence: (typeof d.confidence === 'number') ? d.confidence : null,
          frozen: !!d.frozen,
          keypoints: (ob && ob.keypoints) ? ob.keypoints : [],
          behavior: (ob && ob.behavior) ? ob.behavior : null,
          animal_id: (ob && ob.animal_id) ? ob.animal_id : null
        };
      });
      State.boxes = targetBoxes;
      State.selectedIndex = -1; multiSelected.clear();
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
    
        if (r.boxes) {
            r.boxes.forEach(nb => {
                if (!nb.keypoints || !nb.keypoints.length) {
                    const ob = _prevAutoBoxes.find(x => x.id === nb.id || (Math.abs(x.x - nb.x) < 0.1 && Math.abs(x.y - nb.y) < 0.1));
                    if (ob && ob.keypoints) nb.keypoints = ob.keypoints;
                }
            });
        }
        State.boxes = r.boxes || [];
    State.selectedIndex = -1; multiSelected.clear();
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

/* ==== Sort / filter menus ==== */
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
  const cbU = document.getElementById('filterUncertain');

  cbUA.checked = activeFilter === 'unannotated';
  cbLC.checked = activeFilter === 'lowconf';
  cbH.checked = activeFilter === 'hard';
  if (cbD) cbD.checked = activeFilter === 'duplicates';
  if (cbU) cbU.checked = activeFilter === 'uncertain';

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
    if (cbU) cbU.checked = false;
    if (checked) {
      activeFilter = name;
      if (name === 'unannotated') cbUA.checked = true;
      if (name === 'lowconf') cbLC.checked = true;
      if (name === 'hard') cbH.checked = true;
      if (name === 'duplicates' && cbD) cbD.checked = true;
      if (name === 'uncertain' && cbU) cbU.checked = true;
    } else activeFilter = 'none';
    localStorage.setItem('pdb_filter', activeFilter);
    updateFilterBadge();
    await loadImages();
  }

  cbUA.addEventListener('change', () => setFilter('unannotated', cbUA.checked));
  cbLC.addEventListener('change', () => setFilter('lowconf', cbLC.checked));
  cbH.addEventListener('change', () => setFilter('hard', cbH.checked));
  if (cbD) cbD.addEventListener('change', () => setFilter('duplicates', cbD.checked));
  if (cbU) cbU.addEventListener('change', () => setFilter('uncertain', cbU.checked));

  // [FIX:SECTIONS-TOGGLE-V3]
  const _cbGroup = document.getElementById('filterGroupSections');
  if (_cbGroup) {
    try { _cbGroup.checked = localStorage.getItem('pdb_group_sections') === '1'; } catch (e) {}
    _cbGroup.addEventListener('change', () => {
      try { localStorage.setItem('pdb_group_sections', _cbGroup.checked ? '1' : '0'); } catch (e) {}
      applyFiltersAndRender();
    });
  }

  updateFilterBadge();
}

/* ==== Save / undo ==== */
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
// prevBoxes — состояние ДО авторазметки (snapshot() до State.boxes = ...).
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
function resetHistory() {
  const imgId = currentImageId;
  if (!imgId) { history = [snapshot()]; historyIndex = 0; return; }
  let h = _historyMap.get(imgId);
  if (!h || h.length === 0) {
    h = [snapshot()];
    _historyMap.set(imgId, h);
  }
  history = h;
  historyIndex = history.length - 1;
} // V11.8.3
function pushHistory() {
  const snap = snapshot();
  if (historyIndex >= 0 && JSON.stringify(history[historyIndex]) === JSON.stringify(snap)) return;
  if (historyIndex < history.length - 1) history = history.slice(0, historyIndex + 1);
  history.push(snap);
  if (history.length > HISTORY_LIMIT) history.shift();
  historyIndex = history.length - 1;
  if (currentImageId) _historyMap.set(currentImageId, history); // V11.8.3
}
function undo() {
  if (historyIndex <= 0) return;
  historyIndex--;
  State.boxes = JSON.parse(JSON.stringify(history[historyIndex]));
  // V8.5.5: НЕ сбрасываем selectedIndex — иначе keypoints скелета
  // теряют привязку к рамке. Чистим только выходящие за пределы.
  if (selectedIndex >= boxes.length) State.selectedIndex = -1;
  if (multiSelected.size) {
    const _keep = new Set();
    multiSelected.forEach(_i => { if (_i < boxes.length) _keep.add(_i); });
    State.multiSelected = _keep;
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
  State.boxes = JSON.parse(JSON.stringify(history[historyIndex]));
  // V8.5.5: как в undo — не теряем выделение.
  if (selectedIndex >= boxes.length) State.selectedIndex = -1;
  if (multiSelected.size) {
    const _keep = new Set();
    multiSelected.forEach(_i => { if (_i < boxes.length) _keep.add(_i); });
    State.multiSelected = _keep;
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

/* ==== Theme radiogroup ==== */
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

/* ==== Drag-n-drop ==== */
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
  } catch (e) { setError(t('error.prefix') + String(e.message).slice(0, 120)); }
}

/* ==== Init ==== */
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
    const cur = window.getLang ? window.window.getLang() : 'ru';
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

// [PATCH:STAGE1_DEV_MODE]
function _getDevMode() {
  try { return localStorage.getItem('pdb_dev_mode') === '1'; } catch (e) { return false; }
}
function _setDevMode(on) {
  try { localStorage.setItem('pdb_dev_mode', on ? '1' : '0'); } catch (e) {}
  if (on) _startDevPanel(); else _stopDevPanel();
}
let _devPanel = null;
let _devPanelTimer = null;

function _buildCurlString() {
  if (!currentImageId) return '# нет выбранного изображения';
  const payload = (State.boxes || []).map(b => ({
    x: b.x, y: b.y, w: b.w, h: b.h,
    label: b.label, confidence: b.confidence, frozen: b.frozen,
    behavior: b.behavior || null, animal_id: (b.animal_id ?? null),
    keypoints: Array.isArray(b.keypoints) ? b.keypoints : []
  }));
  const origin = (typeof location !== 'undefined' && location.origin)
                 ? location.origin : 'http://localhost:8000';
  const sep = ' \\\n  ';
  return (
    "curl -X POST '" + origin + '/api/images/' + currentImageId + "/annotations'" + sep +
    "-H 'Content-Type: application/json'" + sep +
    "-H 'X-Requested-With: DatasetBuilder'" + sep +
    "-d '" + JSON.stringify(payload) + "'"
  );
}

function _updateDevPanel() {
  if (!_devPanel) return;
  const pre = _devPanel.querySelector('.dev-panel-state');
  if (pre) {
    try { pre.textContent = JSON.stringify(State.boxes || [], null, 2); }
    catch (e) { pre.textContent = '[error serializing state]'; }
  }
  const imgEl = _devPanel.querySelector('.dev-panel-image');
  if (imgEl) imgEl.textContent = 'image_id: ' + (currentImageId ?? '—');
}

function _startDevPanel() {
  if (_devPanel) return;
  const wrap = document.createElement('div');
  wrap.id = 'devPanel';
  wrap.style.cssText =
    'position:fixed;right:12px;bottom:12px;width:420px;max-height:70vh;'
    + 'background:rgba(20,20,22,0.94);color:#f5f5f7;border-radius:12px;'
    + 'box-shadow:0 10px 40px rgba(0,0,0,0.4);z-index:99999;'
    + 'font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;'
    + 'display:flex;flex-direction:column;border:1px solid rgba(255,255,255,0.1);';

  const header = document.createElement('div');
  header.style.cssText =
    'display:flex;align-items:center;justify-content:space-between;'
    + 'padding:10px 12px;border-bottom:1px solid rgba(255,255,255,0.1);';
  header.innerHTML = '<b>🛠 Dev Mode</b>';
  const btnClose = document.createElement('button');
  btnClose.textContent = '✕';
  btnClose.style.cssText = 'background:none;border:none;color:#f5f5f7;cursor:pointer;font-size:14px;';
  btnClose.onclick = () => {
    _setDevMode(false);
    const cb = document.getElementById('devModeToggle');
    if (cb) cb.checked = false;
  };
  header.appendChild(btnClose);
  wrap.appendChild(header);

  const imgInfo = document.createElement('div');
  imgInfo.className = 'dev-panel-image';
  imgInfo.style.cssText = 'padding:6px 12px;color:#8e8e93;font-size:11px;';
  imgInfo.textContent = 'image_id: —';
  wrap.appendChild(imgInfo);

  const pre = document.createElement('pre');
  pre.className = 'dev-panel-state';
  pre.style.cssText =
    'flex:1;overflow:auto;margin:0;padding:8px 12px;'
    + 'background:#0a0a0b;font-size:11px;line-height:1.4;max-height:40vh;';
  pre.textContent = '{}';
  wrap.appendChild(pre);

  const actions = document.createElement('div');
  actions.style.cssText =
    'display:flex;gap:6px;padding:8px 12px;border-top:1px solid rgba(255,255,255,0.1);';

  const btnCurl = document.createElement('button');
  btnCurl.textContent = '📋 Скопировать cURL';
  btnCurl.style.cssText =
    'flex:1;padding:6px 10px;border-radius:6px;'
    + 'background:#0a84ff;color:#fff;border:none;cursor:pointer;font-size:11px;';
  btnCurl.onclick = async () => {
    try {
      await navigator.clipboard.writeText(_buildCurlString());
      btnCurl.textContent = '✓ Скопировано';
      setTimeout(() => { btnCurl.textContent = '📋 Скопировать cURL'; }, 1500);
    } catch (e) {
      setError('Не удалось скопировать: ' + (e.message || e));
    }
  };
  actions.appendChild(btnCurl);

  const btnRefresh = document.createElement('button');
  btnRefresh.textContent = '↻';
  btnRefresh.title = 'Обновить';
  btnRefresh.style.cssText =
    'padding:6px 10px;border-radius:6px;'
    + 'background:rgba(255,255,255,0.1);color:#f5f5f7;border:none;cursor:pointer;font-size:11px;';
  btnRefresh.onclick = _updateDevPanel;
  actions.appendChild(btnRefresh);
  wrap.appendChild(actions);

  document.body.appendChild(wrap);
  _devPanel = wrap;
  _updateDevPanel();
  _devPanelTimer = setInterval(_updateDevPanel, 500);
}

function _stopDevPanel() {
  if (_devPanelTimer) { clearInterval(_devPanelTimer); _devPanelTimer = null; }
  if (_devPanel && _devPanel.parentNode) _devPanel.parentNode.removeChild(_devPanel);
  _devPanel = null;
}
// [/PATCH:STAGE1_DEV_MODE]

// V11.10.10: Auto-bind ALL functions to window
window._applyAllToPhoto = _applyAllToPhoto;
window._applyAnimalIdToTargets = _applyAnimalIdToTargets;
window._applyBehaviorToTargets = _applyBehaviorToTargets;
window._applyMotionVectorBtnState = _applyMotionVectorBtnState;
window._applyProjectVisualSettings = _applyProjectVisualSettings;
window._assignNextAnimalId = _assignNextAnimalId;
window._autoDetectBehavior = _autoDetectBehavior;
window._autoSkeletonPose = _autoSkeletonPose;
window._behaviorColor = _behaviorColor;
window._boxAriaLabel = _boxAriaLabel;
window._buildSectionList = _buildSectionList;
window._cancelLoadImages = _cancelLoadImages;
window._checkSamModel = _checkSamModel;
window._clearDebugBoxes = _clearDebugBoxes;
window._clearSamPreview = _clearSamPreview;
window._clearSkeletonHint = _clearSkeletonHint;
window._confirmSamPreview = _confirmSamPreview;
window._createBoxElement = _createBoxElement;
window._deleteSkeleton = _deleteSkeleton;
window._downloadDbBackup = _downloadDbBackup;
window._drawSkeletonForBox = _drawSkeletonForBox;
window._ensureNotificationPermission = _ensureNotificationPermission;
window._fillProjectAdvancedSettings = _fillProjectAdvancedSettings;
window._findRowIndexAtY = _findRowIndexAtY;
window._fmtBytes = _fmtBytes;
window._getAttrTargets = _getAttrTargets;
window._getTagSet = _getTagSet;
window._handleSmartCopy = _handleSmartCopy;
window._hideActiveLearningBanner = _hideActiveLearningBanner;
window._imagesQueryParams = _imagesQueryParams;
window._importZipViaDrag = _importZipViaDrag;
window._installAttrBar = _installAttrBar;
window._installDropZone = _installDropZone;
window._installLangSegment = _installLangSegment;
window._installSkeletonDblClick = _installSkeletonDblClick;
window._installThemeRadiogroup = _installThemeRadiogroup;
window._installTrainTaskSegment = _installTrainTaskSegment;
window._installVideoListeners = _installVideoListeners;
window._invalidateTagSet = _invalidateTagSet;
window._invalidateValidateCache = _invalidateValidateCache;
window._isImageItem = _isImageItem;
window._isTrashOrProjectEmpty = _isTrashOrProjectEmpty;
window._linkFromPrev = _linkFromPrev;
window._listScrollInfo = _listScrollInfo;
window._makeRowDraggable = _makeRowDraggable;
window._maybeLoadMoreImages = _maybeLoadMoreImages;
window._navigateWithAid = _navigateWithAid;
window._nextUnplacedName = _nextUnplacedName;
window._pickSmartCopySource = _pickSmartCopySource;
window._placeNextKeypoint = _placeNextKeypoint;
window._pollMigration = _pollMigration;
window._pushListUndo = _pushListUndo;
window._recomputeCounters = _recomputeCounters;
window._recomputeRowTops = _recomputeRowTops;
window._refreshActiveLearning = _refreshActiveLearning;
window._refreshActiveLearningDebounced = _refreshActiveLearningDebounced;
window._refreshAttrBar = _refreshAttrBar;
window._refreshFfmpegStatus = _refreshFfmpegStatus;
window._refreshMotionVector = _refreshMotionVector;
window._refreshRowMeta = _refreshRowMeta;
window._refreshStorageInfo = _refreshStorageInfo;
window._refreshTrainDatasetWarn = _refreshTrainDatasetWarn;
window._reloadAllAfterSmartCopy = _reloadAllAfterSmartCopy;
window._reloadKeypointsForImage = _reloadKeypointsForImage;
window._reloadKeypointsFromBox = _reloadKeypointsFromBox;
window._rememberProjectId = _rememberProjectId;
window._removeLastKeypoint = _removeLastKeypoint;
// V11.8.4: удаление конкретной точки (ПКМ по точке)
// Использует module-scope `keypoints`, НЕ window.keypoints —
// чтобы не зависеть от порядка инициализации window-геттеров.
window._removeKeypoint = function(idx) {
  if (!Array.isArray(keypoints) || idx < 0 || idx >= keypoints.length) return;
  const removed = keypoints.splice(idx, 1)[0];
  if (typeof window._syncKeypointsToBox === 'function') window._syncKeypointsToBox();
  if (typeof window.pushHistory === 'function') window.pushHistory();
  if (typeof window.markDirty === 'function') window.markDirty();
  if (typeof window.renderSkeleton === 'function') window.renderSkeleton();
  if (typeof window.setStatus === 'function' && removed) {
    const _meta = typeof _schemaName === 'function' ? _schemaName(removed.name) : null;
    const _lbl = _meta ? ((typeof getLang === 'function' && window.getLang() === 'en')
                         ? _meta.label_en : _meta.label_ru) : removed.name;
    window.setStatus(`Удалено: ${_lbl}`, 1500);
  }
};
window._renderDebugBoxes = _renderDebugBoxes;
window._renderFfmpegStatus = _renderFfmpegStatus;
window._renderLiveTrainCharts = _renderLiveTrainCharts;
window._renderMetrics = _renderMetrics;
window._renderMetricsChart = _renderMetricsChart;
window._renderMigrationBlock = _renderMigrationBlock;
window._renderMigrationStatus = _renderMigrationStatus;
window._renderProjectsList = _renderProjectsList;
window._renderSamPreview = _renderSamPreview;
window._renderStorageInfo = _renderStorageInfo;
window._renderTrackPlayer = _renderTrackPlayer;
window._restoreHistoryAfterAutolabel = _restoreHistoryAfterAutolabel;
window._rowH = _rowH;
window._rowKeyOf = _rowKeyOf;
window._runExternalImport = _runExternalImport;
window._samClickAt = _samClickAt;
window._saveCollapsedSections = _saveCollapsedSections;
window._schemaName = _schemaName;
window._schemaOrder = _schemaOrder;
window._showActiveLearningBanner = _showActiveLearningBanner;
window._showSmartCopyCaseCDialog = _showSmartCopyCaseCDialog;
window._showTrainingNotification = _showTrainingNotification;
window._startMigration = _startMigration;
window._startTracking = _startTracking;
window._subscribeTrackEvents = _subscribeTrackEvents;
window._syncCurrentProjectMeta = _syncCurrentProjectMeta;
window._syncKeypointsToBox = _syncKeypointsToBox;
window._targetAnnotationId = _targetAnnotationId;
window._toggleKeypointVisibility = _toggleKeypointVisibility;
window._updateImageMeta = _updateImageMeta;
window._updateRowContent = _updateRowContent;
window._updateSectionRow = _updateSectionRow;
window._updateTitleProgress = _updateTitleProgress;
window._updateTrainingIndicator = _updateTrainingIndicator;
window._uploadFilesViaDrag = _uploadFilesViaDrag;
window._validateProjectForm = _validateProjectForm;
window.acceptAndNext = acceptAndNext;
window.activateModel = activateModel;
window.animateNumber = animateNumber;
window.applyFiltersAndRender = applyFiltersAndRender;
window.bulkToggleTag = bulkToggleTag;
window.checkModelsAvailability = checkModelsAvailability;
window.checkVideoCapabilities = checkVideoCapabilities;
window.clearStatus = clearStatus;
window.confColor = confColor;
window.confLabelText = confLabelText;
window.confSortKey = confSortKey;
window.confirmDeleteProject = confirmDeleteProject;
window.createBoxInCenter = createBoxInCenter;
window.createClassSearch = createClassSearch;
window.currentObjectClass = currentObjectClass;
window.deleteBox = deleteBox;
window.deleteImage = deleteImage;
window.deleteModel = deleteModel;
window.deleteSelectedBox = deleteSelectedBox;
window.deleteTag = deleteTag;
window.downloadBoxesCsv = downloadBoxesCsv;
window.downloadFilesCsv = downloadFilesCsv;
window.editTag = editTag;
window.endOperation = endOperation;
window.escapeHtml = escapeHtml;
window.exportCoco = exportCoco;
window.exportYolo = exportYolo;
window.extractVideoFrames = extractVideoFrames;
window.filterList = filterList;
window.fmtSize = fmtSize;
window.getAutolabelMode = getAutolabelMode;
window.getDebugMode = getDebugMode;
window.getExt = getExt;
window.getStem = getStem;
window.getTrainTask = getTrainTask;
window.getTta = getTta;
window.highlightProject = highlightProject;
window.initColorPickers = initColorPickers;
window.initCustomSelects = initCustomSelects;
window.invalidateObjectClasses = invalidateObjectClasses;
window.isSamModeActive = isSamModeActive;
window.loadImages = loadImages;
window.loadKeypointSchema = loadKeypointSchema;
window.loadModelsIntoUI = loadModelsIntoUI;
window.loadMoreImages = loadMoreImages;
window.loadObjectClasses = loadObjectClasses;
window.loadProjects = loadProjects;
window.loadTags = loadTags;
window.loadTrashView = loadTrashView;
window.makeHardIndicator = makeHardIndicator;
window.makeMainRow = makeMainRow;
window.makeProjectTrashRow = makeProjectTrashRow;
window.makeSectionRow = makeSectionRow;
window.makeStatusDot = makeStatusDot;
window.makeTagsMini = makeTagsMini;
window.makeTrashRow = makeTrashRow;
window.markClean = markClean;
window.markDirty = markDirty;
window.markSavedWithPulse = markSavedWithPulse;
window.navigateToNextUnlabeled = navigateToNextUnlabeled;
window.navigateToPrevUnlabeled = navigateToPrevUnlabeled;
window.onActivate = onActivate;
window.onListScroll = onListScroll;
window.openBulkRename = openBulkRename;
window.openDuplicatesModal = openDuplicatesModal;
window.openExportModal = openExportModal;
window.openFfmpegHelp = openFfmpegHelp;
window.openLogs = openLogs;
window.openModelCompare = openModelCompare;
window.openMoveCopyDialog = openMoveCopyDialog;
window.openPreview = openPreview;
window.openProjectCreate = openProjectCreate;
window.openProjectEdit = openProjectEdit;
window.openTagsManager = openTagsManager;
window.openTagsManagerFromSettings = openTagsManagerFromSettings;
window.openTrackPlayer = openTrackPlayer;
window.openValidateModal = openValidateModal;
window.permanentDelete = permanentDelete;
window.permanentDeleteProject = permanentDeleteProject;
window.plural = plural;
window.pluralGroups = pluralGroups;
window.pluralImages = pluralImages;
window.pluralProjects = pluralProjects;
window.prefersReducedMotion = prefersReducedMotion;
window.pulseSaveIndicator = pulseSaveIndicator;
window.pushHistory = pushHistory;
window.redo = redo;
window.redoListAction = redoListAction;
window.refreshTrainStatus = refreshTrainStatus;
window.renameImage = renameImage;
window.renameModel = renameModel;
window.renderBatchState = renderBatchState;
window.renderBootstrapStatus = renderBootstrapStatus;
window.renderBulkTagMenu = renderBulkTagMenu;
window.renderImageList = renderImageList;
window.renderLogs = renderLogs;
window.renderSkeleton = renderSkeleton;
window.renderTagChips = renderTagChips;
window.renderTagFilter = renderTagFilter;
window.renderTagsManager = renderTagsManager;
window.renderTrainState = renderTrainState;
window.renderVersions = renderVersions;
window.resetHistory = resetHistory;
window.restoreImage = restoreImage;
window.restoreProject = restoreProject;
window.runAutolabel = runAutolabel;
window.scheduleRefreshMotionVector = scheduleRefreshMotionVector;
window.scheduleRefreshMotionVectorDebounced = scheduleRefreshMotionVectorDebounced;
window.scheduleRender = scheduleRender;
window.scheduleRenderBoxes = scheduleRenderBoxes;
window.scheduleRenderSkeleton = scheduleRenderSkeleton;
window.scrollListToImage = scrollListToImage;
window.selectImage = selectImage;
window.setAutolabelMode = setAutolabelMode;
window.setDebugMode = setDebugMode;
window.setFfmpegPathManually = setFfmpegPathManually;
window.setSamMode = setSamMode;
window.setSkeletonMode = setSkeletonMode;
window.setSortMode = setSortMode;
window.setTrainTask = setTrainTask;
window.setTta = setTta;
window.setupFilterMenu = setupFilterMenu;
window.setupSortMenu = setupSortMenu;
window.showBackupResult = showBackupResult;
window.showCanvas = showCanvas;
window.showImageSkeleton = showImageSkeleton;
window.snapshot = snapshot;
window.sortImages = sortImages;
window.setModelMode = setModelMode;
window.startTour = startTour;
window.startLogsAutoRefresh = startLogsAutoRefresh;
window.startOperation = startOperation;
window.stopLogsAutoRefresh = stopLogsAutoRefresh;
window.subscribeBatchEvents = subscribeBatchEvents;
window.subscribeBootstrapEvents = subscribeBootstrapEvents;
window.subscribeTrainEvents = subscribeTrainEvents;
// [STAGE1-A:behavior-audit-ui]
async function auditBehaviorCurrent() {
  if (!currentImageId) return;
  try {
    const r = await api(`/api/images/${currentImageId}/behavior_audit`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const msg = `Согласие: ${r.agree}/${r.total} (${(r.agreement * 100).toFixed(1)}%)`;
    if (r.rows.length) { console.table(r.rows); setStatus(msg, 6000); }
    else { setStatus('Нет размеченного поведения на этом фото', 4000); }
  } catch (e) { setError('Аудит поведения: ' + String(e.message).slice(0, 160)); }
}
window.auditBehaviorCurrent = auditBehaviorCurrent;  // [STAGE1-A:behavior-audit-ui]

window.toggleMotionVector = toggleMotionVector;
window.toggleSection = toggleSection;
window.toggleSelectAll = toggleSelectAll;
window.toggleTagChip = toggleTagChip;
window.undo = undo;
window.undoListAction = undoListAction;
window.updateBoxInPlace = updateBoxInPlace;
window.updateBulkBar = updateBulkBar;
window.updateBulkTagBtn = updateBulkTagBtn;
window.updateCurrentProjectInfo = updateCurrentProjectInfo;
window.updateDelBoxBtn = updateDelBoxBtn;
window.updateFilterBadge = updateFilterBadge;
window.updateFreezeBtn = updateFreezeBtn;
window.updateHardBtn = updateHardBtn;
window.updateProgress = updateProgress;
window.updateSaveIndicator = updateSaveIndicator;
window.updateSectionUI = updateSectionUI;
window.updateSelectAllCheck = updateSelectAllCheck;
window.updateSimilarBtn = updateSimilarBtn;
window.updateSortUI = updateSortUI;
window.updateTrashActionsBar = updateTrashActionsBar;
window.updateTrashBadge = updateTrashBadge;
window.updateTrashBar = updateTrashBar;
window.upgradeColorPicker = upgradeColorPicker;
window.upgradeSelect = upgradeSelect;

// V11.6.0: UI bindings for inline HTML
// V11.10.16: bulletproof clearSelection
let _clearSelectionToken = 0;
window.clearSelection = () => {
  // 1) Сброс через State — источник истины
  try {
    if (window.State) {
      window.State.selectedIndex = -1;
      if (window.State.multiSelected && typeof window.State.multiSelected.clear === 'function') {
        window.State.multiSelected.clear();
      }
    }
  } catch (e) {}

  // 2) Сброс локальных переменных
  try { selectedIndex = -1; } catch (e) {}
  try { multiSelected.clear(); } catch (e) {}

  // 3) Принудительно снять фокус с любой рамки
  try {
    const ae = document.activeElement;
    if (ae && ae.classList && ae.classList.contains('box')) {
      ae.blur();
    }
  } catch (e) {}

  // 4) Прямая очистка DOM
  document.querySelectorAll('#boxes .box').forEach(el => {
    el.classList.remove('selected', 'multi-selected');
  });

  // 5) Обновить UI
  if (typeof updateSelectionClasses === 'function') {
    updateSelectionClasses();
  }
};

window.openModal = openModal;
window.getSelectedIndices = getSelectedIndices;
window.renderBoxes = renderBoxes; // V11.10.9: Привязка для keyboard.js
window.navigateImage = navigateImage; // V11.10.9: Привязка для keyboard.js // V11.10.8: Привязка для keyboard.js
window.updateSelectionClasses = updateSelectionClasses; // V11.10.8: Привязка для focus listener
window.MODAL_STACK = MODAL_STACK;
// V11.10.16: window.toggleMultiSelect — вызывается из canvas.js при shift+click
window.toggleMultiSelect = function (idx) {
  if (!window.State) return;
  const ms = window.State.multiSelected;
  if (!ms) return;
  if (ms.has(idx)) ms.delete(idx); else ms.add(idx);
  window.State.selectedIndex = idx;
  if (typeof window.updateSelectionClasses === 'function') {
    window.updateSelectionClasses();
  }
};


window.closeAllPopovers = closeAllPopovers;
// V11.9.3: Aggressive window bindings for inline HTML handlers
if (typeof createProject !== 'undefined') window.createProject = createProject;
if (typeof toggleTrash !== 'undefined') window.toggleTrash = toggleTrash;
if (typeof triggerVideoExtract !== 'undefined') window.triggerVideoExtract = triggerVideoExtract;
if (typeof openImportSourceModal !== 'undefined') window.openImportSourceModal = openImportSourceModal;
if (typeof uploadImages !== 'undefined') window.uploadImages = uploadImages;
if (typeof handleImport !== 'undefined') window.handleImport = handleImport;
if (typeof openStats !== 'undefined') 
window.runCalibration = async () => {
  if (!currentProjectId) return;
  setStatus('Калибровка...');
  try {
    const r = await api(`/api/projects/${currentProjectId}/behavior/calibrate`, { method: 'POST' });
    if (r.error) { setError(r.error); return; }
    setSuccess(t('stats.calibrate.done', { acc: (r.accuracy*100).toFixed(1), n: r.n_pairs }));
  } catch(e) { setError(t('stats.calibrate.err')); }
};

window.resetCalibration = async () => {
  if (!currentProjectId) return;
  if (!await showConfirm('Сброс', 'Вернуть заводские пороги для этого проекта?')) return;
  try {
    await api(`/api/projects/${currentProjectId}/behavior/calibrate`, { method: 'DELETE' });
    setSuccess('Пороги сброшены');
  } catch(e) { setError(e.message); }
};


window.showBehaviorThresholds = async () => {
  if (!currentProjectId) return;
  try {
    const tv = await api(`/api/projects/${currentProjectId}/behavior/thresholds`);
    const wrap = document.createElement('div');
    wrap.style.cssText = 'font-size:0.875rem; line-height:1.8; background:var(--bg-hover); padding:12px; border-radius:8px;';
    wrap.innerHTML = `
      <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--hairline);"><span>drink_thr (нос внизу):</span> <b>${tv.drink_thr}</b></div>
      <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--hairline);"><span>active_delta (сдвиг):</span> <b>${tv.active_delta}</b></div>
      <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--hairline);"><span>active_per_frame:</span> <b>${tv.active_per_frame}</b></div>
      <div style="display:flex;justify-content:space-between;padding:4px 0;"><span>active_bbox_ratio:</span> <b>${tv.active_bbox_ratio}</b></div>
    `;
    _openCustomDialog({
      title: 'Текущие пороги поведения',
      selectorEl: wrap,
      okText: 'OK'
    });
  } catch(e) { setError('Не удалось загрузить пороги'); }
};

window.openStats = openStats;
if (typeof clearSearch !== 'undefined') window.clearSearch = clearSearch;
if (typeof emptyTrashAll !== 'undefined') window.emptyTrashAll = emptyTrashAll;
if (typeof clearListSelection !== 'undefined') window.clearListSelection = clearListSelection;
if (typeof confirmBatchDelete !== 'undefined') window.confirmBatchDelete = confirmBatchDelete;
if (typeof batchRestore !== 'undefined') window.batchRestore = batchRestore;
if (typeof confirmBatchPermanentDelete !== 'undefined') window.confirmBatchPermanentDelete = confirmBatchPermanentDelete;
if (typeof autolabel !== 'undefined') window.autolabel = autolabel;
if (typeof autolabelAllUnlabeled !== 'undefined') window.autolabelAllUnlabeled = autolabelAllUnlabeled;
if (typeof saveAnnotations !== 'undefined') window.saveAnnotations = saveAnnotations;
if (typeof toggleHardCurrent !== 'undefined') window.toggleHardCurrent = toggleHardCurrent;
if (typeof toggleSamMode !== 'undefined') window.toggleSamMode = toggleSamMode;
if (typeof toggleFreezeSelected !== 'undefined') window.toggleFreezeSelected = toggleFreezeSelected;
if (typeof clearBoxes !== 'undefined') window.clearBoxes = clearBoxes;
if (typeof toggleSkeletonMode !== 'undefined') window.toggleSkeletonMode = toggleSkeletonMode;
if (typeof toggleBulkTagMenu !== 'undefined') window.toggleBulkTagMenu = toggleBulkTagMenu;
if (typeof toggleFileOpsMenu !== 'undefined') window.toggleFileOpsMenu = toggleFileOpsMenu;
if (typeof toggleExportMenu !== 'undefined') window.toggleExportMenu = toggleExportMenu;
if (typeof openTracksModal !== 'undefined') window.openTracksModal = openTracksModal;
if (typeof cancelActiveOperation !== 'undefined') window.cancelActiveOperation = cancelActiveOperation;
if (typeof zoomToSelection !== 'undefined') window.zoomToSelection = zoomToSelection;
if (typeof zoomToCenter !== 'undefined') window.zoomToCenter = zoomToCenter;
if (typeof zoomFit !== 'undefined') window.zoomFit = zoomFit;
if (typeof openTagCreate !== 'undefined') window.openTagCreate = openTagCreate;
if (typeof closeTagCreate !== 'undefined') window.closeTagCreate = closeTagCreate;
if (typeof createTagInline !== 'undefined') window.createTagInline = createTagInline;
if (typeof openLogsFromSettings !== 'undefined') window.openLogsFromSettings = openLogsFromSettings;
if (typeof doBackup !== 'undefined') window.doBackup = doBackup;
if (typeof openTrainModal !== 'undefined') window.openTrainModal = openTrainModal;
if (typeof downloadModel !== 'undefined') window.downloadModel = downloadModel;
if (typeof saveSettings !== 'undefined') window.saveSettings = saveSettings;
if (typeof closeSettings !== 'undefined') window.closeSettings = closeSettings;
if (typeof closeTrainModal !== 'undefined') window.closeTrainModal = closeTrainModal;
if (typeof stopTraining !== 'undefined') window.stopTraining = stopTraining;
if (typeof startTraining !== 'undefined') window.startTraining = startTraining;
if (typeof openMetricsModal !== 'undefined') window.openMetricsModal = openMetricsModal;
if (typeof closeMetricsModal !== 'undefined') window.closeMetricsModal = closeMetricsModal;
if (typeof closeDuplicatesModal !== 'undefined') window.closeDuplicatesModal = closeDuplicatesModal;
if (typeof closeFfmpegHelp !== 'undefined') window.closeFfmpegHelp = closeFfmpegHelp;
if (typeof closeSimilarModal !== 'undefined') window.closeSimilarModal = closeSimilarModal;
if (typeof closeImportSourceModal !== 'undefined') window.closeImportSourceModal = closeImportSourceModal;
if (typeof importFromRoboflow !== 'undefined') window.importFromRoboflow = importFromRoboflow;
if (typeof importFromSupervisely !== 'undefined') window.importFromSupervisely = importFromSupervisely;
if (typeof importFromUrl !== 'undefined') window.importFromUrl = importFromUrl;
if (typeof importFromLocalFolder !== 'undefined') window.importFromLocalFolder = importFromLocalFolder;
if (typeof importFromLabelbox !== 'undefined') window.importFromLabelbox = importFromLabelbox;
if (typeof importFromScale !== 'undefined') window.importFromScale = importFromScale;
if (typeof importFromDarwin !== 'undefined') window.importFromDarwin = importFromDarwin;
if (typeof closeExportModal !== 'undefined') window.closeExportModal = closeExportModal;
if (typeof openValidateFromExport !== 'undefined') window.openValidateFromExport = openValidateFromExport;
if (typeof executeExport !== 'undefined') window.executeExport = executeExport;
if (typeof closeImportModal !== 'undefined') window.closeImportModal = closeImportModal;
if (typeof closePreview !== 'undefined') window.closePreview = closePreview;
if (typeof closeStats !== 'undefined') window.closeStats = closeStats;
if (typeof downloadStatsCsv !== 'undefined') window.downloadStatsCsv = downloadStatsCsv;
if (typeof closeValidateModal !== 'undefined') window.closeValidateModal = closeValidateModal;
if (typeof closeTagsManager !== 'undefined') window.closeTagsManager = closeTagsManager;
if (typeof createTag !== 'undefined') window.createTag = createTag;
if (typeof closeVersions !== 'undefined') window.closeVersions = closeVersions;
if (typeof exportTracks !== 'undefined') window.exportTracks = exportTracks;
if (typeof closeTracksModal !== 'undefined') window.closeTracksModal = closeTracksModal;
if (typeof playerNav !== 'undefined') window.playerNav = playerNav;
if (typeof playerOpenCurrent !== 'undefined') window.playerOpenCurrent = playerOpenCurrent;
if (typeof closeTrackPlayer !== 'undefined') window.closeTrackPlayer = closeTrackPlayer;
if (typeof closeLogs !== 'undefined') window.closeLogs = closeLogs;
if (typeof refreshLogs !== 'undefined') window.refreshLogs = refreshLogs;
if (typeof clearLogs !== 'undefined') window.clearLogs = clearLogs;
if (typeof closeShortcuts !== 'undefined') window.closeShortcuts = closeShortcuts;
if (typeof submitProjectModal !== 'undefined') window.submitProjectModal = submitProjectModal;
if (typeof closeProjectModal !== 'undefined') window.closeProjectModal = closeProjectModal;
if (typeof clearProjectAnnotations !== 'undefined') window.clearProjectAnnotations = clearProjectAnnotations;
if (typeof _resetMigrationState !== 'undefined') window._resetMigrationState = _resetMigrationState;
if (typeof openShortcuts !== 'undefined') window.openShortcuts = openShortcuts;
if (typeof openSettings !== 'undefined') window.openSettings = openSettings;
if (typeof openVersions !== 'undefined') window.openVersions = openVersions;

// V11.8.0: Canvas & Keyboard bindings
window.getRel = getRel;
window.clampBox = clampBox;
window.applyTransform = applyTransform;
window.clampPan = clampPan;
window.zoomAt = zoomAt;
window.zoomToCenter = zoomToCenter;
window.zoomReset = zoomReset;
window.zoomFit = zoomFit;
window.zoomToSelection = zoomToSelection;
// V11.7.0: Theme & CmdPalette bindings
window.getThemeMode = getThemeMode;
window.applyTheme = applyTheme;
window.setThemeMode = setThemeMode;
window.updateThemeSegment = updateThemeSegment;
window.getHideHints = getHideHints;
window.setHideHints = setHideHints;
window.getFocusMode = getFocusMode;
window.setFocusMode = setFocusMode;
window.toggleFocusMode = toggleFocusMode;
window.applyFocusMode = applyFocusMode;
window.openCommandPalette = openCommandPalette;
window.closeCommandPalette = closeCommandPalette;
window.closeModal = closeModal;
window.isModalOpen = isModalOpen;
window._closeDialog = _closeDialog;
window._openDialog = _openDialog;
window._openCustomDialog = _openCustomDialog;
window.openGuide = openGuide;
window.closeGuide = closeGuide;
window.showAlert = showAlert;
window.showConfirm = showConfirm;
window.showPrompt = showPrompt;
window._installTooltipObserver = _installTooltipObserver;
window.convertTitlesIn = convertTitlesIn;
window.downloadFile = downloadFile;
window.haptic = haptic;
window.t = t;
window.setStatus = setStatus;
window.setSuccess = setSuccess;
window.setError = setError;

// V11.11.0: Глобальный перехватчик удален (ломал Tab-навигацию).
// Снятие выделения при клике по пустому месту холста обрабатывается в canvas.js.
// V11.10.18: expose internal state to window via getters.
// keyboard.js, command_palette.js читают window.historyIndex,
// window._listUndoStack, window.currentProjectId и т.д. Раньше их не было
// на window → Ctrl+Z падал на TypeError, палитра не видела проектов.
// get/set замыкаются на локальные let-переменные — всегда в синхроне.
(function () {
  const _defs = [
    ['historyIndex',       () => historyIndex,       v => { historyIndex = v; }],
    ['_listUndoStack',     () => _listUndoStack,     null],
    ['_listRedoStack',     () => _listRedoStack,     null],
    ['_cachedProjectsList',() => _cachedProjectsList,null],
    ['currentProjectId',   () => currentProjectId,   null],
    ['currentProjectMeta', () => currentProjectMeta, null],
    ['activeFilter',       () => activeFilter,       v => { activeFilter = v; }],
    ['activeTagIds',       () => activeTagIds,       null],
    ['projectTags',        () => projectTags,        null],
    ['projectTagsMap',     () => projectTagsMap,     null],
    ['objectClassesCache', () => objectClassesCache, null],
    ['samMode',            () => samMode,            v => { samMode = v; }],
    ['viewMode',           () => viewMode,           v => { viewMode = v; }],
    ['exportFormat',       () => exportFormat,       v => { exportFormat = v; }],
    ['keypoints',          () => keypoints,          v => { keypoints = v; }],
  ];
  for (const [name, get, set] of _defs) {
    try {
      Object.defineProperty(window, name, {
        configurable: true,
        get: get,
        set: set || ((_v) => console.warn('[state-sync] window.' + name + ' is read-only')),
      });
    } catch (e) {
      console.warn('[state-sync] defineProperty failed for', name, e);
    }
  }
})();


/* ==== V11.10.0: Onboarding Tour ==== */
const TOUR_STEPS = [
  { el: '#projectsSectionTitle', title: 'tour.step1.title', text: 'tour.step1.text', pos: 'right' },
  { el: '#uploadSection', title: 'tour.step2.title', text: 'tour.step2.text', pos: 'right' },
  { el: '#sectionTitle', title: 'tour.step3.title', text: 'tour.step3.text', pos: 'right' },
  { el: '[data-action="autolabel"]', title: 'tour.step4.title', text: 'tour.step4.text', pos: 'bottom' },
  { el: '#skeletonModeBtn', title: 'tour.step5.title', text: 'tour.step5.text', pos: 'bottom' },
  { el: '#canvasHost', title: 'tour.step6.title', text: 'tour.step6.text', pos: 'top' },
  { el: '[data-action="saveAnnotations"]', title: 'tour.step7.title', text: 'tour.step7.text', pos: 'bottom' },
];
let _tourIdx = 0;
let _tourOverlay = null;
let _tourSpotlight = null;
let _tourTooltip = null;

function _tourInitDOM() {
  if (_tourOverlay) return;
  _tourOverlay = document.createElement('div');
  _tourOverlay.className = 'tour-overlay';
  _tourSpotlight = document.createElement('div');
  _tourSpotlight.className = 'tour-spotlight';
  _tourTooltip = document.createElement('div');
  _tourTooltip.className = 'tour-tooltip';
  _tourOverlay.appendChild(_tourSpotlight);
  _tourOverlay.appendChild(_tourTooltip);
  document.body.appendChild(_tourOverlay);
  window.addEventListener('scroll', () => _tourRender(false), { capture: true, passive: true });
  window.addEventListener('resize', () => _tourRender(false));
}

function _tourRender(animate = true) {
  const step = TOUR_STEPS[_tourIdx];
  const el = document.querySelector(step.el);
  if (!el) { _tourIdx++; if (_tourIdx < TOUR_STEPS.length) _tourRender(); else _tourEnd(); return; }
  if (el.id === 'attrBar' && el.style.display === 'none') {
    el.style.display = 'flex';
    el.dataset.tourForced = '1';
  }
  const rect = el.getBoundingClientRect();
  _tourSpotlight.style.transition = animate ? 'all 400ms cubic-bezier(0.25, 0.1, 0.25, 1)' : 'none';
  _tourTooltip.style.transition = animate ? 'all 400ms cubic-bezier(0.25, 0.1, 0.25, 1)' : 'none';
  _tourSpotlight.style.left = (rect.left - 6) + 'px';
  _tourSpotlight.style.top = (rect.top - 6) + 'px';
  _tourSpotlight.style.width = (rect.width + 12) + 'px';
  _tourSpotlight.style.height = (rect.height + 12) + 'px';

  let tx = rect.left, ty = rect.bottom + 16;
  if (step.pos === 'right') { tx = rect.right + 16; ty = rect.top; }
  if (step.pos === 'top') { tx = rect.left; ty = rect.top - 180; }
  if (tx + 320 > window.innerWidth) tx = window.innerWidth - 336;
  if (tx < 16) tx = 16;
  if (ty + 160 > window.innerHeight) ty = window.innerHeight - 176;
  if (ty < 16) ty = 16;

  _tourTooltip.style.left = tx + 'px';
  _tourTooltip.style.top = ty + 'px';

  let dots = '';
  for (let i = 0; i < TOUR_STEPS.length; i++) dots += `<div class="tour-dot ${i === _tourIdx ? 'active' : ''}"></div>`;

  _tourTooltip.innerHTML = `
    <h3>${t(step.title)}</h3>
    <p>${t(step.text)}</p>
    <div class="tour-tooltip-actions">
      <div class="tour-tooltip-dots">${dots}</div>
      <div style="display:flex;gap:8px;">
        <button class="btn btn-ghost btn-sm" id="tourBtnPrevSkip">${_tourIdx > 0 ? t('tour.prev') : t('tour.skip')}</button>
        <button class="btn btn-primary btn-sm" id="tourBtnNext">${_tourIdx === TOUR_STEPS.length - 1 ? t('tour.done') : t('tour.next')}</button>
      </div>
    </div>
  `;
  const _btnPrevSkip = _tourTooltip.querySelector('#tourBtnPrevSkip');
  if (_btnPrevSkip) _btnPrevSkip.addEventListener('click', (e) => {
    e.preventDefault();
    if (_tourIdx > 0) window._tourPrev(); else window._tourEnd();
  });
  const _btnNext = _tourTooltip.querySelector('#tourBtnNext');
  if (_btnNext) _btnNext.addEventListener('click', (e) => {
    e.preventDefault();
    window._tourNext();
  });
  _tourTooltip.classList.add('active');
}

window._tourNext = () => {
  _tourIdx++;
  if (_tourIdx >= TOUR_STEPS.length) _tourEnd();
  else _tourRender();
};
window._tourPrev = () => {
  _tourIdx--;
  if (_tourIdx < 0) _tourIdx = 0;
  _tourRender();
};
window._tourEnd = () => {
  if (_tourOverlay) _tourOverlay.classList.remove('active');
  try { localStorage.setItem('pdb_tour_done', '1'); } catch (e) {}
};
function startTour() {
  _tourInitDOM();
  _tourIdx = 0;
  window._isTourActive = true;
  _tourOverlay.classList.add('active');
  _tourRender();
}


// [STAGE1-FIX:backdrop-close] автозакрытие новых модалок по клику мимо
(function () {
  const newModals = {
    'trackMgmtModal': 'closeTrackMgmtModal',
    'videoPlayerModal': 'closeVideoPlayer',
  };
  Object.entries(newModals).forEach(([id, fn]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('mousedown', (e) => {
      if (e.target.id !== id) return;
      const f = window[fn];
      if (typeof f === 'function') f();
    });
  });
})();

// [V13.2.0:pipeline]
let _pipelineEventSource = null;

async function runFullPipeline() {
  if (!currentProjectId) { setStatus(t('toast.pickProject')); return; }
  _openPipelineModal();
}

function _openPipelineModal() {
  const mode = getAutolabelMode();
  document.querySelectorAll('input[name="pipeline_mode"]').forEach(r => {
    r.checked = (r.value === mode);
  });
  ['autolabel','pose','track','behavior'].forEach(s => {
    const cb = document.getElementById('pipelineStage_' + s);
    if (cb) cb.checked = true;
  });
  document.getElementById('pipelineForm').style.display = '';
  document.getElementById('pipelineProgressWrap').style.display = 'none';
  document.getElementById('pipelineStartBtn').style.display = '';
  document.getElementById('pipelineStopBtn').style.display = 'none';
  ['autolabel','pose','track','behavior'].forEach(s => _setStageChip(s, 'pending'));
  const logEl = document.getElementById('pipelineLog');
  if (logEl) logEl.textContent = '';
  openModal('pipelineModal');
}

function _setStageChip(stage, status, msg) {
  const el = document.getElementById('pipelineStage_' + stage + '_chip');
  if (!el) return;
  el.className = 'pipeline-stage ' + status;
  const icon = {pending: '⏳', running: '⏵', done: '✓', skipped: '⏸', error: '✗', disabled: '—'}[status] || '⏳';
  const label = {autolabel: 'Рамки', pose: 'Скелеты', track: 'Трекинг', behavior: 'Поведение'}[stage] || stage;
  el.innerHTML = `<span class="pipeline-stage-icon">${icon}</span> <span>${label}</span>` +
    (msg ? `<span class="pipeline-stage-msg">${escapeHtml(String(msg).slice(0, 80))}</span>` : '');
}

async function _pipelineStart() {
  if (!currentProjectId) return;
  const mode = (document.querySelector('input[name="pipeline_mode"]:checked') || {}).value || 'add';
  const stages = {};
  ['autolabel','pose','track','behavior'].forEach(s => {
    const cb = document.getElementById('pipelineStage_' + s);
    stages[s] = !!(cb && cb.checked);
  });
  if (!Object.values(stages).some(v => v)) {
    setStatus('Выберите хотя бы один этап'); return;
  }
  try {
    await api(`/api/projects/${currentProjectId}/pipeline/start`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, stages }),
    });
    document.getElementById('pipelineForm').style.display = 'none';
    document.getElementById('pipelineProgressWrap').style.display = '';
    document.getElementById('pipelineStartBtn').style.display = 'none';
    document.getElementById('pipelineStopBtn').style.display = '';
    const _cb = document.getElementById('pipelineCloseBtn');
    if (_cb) {
      _cb.classList.remove('btn-primary');
      _cb.classList.add('btn-ghost');
      _cb.textContent = window.t('common.close');
      _cb.setAttribute('data-i18n', 'common.close');
    }
    _subscribePipelineEvents();
    haptic('success');
  } catch (e) {
    if (e.status === 409) setError('Уже выполняется: ' + String(e.message || e).slice(0, 160));
    else setError('Не удалось запустить: ' + String(e.message || e).slice(0, 160));
  }
}

function _subscribePipelineEvents() {
  if (_pipelineEventSource) { try { _pipelineEventSource.close(); } catch (e) {} }
  const es = new EventSource(`/api/projects/${currentProjectId}/pipeline/events`);
  _pipelineEventSource = es;
  es.onmessage = (ev) => {
    try { _renderPipelineState(JSON.parse(ev.data)); } catch (e) {}
  };
  es.onerror = () => { try { es.close(); } catch (e) {} _pipelineEventSource = null; };
}

function _renderPipelineState(s) {
  const statusEl = document.getElementById('pipelineStatusText');
  const pctEl = document.getElementById('pipelinePercent');
  const fillEl = document.getElementById('pipelineProgressFill');
  const msgEl = document.getElementById('pipelineMessage');
  const stopBtn = document.getElementById('pipelineStopBtn');
  const startBtn = document.getElementById('pipelineStartBtn');
  const logEl = document.getElementById('pipelineLog');

  if (pctEl) pctEl.textContent = Math.round(s.progress || 0) + '%';
  if (fillEl) fillEl.style.width = (s.progress || 0) + '%';
  if (msgEl) msgEl.textContent = s.message || '';
  if (statusEl) {
    const map = {idle: 'Ожидание', running: 'Работает', stopping: 'Остановка…',
                 done: '✓ Готово', error: '✗ Ошибка', stopped: '⏸ Остановлено'};
    statusEl.textContent = map[s.status] || s.status;
  }
  const stageNames = ['autolabel','pose','track','behavior'];
  const sr = s.stage_results || {};
  stageNames.forEach(name => {
    if (!s.stage_enabled || !s.stage_enabled[name]) { _setStageChip(name, 'disabled'); return; }
    if (sr[name]) {
      const r = sr[name];
      _setStageChip(name, r === 'done' ? 'done' : r === 'skipped' ? 'skipped' : 'error');
    } else if (s.stage === name) {
      _setStageChip(name, 'running', s.message || '');
    } else {
      _setStageChip(name, 'pending');
    }
  });
  if (logEl && s.log) {
    logEl.textContent = (s.log || []).slice(-25).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
  }
  const closeBtn = document.getElementById('pipelineCloseBtn');
  if (s.status === 'done') {
    if (stopBtn) stopBtn.style.display = 'none';
    if (startBtn) startBtn.style.display = 'none';
    if (closeBtn) {
      closeBtn.classList.remove('btn-ghost');
      closeBtn.classList.add('btn-primary');
      closeBtn.textContent = window.t('pipeline.done');
      closeBtn.removeAttribute('data-i18n');
    }
  } else if (s.status === 'error' || s.status === 'stopped') {
    if (stopBtn) stopBtn.style.display = 'none';
    if (startBtn) { startBtn.style.display = ''; startBtn.textContent = window.t('pipeline.retry'); startBtn.removeAttribute('data-i18n'); }
    if (closeBtn) {
      closeBtn.classList.remove('btn-primary');
      closeBtn.classList.add('btn-ghost');
      closeBtn.textContent = window.t('common.close');
      closeBtn.setAttribute('data-i18n', 'common.close');
    }
  }

  if (s.status === 'done') setSuccess('Полная разметка завершена', 6000);
  else if (s.status === 'error') setError('Pipeline: ' + (s.error || 'ошибка'), 8000);
  else if (s.status === 'stopped') setStatus('Остановлено', 4000);

  if (s.status === 'done' || s.status === 'error' || s.status === 'stopped') {
    loadImages();
    if (currentImageId) {
      api(`/api/images/${currentImageId}/annotations`).then(anns => {
        State.boxes = anns || []; renderBoxes();
      }).catch(() => {});
    }
    if (_pipelineEventSource) { try { _pipelineEventSource.close(); } catch (e) {} _pipelineEventSource = null; }
  }
}

async function _pipelineStop() {
  if (!currentProjectId) return;
  try {
    await api(`/api/projects/${currentProjectId}/pipeline/stop`, { method: 'POST' });
    setStatus('Останавливаю…', 3000);
  } catch (e) { setError(String(e.message || e).slice(0, 140)); }
}

function closePipelineModal() { closeModal('pipelineModal'); }

window.runFullPipeline = runFullPipeline;
window._pipelineStart = _pipelineStart;
window._pipelineStop = _pipelineStop;
window.closePipelineModal = closePipelineModal;
window._renderPipelineState = _renderPipelineState;
window._subscribePipelineEvents = _subscribePipelineEvents;
window._openPipelineModal = _openPipelineModal;


// ============================================================================
// [PATCH:file-ops-wrappers] Wrappers for fileOpsMenu actions.
// Menu triggers data-action="openXxxFromMenu" — closes the menu, then calls
// the real handler. Replaces the previous broken
//   data-args="null,true); fn("
// hack which caused JSON.parse to throw inside the click delegate.
// ============================================================================
window.openBulkRenameFromMenu = function () {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.openBulkRename === 'function') window.openBulkRename();
};

window.openMoveCopyDialogFromMenu = function (mode) {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.openMoveCopyDialog === 'function') window.openMoveCopyDialog(mode);
};

window.openDuplicatesModalFromMenu = function () {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.openDuplicatesModal === 'function') window.openDuplicatesModal();
};

window.downloadFilesCsvFromMenu = function () {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.downloadFilesCsv === 'function') window.downloadFilesCsv();
};

window.downloadBoxesCsvFromMenu = function () {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.downloadBoxesCsv === 'function') window.downloadBoxesCsv();
};


// ============================================================================
// [FRONTEND:new-features] Новые функции: ONNX, Active Learning, Keypoint Schema,
// ML classifier, Streams.
// ============================================================================

// ---------- 2.1: ONNX export ----------
async function exportModelOnnx(name) {
  if (!name) return;
  const ok = await window.showConfirm(
    window.t('models.onnx.export'),
    window.t('models.onnx.confirm', { name }),
    { okText: window.t('models.onnx.export') }
  );
  if (!ok) return;
  window.setStatus(window.t('models.onnx.exporting', { name }), 120000);
  try {
    const fd = new FormData();
    fd.append('dynamic', 'true');
    const r = await api(
      `/api/models/${encodeURIComponent(name)}/export_onnx`,
      { method: 'POST', body: fd }
    );
    const sizeMb = (r.size / (1024 * 1024)).toFixed(1);
    window.setSuccess(
      window.t('models.onnx.done', { file: r.onnx_name, size: sizeMb }), 6000);
    window.haptic && window.haptic('success');
  } catch (e) {
    window.setError(
      window.t('models.onnx.error', { msg: String(e.message).slice(0, 160) }), 8000);
  }
}

// ---------- 3.1: Active Learning Queue ----------
async function _loadUncertainImages() {
  if (!currentProjectId) return;
  window.showImageSkeleton && window.showImageSkeleton();
  window.setStatus(window.t('al.uncertain.loading'), 8000);
  try {
    const q = await api(
      `/api/projects/${currentProjectId}/active_learning_queue?limit=500`);
    const items = (q && q.items) || [];
    if (!items.length) {
      allImages = [];
      imagesList = [];
      _imagesHasMore = false;
      _imagesTotalInProject = 0;
      _imagesAnnotatedInProject = 0;
      applyFiltersAndRender();
      window.setStatus(window.t('al.uncertain.empty'), 5000);
      return;
    }
    const ids = items.map(x => x.image_id).filter(x => Number.isFinite(x));
    const raw = await api(`/api/projects/${currentProjectId}/images?limit=0`);
    const metaList = Array.isArray(raw) ? raw : (raw.items || []);
    const map = new Map(metaList.map(x => [x.id, x]));
    allImages = [];
    for (const it of items) {
      const m = map.get(it.image_id);
      if (!m) continue;
      m._max_conf = it.max_conf;
      m._in_band = !!it.in_uncertainty_band;
      allImages.push(m);
    }
    _imagesHasMore = false;
    _imagesTotalInProject = allImages.length;
    _imagesAnnotatedInProject = 0;
    applyFiltersAndRender();
  } catch (e) {
    console.warn('active_learning_queue failed:', e);
    allImages = []; imagesList = [];
    renderImageList();
    window.setError(
      window.t('al.uncertain.error', { msg: String(e.message || e).slice(0, 160) }), 8000);
  }
}

// ---------- 2.3: Keypoint Schema editor ----------
let _kpschemaCurrentSchema = null;
let _kpschemaCurrentSource = 'default';
let _kpschemaProjectId = null;

async function _loadKeypointSchemaForProject(projectId) {
  _kpschemaProjectId = projectId;
  try {
    const r = await api(`/api/projects/${projectId}/keypoint_schema`);
    _kpschemaCurrentSource = r.source || 'default';
    _kpschemaCurrentSchema = Array.isArray(r.schema) ? r.schema.map(p => ({
      name: p.name || '',
      label_ru: p.label_ru || '',
      label_en: p.label_en || '',
      parent: p.parent || '',
    })) : [];
    _renderKeypointSchemaEditor();
  } catch (e) {
    console.warn('load keypoint_schema failed:', e);
    const host = document.getElementById('kpschemaEditor');
    if (host) host.innerHTML = '<div style="padding:8px;color:var(--text-secondary);font-size:0.75rem;">Не удалось загрузить схему</div>';
  }
}

function _renderKeypointSchemaEditor() {
  const host = document.getElementById('kpschemaEditor');
  const badge = document.getElementById('kpschemaBadge');
  const count = document.getElementById('kpschemaCount');
  if (!host) return;
  host.innerHTML = '';
  if (!_kpschemaCurrentSchema || !_kpschemaCurrentSchema.length) {
    host.innerHTML = '<div style="padding:10px;text-align:center;color:var(--text-secondary);font-size:0.75rem;">'
                     + window.t('kpschema.empty') + '</div>';
    if (badge) badge.innerHTML = '';
    if (count) count.textContent = '';
    return;
  }
  const tbl = document.createElement('table');
  tbl.className = 'kpschema-tbl';
  const thead = document.createElement('thead');
  thead.innerHTML = '<tr>'
    + '<th data-i18n="kpschema.col_name">' + window.t('kpschema.col_name') + '</th>'
    + '<th data-i18n="kpschema.col_ru">' + window.t('kpschema.col_ru') + '</th>'
    + '<th data-i18n="kpschema.col_en">' + window.t('kpschema.col_en') + '</th>'
    + '<th data-i18n="kpschema.col_parent">' + window.t('kpschema.col_parent') + '</th>'
    + '<th></th></tr>';
  tbl.appendChild(thead);
  const tbody = document.createElement('tbody');
  _kpschemaCurrentSchema.forEach((pt, idx) => {
    _appendKeypointRow(tbody, pt, idx);
  });
  tbl.appendChild(tbody);
  host.appendChild(tbl);
  if (badge) {
    const b = document.createElement('span');
    b.className = 'kpschema-badge ' + (_kpschemaCurrentSource === 'custom' ? 'custom' : 'default');
    b.textContent = window.t('kpschema.badge.' + (_kpschemaCurrentSource === 'custom' ? 'custom' : 'default'));
    badge.innerHTML = '';
    badge.appendChild(b);
  }
  if (count) {
    count.textContent = _kpschemaCurrentSchema.length + ' точек';
  }
}

function _appendKeypointRow(tbody, pt, idx) {
  const tr = document.createElement('tr');
  ['name', 'label_ru', 'label_en', 'parent'].forEach(field => {
    const td = document.createElement('td');
    const inp = document.createElement('input');
    inp.value = pt[field] || '';
    inp.placeholder = field;
    inp.dataset.field = field;
    inp.addEventListener('input', () => {
      _kpschemaCurrentSchema[idx][field] = inp.value;
    });
    td.appendChild(inp);
    tr.appendChild(td);
  });
  const tdDel = document.createElement('td');
  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'kpschema-del';
  del.textContent = '×';
  del.setAttribute('aria-label', 'Удалить точку');
  del.onclick = () => {
    _kpschemaCurrentSchema.splice(idx, 1);
    _renderKeypointSchemaEditor();
  };
  tdDel.appendChild(del);
  tr.appendChild(tdDel);
  tbody.appendChild(tr);
}

function _addKeypointRow() {
  if (!_kpschemaCurrentSchema) _kpschemaCurrentSchema = [];
  _kpschemaCurrentSchema.push({ name: '', label_ru: '', label_en: '', parent: '' });
  _renderKeypointSchemaEditor();
  const host = document.getElementById('kpschemaEditor');
  if (host) {
    const rows = host.querySelectorAll('tbody tr');
    const last = rows[rows.length - 1];
    const firstInp = last && last.querySelector('input');
    if (firstInp) firstInp.focus();
  }
}

async function _saveKeypointSchema() {
  if (!_kpschemaProjectId) return;
  const schema = (_kpschemaCurrentSchema || []).filter(p => (p.name || '').trim());
  if (!schema.length) { window.setStatus(window.t('kpschema.err_empty'), 4000); return; }
  if (!schema.every(p => (p.name || '').trim())) {
    window.setStatus(window.t('kpschema.err_name'), 4000); return;
  }
  try {
    const r = await api(
      `/api/projects/${_kpschemaProjectId}/keypoint_schema`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema }),
      }
    );
    _kpschemaCurrentSource = 'custom';
    _renderKeypointSchemaEditor();
    window.setSuccess(window.t('kpschema.saved', { n: r.count || schema.length }), 4000);
    window.haptic && window.haptic('success');
  } catch (e) {
    window.setError(String(e.message).slice(0, 160), 6000);
  }
}

async function _resetKeypointSchema() {
  if (!_kpschemaProjectId) return;
  const ok = await window.showConfirm(
    window.t('kpschema.reset'),
    'Сбросить схему к дефолтной 17-точечной?',
    { okText: window.t('kpschema.reset'), danger: true }
  );
  if (!ok) return;
  try {
    await api(`/api/projects/${_kpschemaProjectId}/keypoint_schema`,
                     { method: 'DELETE' });
    window.setStatus(window.t('kpschema.reset_done'), 3000);
    await _loadKeypointSchemaForProject(_kpschemaProjectId);
  } catch (e) {
    window.setError(String(e.message).slice(0, 160), 6000);
  }
}

// ---------- 3.2: ML behavior classifier ----------

// [FIX:v1341-frontend] classifier status refresh
async function _refreshClassifierMeta(projectId) {
  const el = document.getElementById('projectClassifierStatus');
  if (!el || !projectId) return;
  el.innerHTML = '<span style="color:var(--text-secondary);">Загрузка…</span>';
  try {
    const r = await api(`/api/projects/${projectId}/behavior/classifier_meta`);
    el.innerHTML = '';
    if (!r || !r.exists) {
      el.style.color = 'var(--text-secondary)';
      el.textContent = window.t('classifier.not_trained');
      return;
    }
    const curClass = (window._projectModalTarget && window._projectModalTarget.object_class) || '';
    const trainedClass = r.object_class || '';
    const mismatch = curClass && trainedClass && curClass !== trainedClass;
    const line = document.createElement('div');
    line.textContent = window.t('classifier.trained', {
      n: r.n_samples || 0,
      classes: (r.classes || []).join(', '),
    });
    line.style.color = mismatch ? 'var(--warning)' : 'var(--success)';
    el.appendChild(line);
    if (mismatch) {
      const warn = document.createElement('div');
      warn.style.cssText = 'color:var(--warning); margin-top:3px;';
      warn.textContent = window.t('classifier.wrong_class', {
        trained: trainedClass, current: curClass,
      });
      el.appendChild(warn);
    }
  } catch (e) {
    el.textContent = '?';
  }
}
window._refreshClassifierMeta = _refreshClassifierMeta;

async function trainBehaviorClassifier() {
  const pid = (_projectModalTarget && _projectModalTarget.id) || currentProjectId;
  if (!pid) { window.setStatus(window.t('toast.pickProject')); return; }
  window.setStatus(window.t('train.classifier.running'), 120000);
  try {
    const r = await api(
      `/api/projects/${pid}/behavior/train_classifier`,
      { method: 'POST' }
    );
    if (r.error) {
      window.setError(String(r.error).slice(0, 200), 8000);
      return;
    }
    window.setSuccess(
      window.t('train.classifier.done', {
        n: r.n_samples,
        classes: (r.classes || []).join(', ').slice(0, 120),
      }), 8000);
    window.haptic && window.haptic('success');
    try { await _refreshClassifierMeta(pid); } catch (e) {}
  } catch (e) {
    window.setError(
      window.t('train.classifier.error', { msg: String(e.message).slice(0, 160) }), 8000);
  }
}

// ---------- 3.3: RTSP Streams ----------
async function openStreamMgmtModal() {
  if (!currentProjectId) { window.setStatus(window.t('toast.pickProject')); return; }
  if (window.openModal) window.openModal('streamMgmtModal');
  await _refreshStreamsList();
}

function closeStreamMgmtModal() {
  if (window.closeModal) window.closeModal('streamMgmtModal');
}

async function _refreshStreamsList() {
  const list = document.getElementById('streamsList');
  if (!list || !currentProjectId) return;
  list.innerHTML = '<div style="color:var(--text-secondary);font-size:0.8125rem;padding:8px;">'
                   + window.t('common.loading') + '</div>';
  try {
    const rows = await api(`/api/projects/${currentProjectId}/streams`);
    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) {
      list.innerHTML = '<div style="color:var(--text-secondary);font-size:0.8125rem;text-align:center;padding:20px 0;">'
                       + window.t('streams.empty') + '</div>';
      return;
    }
    list.innerHTML = '';
    items.forEach(s => {
      const row = document.createElement('div');
      row.className = 'stream-row' + (s.is_active ? '' : ' inactive');

      const info = document.createElement('div');
      info.className = 'stream-info';
      const name = document.createElement('div');
      name.className = 'stream-name';
      name.textContent = s.name || ('Stream #' + s.id);
      const url = document.createElement('div');
      url.className = 'stream-url';
      url.textContent = s.url;
      info.appendChild(name);
      info.appendChild(url);
      row.appendChild(info);

      const st = document.createElement('span');
      st.className = 'stream-status ' + (s.is_active ? 'active' : 'inactive');
      st.textContent = window.t(s.is_active ? 'streams.active' : 'streams.inactive');
      row.appendChild(st);

      if (s.is_active) {
        const stopBtn = document.createElement('button');
        stopBtn.type = 'button';
        stopBtn.className = 'stream-stop';
        stopBtn.textContent = window.t('streams.stop');
        stopBtn.onclick = async () => {
          try {
            await api(
              `/api/projects/${currentProjectId}/streams/${s.id}/stop`,
              { method: 'POST' }
            );
            window.setSuccess(window.t('streams.stopped'), 3000);
            await _refreshStreamsList();
          } catch (e) {
            window.setError(
              window.t('streams.error', { msg: String(e.message).slice(0, 160) }), 6000);
          }
        };
        row.appendChild(stopBtn);
      }
      list.appendChild(row);
    });
  } catch (e) {
    list.innerHTML = '<div style="color:var(--danger);font-size:0.8125rem;">'
                     + window.t('streams.error', { msg: window.escapeHtml(String(e.message)) })
                     + '</div>';
  }
}

async function createStream() {
  if (!currentProjectId) return;
  const urlEl = document.getElementById('streamUrlInput');
  const nameEl = document.getElementById('streamNameInput');
  const url = (urlEl && urlEl.value || '').trim();
  const name = (nameEl && nameEl.value || '').trim();
  if (!url) { window.setStatus(window.t('streams.url_required'), 4000); return; }
  try {
    await api(`/api/projects/${currentProjectId}/streams`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, name: name || undefined }),
    });
    if (urlEl) urlEl.value = '';
    if (nameEl) nameEl.value = '';
    window.setSuccess(window.t('streams.created'), 3000);
    window.haptic && window.haptic('success');
    await _refreshStreamsList();
  } catch (e) {
    window.setError(
      window.t('streams.error', { msg: String(e.message).slice(0, 160) }), 6000);
  }
}

// ---------- window bindings ----------
window.exportModelOnnx = exportModelOnnx;
window._loadUncertainImages = _loadUncertainImages;
window._loadKeypointSchemaForProject = _loadKeypointSchemaForProject;
window._renderKeypointSchemaEditor = _renderKeypointSchemaEditor;
window._addKeypointRow = _addKeypointRow;
window._saveKeypointSchema = _saveKeypointSchema;
window._resetKeypointSchema = _resetKeypointSchema;
window.trainBehaviorClassifier = trainBehaviorClassifier;
window.openStreamMgmtModal = openStreamMgmtModal;
window.closeStreamMgmtModal = closeStreamMgmtModal;
window.createStream = createStream;
window._refreshStreamsList = _refreshStreamsList;

// data-action-обёртки для HTML
window.addKeypointRow = function () { _addKeypointRow(); };
window.saveKeypointSchema = function () { _saveKeypointSchema(); };
window.resetKeypointSchema = function () { _resetKeypointSchema(); };

document.addEventListener('DOMContentLoaded', async () => {
  setTimeout(makeModalsDraggable, 100);

  // [STAGE1:auth-gate] Team Mode: block UI until authenticated
  try {
    const _ar = await fetch('/api/auth/status', { credentials: 'same-origin' });
    const _auth = await _ar.json();
    window.AUTH_STATE = { mode: _auth.mode, user: _auth.user };
    if (_auth.mode === 'team') {
      if (_auth.needs_setup) {
        const _le = document.getElementById('loginError');
        if (_le) {
          _le.textContent = 'Требуется первичная настройка: POST /api/setup/admin {username, password}';
          _le.style.display = 'block';
        }
        window.openModal('loginModal');
        return;
      }
      if (!_auth.is_authenticated) {
        try {
          localStorage.removeItem('pdb_user');
          localStorage.removeItem('pdb_token');
        } catch (_ee) {}
        window.openModal('loginModal');
        return;
      }
    }
  } catch (_e) { console.warn('[auth-gate]', _e); }
  // [/STAGE1:auth-gate]

  initEventDelegation();
  installCanvasListeners();
  installKeyboardListeners();
  _installTooltipObserver();
  _installThemeRadiogroup();
  _installDropZone();
  _installLangSegment();
  if (window.applyI18nToDOM) window.applyI18nToDOM();
  applyTheme();
  if (window.setHideHints) window.setHideHints(window.getHideHints ? window.getHideHints() : false);
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
      // [PATCH:STAGE1_DEV_MODE_INIT] Developer Mode
      const _devCbInit = document.getElementById('developerModeToggle'); // [PATCH:FIX_DEV_MODE_ID]
      if (_devCbInit) {
        _devCbInit.checked = _getDevMode();
        _devCbInit.addEventListener('change', (e) => _setDevMode(e.target.checked));
        if (_getDevMode()) setTimeout(_startDevPanel, 500);
      }
      // [/PATCH:STAGE1_DEV_MODE_INIT]
  const _tourBtn = document.getElementById('tourBtn');
  if (_tourBtn) _tourBtn.addEventListener('click', () => window.startTour());
  // Авто-запуск при первом визите
  try {
    if (!localStorage.getItem('pdb_tour_done')) {
      setTimeout(() => window.startTour(), 1500);
    }
  } catch (e) {}
  const _singleCb = document.getElementById('useSingleModelToggle');
  if (_singleCb) _singleCb.addEventListener('change', () => setModelMode(_singleCb.checked));
  const dlFam = document.getElementById('downloadFamily');
  const dlTsk = document.getElementById('downloadTask');
  if (dlFam) dlFam.addEventListener('change', _updateDownloadSelects);
  if (dlTsk) dlTsk.addEventListener('change', _updateDownloadSelects);
  _updateDownloadSelects();

  // [FIX:train-ui] Listeners for training modal
  const trainFamEl = document.getElementById('trainFamily');
  const trainBaseEl = document.getElementById('trainBaseModel');
  if (trainFamEl) trainFamEl.addEventListener('change', _updateTrainSelects);
  if (trainBaseEl) trainBaseEl.addEventListener('change', _updateTrainSelects);

  // V8.3.0: панель атрибутов
  _installAttrBar();
  // [FIX:v1341-frontend] auto-blur UI handlers
  const _abToggle = document.getElementById('autoBlurToggle');
  if (_abToggle) _abToggle.addEventListener('change', () => {
    _projectAutoBlurEnabled = !!_abToggle.checked;
    const blk = document.getElementById('autoBlurClassesBlock');
    if (blk) blk.style.display = _projectAutoBlurEnabled ? 'flex' : 'none';
    _validateProjectForm();
  });
  document.querySelectorAll('[data-blur-class]').forEach(cb => {
    cb.addEventListener('change', () => {
      _projectAutoBlurClasses = Array.from(
        document.querySelectorAll('[data-blur-class]:checked')
      ).map(c => c.dataset.blurClass);
      _validateProjectForm();
    });
  });
  _refreshAttrBar();
  // V8.5.1: скелет
  loadKeypointSchema(currentProjectId).catch(() => {});
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
                  loginModal: () => window.closeLogin(),
                  usersModal: () => window.closeUsersModal(),
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
    trackPlayerModal: () => closeTrackPlayer(),
    guideModal: () => closeGuide(),   // V8.8.4
    // [PATCH:close-handlers] standard backdrop-close for these two modals
    webhooksModal: () => { if (window.closeWebhooksModal) window.closeWebhooksModal(); },
    datasetVersionsModal: () => { if (window.closeDatasetVersionsModal) window.closeDatasetVersionsModal(); },
    streamMgmtModal: () => { if (window.closeStreamMgmtModal) window.closeStreamMgmtModal(); },
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
    .then(s => {
      if (s.status === 'running') {
        batchRunning = true;
        subscribeBatchEvents();
        // V10.4.1: страница перезагружена посреди батча — восстанавливаем кнопку.
        startOperation('batch', () => api('/api/autolabel/batch/stop', { method: 'POST' }));
      }
    })
    .catch(() => {});
  setTimeout(checkModelsAvailability, 1500);
  // [V13.2.0:pipeline-restore]
  if (currentProjectId) {
    api(`/api/projects/${currentProjectId}/pipeline/status`).then(ps => {
      if (ps.status === 'running' || ps.status === 'stopping') {
        _openPipelineModal();
        document.getElementById('pipelineForm').style.display = 'none';
        document.getElementById('pipelineProgressWrap').style.display = '';
        document.getElementById('pipelineStartBtn').style.display = 'none';
        document.getElementById('pipelineStopBtn').style.display = '';
        _renderPipelineState(ps);
        _subscribePipelineEvents();
      }
    }).catch(() => {});
  }
});





// V13.3.2: Unified global deselect (единый обработчик)
document.addEventListener('pointerdown', (e) => {
  const el = e.target;
  if (!el || typeof el.closest !== 'function') return;

  // Игнорируем клики внутри холста (canvas.js сам справится)
  if (el.closest('#canvasViewport')) return;
  // Игнорируем панели, работающие с рамками
  if (el.closest('.toolbar') || el.closest('.attr-bar') || el.closest('.tag-chips-bar')) return;
  // Игнорируем модалки и меню
  if (el.closest('.modal-backdrop.open, .sort-menu.open, .custom-select.open, .class-search-menu, .command-palette-backdrop, #global-tooltip, .tour-overlay')) return;

  if (typeof window.clearSelection === 'function') {
    window.clearSelection();
  }
}, { capture: true });




// ============================================================================
// [STAGE3:ui-blur] Размытие областей (blur regions)
// ============================================================================
window._currentBlurRegions = [];

window._loadBlurRegions = async function() {
  if (!window.currentImageId) return;
  try {
    const r = await api(`/api/images/${window.currentImageId}/blur_regions`);
    window._currentBlurRegions = Array.isArray(r) ? r : [];
  } catch (e) {
    window._currentBlurRegions = [];
  }
  window._renderBlurOverlay();
};

window._renderBlurOverlay = function() {
  const stage = document.getElementById('canvasStage');
  if (!stage) return;
  let layer = document.getElementById('blurLayer');
  if (!layer) {
    layer = document.createElement('div');
    layer.id = 'blurLayer';
    layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:9;';
    stage.appendChild(layer);
  }
  layer.innerHTML = '';
  (window._currentBlurRegions || []).forEach(r => {
    const d = document.createElement('div');
    d.style.cssText = `position:absolute;left:${r.x*640}px;top:${r.y*640}px;width:${r.w*640}px;height:${r.h*640}px;background:rgba(0,0,0,0.85);border:1px dashed rgba(255,255,255,0.4);border-radius:4px;`;
    layer.appendChild(d);
  });
};

window.blurSelectedRegions = async function() {
  if (!window.currentImageId) { window.setStatus && window.setStatus('Сначала открой фото'); return; }
  const idx = (window.getSelectedIndices ? window.getSelectedIndices() : [])
              .filter(i => window.AppState.boxes[i]);
  if (!idx.length) {
    window.setStatus && window.setStatus('Выдели рамки для размытия', 3000);
    return;
  }
  const regions = idx.map(i => {
    const b = window.AppState.boxes[i];
    return { x: b.x, y: b.y, w: b.w, h: b.h };
  });
  try {
    const cur = await api(`/api/images/${window.currentImageId}/blur_regions`);
    const merged = (Array.isArray(cur) ? cur : []).concat(regions);
    await api(`/api/images/${window.currentImageId}/blur_regions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(merged),
    });
    await window._loadBlurRegions();
    window.setStatus && window.setStatus(`Размыто областей: ${merged.length}`);
    if (window.haptic) window.haptic('success');
    // Force reload image to show blurred version
    const imgEl = document.getElementById('image');
    if (imgEl && imgEl.src) {
      const t = Date.now();
      imgEl.src = `/api/images/${window.currentImageId}/file?t=${t}`;
    }
  } catch (e) {
    window.setError && window.setError('Ошибка размытия: ' + String(e.message).slice(0, 160));
  }
};

window.clearBlurRegions = async function() {
  if (!window.currentImageId) return;
  try {
    await api(`/api/images/${window.currentImageId}/blur_regions`, { method: 'DELETE' });
    window._currentBlurRegions = [];
    window._renderBlurOverlay();
    const imgEl = document.getElementById('image');
    if (imgEl && imgEl.src) {
      const t = Date.now();
      imgEl.src = `/api/images/${window.currentImageId}/file?t=${t}`;
    }
    window.setStatus && window.setStatus('Области размытия очищены');
    if (window.haptic) window.haptic('selection');
  } catch (e) {
    window.setError && window.setError('Ошибка: ' + String(e.message).slice(0, 160));
  }
};




// ============================================================================
// [STAGE3:ui-versions] Версии датасета
// ============================================================================
window.createVersionSnapshot = async function() {
  const pid = window.currentProjectId;
  if (!pid) { window.setStatus && window.setStatus('Выбери проект'); return; }
  try {
    const r = await api(`/api/projects/${pid}/version`, {
      method: 'POST',
      headers: { 'X-Requested-With': 'DatasetBuilder' },
    });
    window.setSuccess && window.setSuccess(`Snapshot: ${r.hash.slice(0, 12)}… (${r.image_count} фото, ${r.annotation_count} рамок)`, 6000);
    if (window.haptic) window.haptic('success');
  } catch (e) {
    window.setError && window.setError('Ошибка snapshot: ' + String(e.message).slice(0, 160));
  }
};




window._refreshWebhooksList = async function() {
  const pid = window.currentProjectId;
  if (!pid) return;
  const list = document.getElementById('webhooksList');
  if (!list) return;
  list.innerHTML = '<div style="color:var(--text-secondary);font-size:0.8125rem;padding:8px;">Загрузка…</div>';
  try {
    const rows = await api(`/api/projects/${pid}/webhooks`);
    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) {
      list.innerHTML = '<div style="color:var(--text-secondary);font-size:0.8125rem;text-align:center;padding:20px 0;">Подписок пока нет.</div>';
      return;
    }
    list.innerHTML = '';
    items.forEach(wh => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;background:var(--bg-hover);font-size:0.8125rem;';
      const info = document.createElement('div');
      info.style.cssText = 'flex:1;min-width:0;overflow:hidden;';
      info.innerHTML = `
        <div style="font-family:ui-monospace,monospace;font-size:0.75rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${window.escapeHtml(wh.url)}</div>
        <div style="font-size:0.6875rem;color:var(--text-secondary);margin-top:2px;">
          ${wh.event_type} · ${wh.active ? '✓ active' : '✗ off'}${wh.has_secret ? ' · 🔐 secret' : ''}
        </div>`;
      row.appendChild(info);
      const testBtn = document.createElement('button');
      testBtn.className = 'btn btn-ghost btn-sm'; testBtn.textContent = 'test';
      testBtn.onclick = async () => {
        try {
          const r = await api(`/api/webhooks/${wh.id}/test`, { method: 'POST', headers: {'X-Requested-With':'DatasetBuilder'} });
          if (r.ok) window.setSuccess && window.setSuccess('Webhook OK');
          else window.setError && window.setError('Webhook failed');
        } catch (e) { window.setError && window.setError(String(e.message).slice(0, 120)); }
      };
      row.appendChild(testBtn);
      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'btn btn-ghost btn-sm'; toggleBtn.textContent = wh.active ? 'off' : 'on';
      toggleBtn.onclick = async () => {
        try {
          await api(`/api/webhooks/${wh.id}/toggle`, { method: 'POST', headers: {'X-Requested-With':'DatasetBuilder'} });
          await window._refreshWebhooksList();
        } catch (e) { window.setError && window.setError(String(e.message).slice(0, 120)); }
      };
      row.appendChild(toggleBtn);
      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-ghost btn-sm'; delBtn.textContent = '✕';
      delBtn.style.color = 'var(--danger)';
      delBtn.onclick = async () => {
        if (!confirm('Удалить webhook?')) return;
        try {
          await api(`/api/webhooks/${wh.id}`, { method: 'DELETE', headers: {'X-Requested-With':'DatasetBuilder'} });
          await window._refreshWebhooksList();
        } catch (e) { window.setError && window.setError(String(e.message).slice(0, 120)); }
      };
      row.appendChild(delBtn);
      list.appendChild(row);
    });
  } catch (e) {
    list.innerHTML = '<div style="color:var(--danger);font-size:0.8125rem;">Ошибка: ' + window.escapeHtml(String(e.message)) + '</div>';
  }
};


window.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    if (typeof window.selectImage !== 'function' || window.selectImage.__stage3Hooked) return;
    const orig = window.selectImage;
    const wrapped = async function(...args) {
      await orig.apply(this, args);
      try { await window._loadBlurRegions(); } catch (e) {}
    };
    wrapped.__stage3Hooked = true;
    window.selectImage = wrapped;
  }, 200);
});




// ============================================================================
// [STAGE4:fix-modals] Прямое открытие модалок versions/webhooks.
// Обходит конфликты z-index и MODAL_STACK — принудительный display:flex + z-index:9999.
// ============================================================================




window._blurDrawMode = false;
window._blurDrawing = null;

window.toggleBlurMode = function () {
  window._blurDrawMode = !window._blurDrawMode;
  const btn = document.getElementById('attrBlurBtn');
  if (btn) {
    btn.classList.toggle('active', window._blurDrawMode);
    btn.textContent = window._blurDrawMode ? '🔒 blur ON' : '🔒 blur mode';
  }
  const vp = document.getElementById('canvasViewport');
  if (vp) {
    vp.style.cursor = window._blurDrawMode ? 'crosshair' : '';
    vp.classList.toggle('blur-mode', window._blurDrawMode);
  }
  window.setStatus && window.setStatus(
    window._blurDrawMode
      ? 'Blur mode ON: рисуй прямоугольник на фоне (свиней не трогай). Кнопка ещё раз — выйти.'
      : 'Blur mode OFF',
    window._blurDrawMode ? 6000 : 2500
  );
};

(function _initBlurDrawHandlers() {
  const vp = document.getElementById('canvasViewport');
  if (!vp || vp.__blurBound) return;
  vp.__blurBound = true;

  vp.addEventListener('pointerdown', (e) => {
    if (!window._blurDrawMode) return;
    if (e.button !== 0) return;
    if (!window.currentImageId) return;
    e.preventDefault();
    e.stopPropagation();
    const rect = vp.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    window._blurDrawing = { startX: x, startY: y, curX: x, curY: y };
    let preview = document.getElementById('blurPreview');
    if (!preview) {
      preview = document.createElement('div');
      preview.id = 'blurPreview';
      preview.style.cssText =
        'position:absolute;background:rgba(0,0,0,0.55);border:2px dashed #fff;' +
        'pointer-events:none;z-index:9999;border-radius:4px;';
      vp.appendChild(preview);
    }
    preview.style.display = 'block';
    preview.style.left = (x * 100) + '%';
    preview.style.top = (y * 100) + '%';
    preview.style.width = '0';
    preview.style.height = '0';
  }, { capture: true });

  vp.addEventListener('pointermove', (e) => {
    if (!window._blurDrawing) return;
    const rect = vp.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    window._blurDrawing.curX = x;
    window._blurDrawing.curY = y;
    const x1 = Math.min(window._blurDrawing.startX, x);
    const y1 = Math.min(window._blurDrawing.startY, y);
    const x2 = Math.max(window._blurDrawing.startX, x);
    const y2 = Math.max(window._blurDrawing.startY, y);
    const p = document.getElementById('blurPreview');
    if (p) {
      p.style.left = (x1 * 100) + '%';
      p.style.top = (y1 * 100) + '%';
      p.style.width = ((x2 - x1) * 100) + '%';
      p.style.height = ((y2 - y1) * 100) + '%';
    }
  }, { capture: true });

  vp.addEventListener('pointerup', async (e) => {
    if (!window._blurDrawing) return;
    const d = window._blurDrawing;
    window._blurDrawing = null;
    const p = document.getElementById('blurPreview');
    if (p) p.style.display = 'none';
    const x1 = Math.min(d.startX, d.curX);
    const y1 = Math.min(d.startY, d.curY);
    const w = Math.abs(d.curX - d.startX);
    const h = Math.abs(d.curY - d.startY);
    if (w < 0.01 || h < 0.01) return;
    try {
      const cur = await api(
        '/api/images/' + window.currentImageId + '/blur_regions'
      );
      const merged = (Array.isArray(cur) ? cur : []).concat([{ x: x1, y: y1, w: w, h: h }]);
      await api(
        '/api/images/' + window.currentImageId + '/blur_regions',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(merged),
        }
      );
      const imgEl = document.getElementById('image');
      if (imgEl && imgEl.src) {
        imgEl.src = '/api/images/' + window.currentImageId + '/file?t=' + Date.now();
      }
      window.setStatus && window.setStatus('Область размыта (нажми 🧹 чтобы очистить)');
      window.haptic && window.haptic('success');
    } catch (err) {
      window.setError && window.setError('Blur: ' + String(err.message).slice(0, 140));
    }
  }, { capture: true });
})();




// ============================================================================
// [STAGE5:force-modals] Форсированное открытие versions/webhooks.
// Обходит баг с animation: backdropIn → opacity:0.
// ============================================================================



// Переопределяем открытие/закрытие с force



// [PATCH:stage5-kd-removed] blanket keydown handler removed — handled by closeHandlers + keyboard.js

// Клик по backdrop тоже закрывает
// [PATCH:stage5-md-removed] blanket mousedown handler removed — handled by closeHandlers




// ============================================================================
// [STAGE5:smart-skeleton-click] Умный клик для скелета при zoom > 1.
//
// Проблема: при zoom > 1 клик по пустому месту запускал pan вместо постановки точки.
// Шифт-клик ставил невидимую точку, требовал двух кликов чтобы сделать видимой.
//
// Решение: pointerdown → pointermove → pointerup.
//   - Сдвиг < 3px — считаем кликом → ставим точку (visibility=1.0)
//   - Сдвиг > 3px — считаем панорамированием
//
// Не трогает:
//   - drag существующих точек (.skeleton-point)
//   - клики по рамкам (там своя логика выделения)
//   - shift+клик (ставит невидимую точку — оставляем как fallback)
//   - zoom <= 1 (там нет pan-конфликта)
// ============================================================================

(function _initSmartSkeletonClick() {
  if (window.__smartSkelBound) return;
  window.__smartSkelBound = true;

  const CLICK_THRESHOLD_PX = 3;

  window.addEventListener('pointerdown', (e) => {
    // Условия активации
    if (!window.skeletonMode) return;
    if (window.AppState.zoom <= 1) return;  // при zoom <=1 нет конфликта — работает оригинал
    if (e.button !== 0) return;
    if (window.spacePressed) return;
    if (e.shiftKey) return;  // shift оставляем оригиналу (невидимая точка)
    if (!window.currentImageId) return;

    const t = e.target;
    if (!t || typeof t.closest !== 'function') return;
    // [STAGE7:smart-click-fix]
    if (!t.closest('#canvasViewport')) return;
    if (t.closest('.sidebar, .modal-backdrop, .status-bar, .toolbar, .attr-bar')) return;

    // Не перехватываем: точки, рамки, handles, edges, удаление
    if (t.classList && t.classList.contains('skeleton-point')) return;
    if (t.classList && t.classList.contains('handle')) return;
    if (t.classList && t.classList.contains('box-edge')) return;
    if (t.classList && t.classList.contains('box-delete')) return;
    if (t.closest('.box')) return;
    if (t.closest('.zoom-controls')) return;
    if (t.closest('.zoom-badge')) return;
    if (t.closest('.attr-bar')) return;
    if (t.closest('.toolbar')) return;

    // Нет выделенной рамки → пусть pan работает как раньше (ставит точку некуда)
    if (typeof window._targetAnnotationId === 'function' && window._targetAnnotationId() < 0) {
      return;
    }

    // Перехватываем: не даём оригинальному canvas.js запустить pan
    e.stopImmediatePropagation();
    e.preventDefault();

    const startX = e.clientX;
    const startY = e.clientY;
    const panStart = {
      x: startX - window.AppState.panX,
      y: startY - window.AppState.panY,
    };
    let isPan = false;
    let moved = false;

    const vp = document.getElementById('canvasViewport');

    function onMove(ev) {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (!isPan && Math.hypot(dx, dy) > CLICK_THRESHOLD_PX) {
        isPan = true;
        moved = true;
        window.isPanning = true;
        window.panStart = panStart;
        vp.classList.add('panning');
      }
      if (isPan) {
        window.AppState.panX = ev.clientX - panStart.x;
        window.AppState.panY = ev.clientY - panStart.y;
        window.clampPan && window.clampPan();
        window.applyTransform && window.applyTransform();
      }
    }

    function onUp(ev) {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
      window.removeEventListener('pointercancel', onUp, true);

      if (isPan) {
        window.isPanning = false;
        vp.classList.remove('panning');
        return;
      }
      if (moved) return;

      // Чистый клик — ставим точку
      const rect = vp.getBoundingClientRect();
      const vx = ev.clientX - rect.left;
      const vy = ev.clientY - rect.top;
      const nx = ((vx - window.AppState.panX) / window.AppState.zoom) / 640;
      const ny = ((vy - window.AppState.panY) / window.AppState.zoom) / 640;
      if (nx < 0 || nx > 1 || ny < 0 || ny > 1) return;
      if (typeof window._placeNextKeypoint === 'function') {
        window._placeNextKeypoint(nx, ny, 1.0);
      }
    }

    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
    window.addEventListener('pointercancel', onUp, true);
  }, true);  // capture — раньше обработчика в canvas.js
})();




// ============================================================================
// [STAGE6:programmatic-modals] Модалки создаются через createElement —
// не зависят от CSS animations и от того, вставлены ли они в index.html.
//
// Причина бага: `@keyframes backdropIn` иногда застревает на opacity:0
// в Chrome на Windows (GPU-баг). Программное создание + inline-стили
// с !important полностью обходит проблему.
// ============================================================================


// --- VERSIONS ---


window._refreshWebhooksList = async function (container) {
  const pid = window.currentProjectId;
  const list = document.getElementById('webhooksListInner') || container;
  if (!pid || !list) return;
  list.innerHTML = '<div style="color:var(--text-secondary,#666);font-size:0.8125rem;padding:8px;">Загрузка…</div>';
  try {
    const rows = await api('/api/projects/' + pid + '/webhooks');
    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) {
      list.innerHTML = '<div style="color:var(--text-secondary,#666);font-size:0.8125rem;text-align:center;padding:20px 0;">Подписок пока нет.</div>';
      return;
    }
    list.innerHTML = '';
    items.forEach(wh => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;background:rgba(0,0,0,0.04);font-size:0.8125rem;';
      const info = document.createElement('div');
      info.style.cssText = 'flex:1;min-width:0;overflow:hidden;';
      const urlDiv = document.createElement('div');
      urlDiv.style.cssText = 'font-family:ui-monospace,monospace;font-size:0.75rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-primary,#000);';
      urlDiv.textContent = wh.url;
      info.appendChild(urlDiv);
      const metaDiv = document.createElement('div');
      metaDiv.style.cssText = 'font-size:0.6875rem;color:var(--text-secondary,#666);margin-top:2px;';
      metaDiv.textContent = wh.event_type + ' · ' + (wh.active ? '✓ active' : '✗ off') +
                            (wh.has_secret ? ' · 🔐 secret' : '');
      info.appendChild(metaDiv);
      row.appendChild(info);

      const testBtn = document.createElement('button');
      testBtn.type = 'button';
      testBtn.className = 'btn btn-ghost btn-sm';
      testBtn.textContent = 'test';
      testBtn.onclick = async () => {
        try {
          const r = await api('/api/webhooks/' + wh.id + '/test', {
            method: 'POST', headers: { 'X-Requested-With': 'DatasetBuilder' },
          });
          if (r.ok) window.setSuccess && window.setSuccess('Webhook OK');
          else window.setError && window.setError('Webhook failed');
        } catch (e) { window.setError && window.setError(String(e.message).slice(0, 120)); }
      };
      row.appendChild(testBtn);

      const toggleBtn = document.createElement('button');
      toggleBtn.type = 'button';
      toggleBtn.className = 'btn btn-ghost btn-sm';
      toggleBtn.textContent = wh.active ? 'off' : 'on';
      toggleBtn.onclick = async () => {
        try {
          await api('/api/webhooks/' + wh.id + '/toggle', {
            method: 'POST', headers: { 'X-Requested-With': 'DatasetBuilder' },
          });
          await window._refreshWebhooksList(container);
        } catch (e) { window.setError && window.setError(String(e.message).slice(0, 120)); }
      };
      row.appendChild(toggleBtn);

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn btn-ghost btn-sm';
      delBtn.textContent = '✕';
      delBtn.style.color = 'var(--danger,#f00)';
      delBtn.onclick = async () => {
        if (!confirm('Удалить webhook?')) return;
        try {
          await api('/api/webhooks/' + wh.id, {
            method: 'DELETE', headers: { 'X-Requested-With': 'DatasetBuilder' },
          });
          await window._refreshWebhooksList(container);
        } catch (e) { window.setError && window.setError(String(e.message).slice(0, 120)); }
      };
      row.appendChild(delBtn);
      list.appendChild(row);
    });
  } catch (e) {
    list.innerHTML = '<div style="color:var(--danger,#f00);font-size:0.8125rem;">Ошибка: ' +
                     window.escapeHtml(String(e.message)) + '</div>';
  }
};



window._stage6Download = async function (path, filename) {
  try {
    window.setStatus && window.setStatus('Готовим файл…', 30000);
    const res = await fetch(path);
    if (!res.ok) {
      let msg = 'HTTP ' + res.status;
      try { msg = (await res.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
    window.setSuccess && window.setSuccess('Скачано: ' + filename);
  } catch (e) {
    window.setError && window.setError('Ошибка: ' + String(e.message).slice(0, 200));
  }
};

window.exportCvatXml = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window._stage6Download('/api/projects/' + pid + '/export/cvat',
                         'cvat_project_' + pid + '.xml');
};

window.downloadDatasetCard = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window._stage6Download('/api/projects/' + pid + '/dataset_card',
                         'dataset_card_' + pid + '.md');
};

window.exportParquet = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window._stage6Download('/api/projects/' + pid + '/export/parquet',
                         'parquet_project_' + pid + '.zip');
};

window.exportSql = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window._stage6Download('/api/projects/' + pid + '/export/sql',
                         'sql_project_' + pid + '.sql');
};


window.openExportPlusModal = function () {
  const m = document.getElementById('exportPlusModal');
  if (!m) {
    window.setError && window.setError('exportPlusModal не найден — Ctrl+F5');
    return;
  }
  m.classList.remove('closing');
  m.classList.add('open');
  m.style.display = 'flex';
  m.style.zIndex = '99999';
  m.style.opacity = '1';
  m.style.animation = 'none';
  if (window.MODAL_STACK && !window.MODAL_STACK.includes('exportPlusModal')) {
    window.MODAL_STACK.push('exportPlusModal');
  }
};
window.closeExportPlusModal = function () {
  const m = document.getElementById('exportPlusModal');
  if (m) {
    m.classList.remove('open');
    m.style.display = '';
    m.style.zIndex = '';
    m.style.opacity = '';
  }
  if (window.MODAL_STACK) {
    const i = window.MODAL_STACK.indexOf('exportPlusModal');
    if (i >= 0) window.MODAL_STACK.splice(i, 1);
  }
};




// ============================================================================
// [STAGE7:fixes] Модалки, интерполяция, экспорт
// ============================================================================

// 1. Модалки через родной openModal (CSS-фикс из stage5 уже решает баг)


window.openInterpolateDialog = async function () {
  if (!window.currentProjectId || !window.currentImageId) { window.setStatus && window.setStatus('Выбери проект и кадр'); return; }
  const sel = window.getSelectedIndices();
  if (!sel.length) { window.setStatus && window.setStatus('Сначала выдели рамку'); return; }
  const box = window.AppState.boxes[sel[0]];
  if (box.animal_id == null) { window.setError && window.setError('У рамки нет animal_id'); return; }
  const curAnnId = window._currentAnnIds ? window._currentAnnIds[sel[0]] : null;
  if (!curAnnId) { window.setError && window.setError('Не удалось определить ID текущей аннотации'); return; }

  try {
    window.setStatus && window.setStatus('Поиск предыдущего кадра…', 5000);
    const nav = await api(`/api/projects/${window.currentProjectId}/navigate_with_aid?from_image_id=${window.currentImageId}&animal_id=${box.animal_id}&dir=prev`);
    if (!nav.found) { window.setError && window.setError('Не найдено предыдущего кадра с этим animal_id'); return; }

    const prevAnns = await api(`/api/images/${nav.image_id}/annotations`);
    const prevAnn = prevAnns.find(a => a.animal_id === box.animal_id);
    if (!prevAnn) { window.setError && window.setError('На предыдущем кадре нет рамки с этим animal_id'); return; }

    window.setStatus && window.setStatus('Интерполяция…', 5000);
    const r = await api(`/api/projects/${window.currentProjectId}/interpolate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'DatasetBuilder' },
      body: JSON.stringify({
        animal_id: box.animal_id,
        from_ann_id: prevAnn.id,
        to_ann_id: curAnnId
      })
    });
    window.setSuccess && window.setSuccess(`Интерполировано ${r.interpolated_frames} кадров (animal_id=${box.animal_id})`);
    if (typeof window.loadImages === 'function') window.loadImages();
  } catch (e) {
    window.setError && window.setError('Ошибка интерполяции: ' + String(e.message).slice(0, 160));
  }
};

// 3. Функции экспорта
window.exportCvatXml = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window.downloadFile(`/api/projects/${pid}/export/cvat`, `cvat_project_${pid}.xml`);
};

window.downloadDatasetCard = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window.downloadFile(`/api/projects/${pid}/dataset_card`, `dataset_card_${pid}.md`);
};

window.exportParquet = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window.downloadFile(`/api/projects/${pid}/export/parquet`, `parquet_project_${pid}.zip`);
};

window.exportSql = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window.downloadFile(`/api/projects/${pid}/export/sql`, `sql_project_${pid}.sql`);
};

// [PATCH:STAGE2_2:agtech-csv-export]
window.exportAgtechCsv = function () {
  const pid = window.currentProjectId;
  if (!pid) { if (window.setStatus) window.setStatus('Выбери проект'); return; }
  window.downloadFile(
    `/api/projects/${pid}/export/agtech_csv`,
    `agtech_events_project_${pid}.csv`,
  );
};
// [/PATCH:STAGE2_2:agtech-csv-export]



window.openInterpolateDialog = async function () {
  if (!window.currentProjectId || !window.currentImageId) { window.setStatus && window.setStatus('Выбери проект и кадр'); return; }
  const sel = window.getSelectedIndices();
  if (!sel.length) { window.setStatus && window.setStatus('Сначала выдели рамку'); return; }
  const box = window.AppState.boxes[sel[0]];
  if (box.animal_id == null) { window.setError && window.setError('У рамки нет animal_id'); return; }
  const curAnnId = window._currentAnnIds ? window._currentAnnIds[sel[0]] : null;
  if (!curAnnId) { window.setError && window.setError('Не удалось определить ID текущей аннотации'); return; }

  try {
    window.setStatus && window.setStatus('Поиск предыдущего кадра…', 5000);
    const nav = await api(`/api/projects/${window.currentProjectId}/navigate_with_aid?from_image_id=${window.currentImageId}&animal_id=${box.animal_id}&dir=prev`);
    if (!nav.found) { window.setError && window.setError('Не найдено предыдущего кадра с этим animal_id'); return; }

    const prevAnns = await api(`/api/images/${nav.image_id}/annotations`);
    const prevAnn = prevAnns.find(a => a.animal_id === box.animal_id);
    if (!prevAnn) { window.setError && window.setError('На предыдущем кадре нет рамки с этим animal_id'); return; }

    window.setStatus && window.setStatus('Интерполяция…', 5000);
    const r = await api(`/api/projects/${window.currentProjectId}/interpolate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'DatasetBuilder' },
      body: JSON.stringify({
        animal_id: box.animal_id,
        from_ann_id: prevAnn.id,
        to_ann_id: curAnnId
      })
    });
    window.setSuccess && window.setSuccess(`Интерполировано ${r.interpolated_frames} кадров (animal_id=${box.animal_id})`);
    if (typeof window.loadImages === 'function') window.loadImages();
  } catch (e) {
    window.setError && window.setError('Ошибка интерполяции: ' + String(e.message).slice(0, 160));
  }
};

window.exportCvatXml = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window.downloadFile(`/api/projects/${pid}/export/cvat`, `cvat_project_${pid}.xml`);
};

window.downloadDatasetCard = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window.downloadFile(`/api/projects/${pid}/dataset_card`, `dataset_card_${pid}.md`);
};

window.exportParquet = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window.downloadFile(`/api/projects/${pid}/export/parquet`, `parquet_project_${pid}.zip`);
};

window.exportSql = function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');
  window.downloadFile(`/api/projects/${pid}/export/sql`, `sql_project_${pid}.sql`);
};


// [STAGE9:js-cleanup]



// ============================================================================
// [STAGE9:clean-modals] Полностью программные модалки. Никаких HTML-зависимостей.
// Создаются с нуля через createElement, вставляются в body, удаляются при закрытии.
// 100% защита от любых CSS-багов, конфликтов z-index и засорения MODAL_STACK.
// ============================================================================



window.runAsyncAutolabel = async function () {
  const pid = window.currentProjectId;
  if (!pid) return window.setStatus && window.setStatus('Выбери проект');

  // Блокируем кнопку
  const btn = document.querySelector('button[data-action="runAsyncAutolabel"]');
  if (btn) btn.disabled = true;

  try {
    const r = await api(`/api/v2/projects/${pid}/autolabel`, {
      method: 'POST', headers: { 'X-Requested-With': 'DatasetBuilder' }
    });

    window.setStatus && window.setStatus('Фоновая разметка запущена (можно закрыть вкладку)', 4000);

    // Визуализация в полоске прогресса тулбара
    const fill = document.getElementById('progressFill');
    const label = document.getElementById('progressLabel');
    const text = document.getElementById('progressText');
    const bar = document.getElementById('progressBar');

    if (fill) {
      fill.style.width = '0%';
      fill.classList.add('batch');
    }
    if (label) label.textContent = 'Async Autolabel';
    if (text) text.textContent = 'Запуск...';
    if (bar) bar.setAttribute('aria-valuenow', '0');

    let tries = 0;
    const poll = setInterval(async () => {
      tries++;
      try {
        const st = await api(`/api/v2/tasks/${r.task_id}`);

        // Обновляем UI
        if (fill && st.progress != null) fill.style.width = st.progress + '%';
        if (bar && st.progress != null) bar.setAttribute('aria-valuenow', Math.round(st.progress));
        if (text) text.textContent = st.message || `${Math.round(st.progress || 0)}%`;

        if (st.status === 'done') {
          clearInterval(poll);
          if (btn) btn.disabled = false;

          window.setSuccess && window.setSuccess(`Async autolabel готов (${st.result?.images || '?'} фото)`);

          if (fill) fill.style.width = '100%';
          if (label) label.textContent = 'Готово';
          if (text) text.textContent = `Размечено: ${st.result?.images || '?'}`;

          // Сбрасываем полоску через 3 секунды
          setTimeout(() => {
            if (fill) { fill.style.width = '0%'; fill.classList.remove('batch'); }
            if (label) label.textContent = 'Размечено';
            if (typeof window.loadImages === 'function') window.loadImages();
            if (typeof window.updateProgress === 'function') window.updateProgress();
          }, 3000);

        } else if (st.status === 'error') {
          clearInterval(poll);
          if (btn) btn.disabled = false;
          window.setError && window.setError('Async autolabel: ' + (st.error || 'ошибка'));
          if (fill) fill.classList.remove('batch');
          if (label) label.textContent = 'Размечено';
          if (typeof window.updateProgress === 'function') window.updateProgress();
        } else if (tries > 900) {
          // Таймаут 30 минут
          clearInterval(poll);
          if (btn) btn.disabled = false;
        }
      } catch (e) {
        clearInterval(poll);
        if (btn) btn.disabled = false;
        window.setError && window.setError('Ошибка поллинга: ' + String(e.message).slice(0, 120));
      }
    }, 1500);

  } catch (e) {
    if (btn) btn.disabled = false;
    window.setError && window.setError('Не удалось запустить Async: ' + String(e.message).slice(0, 160));
  }
};


// [STAGE11:js-cleanup]



// ============================================================================
// [STAGE11:native-modals] Плавные модалки на базе window.openModal
// ============================================================================







// [STAGE12:js-cleanup]



// ============================================================================
// [STAGE12:clean-modals] Родные модалки из index.html (плавные, как все)
// ============================================================================

window.openDatasetVersionsModal = async function () {
  const pid = window.currentProjectId;
  if (!pid) { window.setStatus && window.setStatus(window.t('toast.pickProject')); return; }
  if (window.openModal) window.openModal('datasetVersionsModal');

  const body = document.getElementById('dsVersionsBody');
  if (!body) return;
  body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;text-align:center;padding:20px 0;">' + window.t('common.loading') + '</p>';

  try {
    const rows = await api('/api/projects/' + pid + '/versions');
    const items = Array.isArray(rows) ? rows : [];
    body.innerHTML = '';

    if (!items.length) {
      body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;text-align:center;padding:24px 0;">Версий пока нет. Нажми «💾 snapshot» в панели атрибутов.</p>';
      return;
    }

    const list = document.createElement('div');
    list.style.cssText = 'max-height: 45vh; overflow-y: auto; padding-right: 6px;';

    items.forEach(v => {
      const row = document.createElement('label');
      row.className = 'version-row';
      row.dataset.createdAt = v.created_at || '';
      row.dataset.versionId = String(v.id || 0);
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'version-cb';
      cb.dataset.hash = v.hash;
      cb.addEventListener('change', () => {
        const checked = body.querySelectorAll('.version-cb:checked');
        if (checked.length > 2) {
          cb.checked = false;
        }
        row.classList.toggle('checked', cb.checked);
        _updateVersionsCompareBtn(body);
      });
      row.appendChild(cb);

      const info = document.createElement('div');
      info.style.cssText = 'flex:1; min-width:0;';
      const hashLine = document.createElement('div');
      hashLine.className = 'ver-hash';
      hashLine.textContent = v.hash;
      const metaLine = document.createElement('div');
      metaLine.className = 'ver-meta';
      metaLine.textContent = v.image_count + ' фото · ' +
                              v.annotation_count + ' рамок · ' +
                              ((v.created_at || '').replace('T', ' ').slice(0, 19));
      info.appendChild(hashLine);
      info.appendChild(metaLine);
      row.appendChild(info);

      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'btn btn-ghost btn-sm ver-copy';
      copyBtn.textContent = window.t('versions.diff.copy');
      copyBtn.onclick = (e) => {
        e.preventDefault(); e.stopPropagation();
        navigator.clipboard.writeText(v.hash).then(
          () => window.setStatus && window.setStatus('hash скопирован'));
      };
      row.appendChild(copyBtn);

      list.appendChild(row);
    });
    body.appendChild(list);

    // [FRONTEND:versions-diff]
    const actions = document.createElement('div');
    actions.className = 'versions-actions';
    actions.id = 'versionsActions';
    const cmpBtn = document.createElement('button');
    cmpBtn.type = 'button';
    cmpBtn.className = 'btn btn-primary btn-sm';
    cmpBtn.id = 'versionsCompareBtn';
    cmpBtn.textContent = window.t('versions.diff.btn');
    cmpBtn.disabled = true;
    cmpBtn.onclick = () => _compareVersions(pid, body);
    actions.appendChild(cmpBtn);
    body.appendChild(actions);

    const diffHost = document.createElement('div');
    diffHost.id = 'versionsDiffHost';
    body.appendChild(diffHost);
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger,#f00);font-size:0.8125rem;">' +
                     window.t('error.load', { msg: String(e.message || e) }) + '</p>';
  }
};

function _updateVersionsCompareBtn(body) {
  const btn = body.querySelector('#versionsCompareBtn');
  const checked = body.querySelectorAll('.version-cb:checked');
  if (btn) btn.disabled = checked.length !== 2;
}

async function _compareVersions(pid, body) {
  const checked = Array.from(body.querySelectorAll('.version-cb:checked'));
  if (checked.length !== 2) {
    window.setStatus && window.setStatus(window.t('versions.diff.pick_two'));
    return;
  }
  // [FIX:v1341-frontend] сортировка: h1 = старая, h2 = новая
  const _items = checked.map(cb => {
    const row = cb.closest('.version-row');
    return {
      hash: cb.dataset.hash,
      createdAt: row.dataset.createdAt || '',
      versionId: parseInt(row.dataset.versionId || '0', 10),
    };
  });
  _items.sort((a, b) => {
    if (a.createdAt !== b.createdAt) return a.createdAt.localeCompare(b.createdAt);
    return a.versionId - b.versionId;
  });
  const [h1, h2] = _items.map(x => x.hash);
  const host = body.querySelector('#versionsDiffHost');
  if (!host) return;
  host.innerHTML = '<div style="padding:8px 0;color:var(--text-secondary);font-size:0.8125rem;">' + window.t('common.loading') + '</div>';
  try {
    const d = await api(
      `/api/projects/${pid}/versions/diff?hash1=${encodeURIComponent(h1)}&hash2=${encodeURIComponent(h2)}`
    );
    host.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'versions-diff' + (d.is_identical ? ' identical' : '');
    const title = document.createElement('div');
    title.className = 'versions-diff-title';
    title.textContent = window.t('versions.diff.header',
                                  { h1: h1.slice(0, 12) + '…',
                                    h2: h2.slice(0, 12) + '…' });
    wrap.appendChild(title);

    if (d.is_identical) {
      const msg = document.createElement('div');
      msg.style.cssText = 'font-weight:600; padding:6px 0;';
      msg.textContent = '✓ ' + window.t('versions.diff.identical');
      wrap.appendChild(msg);
    } else {
      const rows = [
            ['images_added',        'added'],
            ['images_removed',      'removed'],
            ['annotations_added',   'added'],
            ['annotations_removed', 'removed'],
            ['keypoints_added',     'added'],
            ['keypoints_removed',   'removed'],
            ['behaviors_added',     'added'],
            ['behaviors_removed',   'removed'],
        ]; // [PATCH:VERSION_DIFF_KP_BEH]
      rows.forEach(([key, cls]) => {
        const r = document.createElement('div');
        r.className = 'versions-diff-row ' + cls;
        const lbl = document.createElement('span');
        lbl.textContent = window.t('versions.diff.' + key);
        const val = document.createElement('b');
        val.textContent = (d[key] != null ? d[key] : 0);
        r.appendChild(lbl); r.appendChild(val);
        wrap.appendChild(r);
      });
    }
    host.appendChild(wrap);
    window.haptic && window.haptic('selection');
  } catch (e) {
    host.innerHTML = '<div style="color:var(--danger);padding:8px 0;font-size:0.8125rem;">' +
                     window.escapeHtml(String(e.message || e)) + '</div>';
  }
}

window._updateVersionsCompareBtn = _updateVersionsCompareBtn;
window._compareVersions = _compareVersions;

window.closeDatasetVersionsModal = function () {
  // [STAGE3:close] removeProperty handles !important correctly

  // [PATCH:close-cleanup-versions] reset inline styles set by bulletproof open
  const el = document.getElementById('datasetVersionsModal');
  if (el) {
    el.style.removeProperty('display');
    el.style.removeProperty('opacity');
    el.style.removeProperty('visibility');
    el.style.removeProperty('z-index');
  }
  if (window.closeModal) window.closeModal('datasetVersionsModal');
};

window.openWebhooksModal = async function () {
  const pid = window.currentProjectId;
  if (!pid) { window.setStatus && window.setStatus('Выбери проект'); return; }

  if (window.openModal) window.openModal('webhooksModal');
  if (typeof window.refreshWebhooksList === 'function') window.refreshWebhooksList();
};

window.closeWebhooksModal = function () {
  // [STAGE3:close] removeProperty handles !important correctly

  // [PATCH:close-cleanup-webhooks] reset inline styles set by bulletproof open
  const el = document.getElementById('webhooksModal');
  if (el) {
    el.style.removeProperty('display');
    el.style.removeProperty('opacity');
    el.style.removeProperty('visibility');
    el.style.removeProperty('z-index');
  }
  if (window.closeModal) window.closeModal('webhooksModal');
};

window.createWebhook = async function () {
  const pid = window.currentProjectId;
  if (!pid) return;

  const url = document.getElementById('whUrlInput').value.trim();
  const eventType = document.getElementById('whEventSelect').value;
  const secret = document.getElementById('whSecretInput').value.trim();

  if (!url) { window.setStatus && window.setStatus('Введи URL'); return; }

  try {
    await api('/api/projects/' + pid + '/webhooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'DatasetBuilder' },
      body: JSON.stringify({ url, event_type: eventType, secret_key: secret })
    });
    document.getElementById('whUrlInput').value = '';
    document.getElementById('whSecretInput').value = '';
    if (typeof window.refreshWebhooksList === 'function') window.refreshWebhooksList();
    window.setSuccess && window.setSuccess('Webhook создан');
  } catch (e) {
    window.setError && window.setError('Ошибка: ' + String(e.message).slice(0, 160));
  }
};

window.refreshWebhooksList = async function () {
  const pid = window.currentProjectId;
  const list = document.getElementById('webhooksList');
  if (!pid || !list) return;

  list.innerHTML = '<div style="color:var(--text-secondary,#666);font-size:0.8125rem;padding:8px;">Загрузка…</div>';
  try {
    const rows = await api('/api/projects/' + pid + '/webhooks');
    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) {
      list.innerHTML = '<div style="color:var(--text-secondary,#666);font-size:0.8125rem;text-align:center;padding:20px 0;">Подписок пока нет.</div>';
      return;
    }
    list.innerHTML = '';
    items.forEach(wh => {
      const whRow = document.createElement('div');
      whRow.style.cssText = 'display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;background:rgba(0,0,0,0.04);font-size:0.8125rem;';
      whRow.innerHTML = '<div style="flex:1;min-width:0;overflow:hidden;">' +
        '<div style="font-family:ui-monospace,monospace;font-size:0.75rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-primary,#000);">' + window.escapeHtml(wh.url) + '</div>' +
        '<div style="font-size:0.6875rem;color:var(--text-secondary,#666);margin-top:2px;">' + wh.event_type + ' · ' + (wh.active ? '✓ active' : '✗ off') + (wh.has_secret ? ' · 🔐 secret' : '') + '</div></div>';

      const testBtn = document.createElement('button');
      testBtn.className = 'btn btn-ghost btn-sm';
      testBtn.textContent = 'test';
      testBtn.onclick = async () => {
        try { const r = await api('/api/webhooks/' + wh.id + '/test', { method: 'POST', headers: { 'X-Requested-With': 'DatasetBuilder' } }); if (r.ok) window.setSuccess('Webhook OK'); else window.setError('Webhook failed'); } catch (e) { window.setError(String(e.message).slice(0,120)); }
      };
      whRow.appendChild(testBtn);

      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-ghost btn-sm';
      delBtn.textContent = '✕';
      delBtn.style.color = 'var(--danger,#f00)';
      delBtn.onclick = async () => {
        if (!confirm('Удалить?')) return;
        try { await api('/api/webhooks/' + wh.id, { method: 'DELETE', headers: { 'X-Requested-With': 'DatasetBuilder' } }); window.refreshWebhooksList(); } catch (e) {}
      };
      whRow.appendChild(delBtn);
      list.appendChild(whRow);
    });
  } catch (e) {
    list.innerHTML = '<div style="color:var(--danger,#f00);font-size:0.8125rem;">Ошибка: ' + window.escapeHtml(String(e.message)) + '</div>';
  }
};



// [STAGE5:I18N-USE]

// [PATCH:STAGE2_1:track-metrics-ui]
window._computeTrackMetrics = async function () {
  if (!window.currentProjectId) {
    if (window.setStatus) window.setStatus('Выбери проект');
    return;
  }
  try {
    const vids = await api(`/api/projects/${window.currentProjectId}/videos`);
    if (!vids || !vids.length) {
      if (window.setStatus) window.setStatus('В проекте нет видео');
      return;
    }
    let vid = vids[0].id;
    if (vids.length > 1) {
      const vlist = vids.map(v => `${v.id}: ${v.filename}`).join('\n');
      const input = await window.showPrompt('ID видео для расчёта метрик', {
        defaultValue: String(vid),
        hint: 'Доступные:\n' + vlist,
        okText: 'Рассчитать',
      });
      if (!input) return;
      vid = parseInt(input, 10);
      if (isNaN(vid)) return;
    }
    const m = await api(`/api/videos/${vid}/track/metrics`);
    let msg;
    if (m.mota != null) {
      msg = `📊 Метрики видео #${vid}\n\n`
          + `MOTA:  ${(m.mota * 100).toFixed(2)}%\n`
          + `IDF1:  ${(m.idf1 * 100).toFixed(2)}%\n`
          + `GT:    ${m.gt_count} рамок\n`
          + `Pred:  ${m.pred_count} рамок`;
    } else {
      msg = `⚠ Метрики недоступны\n\n${m.hint || m.reason || 'unknown'}`;
    }
    if (window.showAlert) await window.showAlert('📊 Оценка трекинга', msg);
    else alert(msg);
    if (window.haptic) window.haptic('selection');
  } catch (e) {
    if (window.setError) window.setError('Метрики: ' + String(e.message).slice(0, 200));
  }
};
// [/PATCH:STAGE2_1:track-metrics-ui]

// [PATCH:STAGE2_3:rbac-frontend]
window.openUsersModal = async function () {
  try {
    const me = await api('/api/auth/me');
    if (!me || me.role !== 'admin') {
      if (window.setStatus) window.setStatus('Доступно только администратору');
      return;
    }
    window.openModal('usersModal');
    await window._refreshUsersList();
  } catch (e) {
    if (window.setError) window.setError('Пользователи: ' + String(e.message).slice(0, 160));
  }
};

window.closeUsersModal = function () { window.closeModal('usersModal'); };

window._refreshUsersList = async function () {
  const list = document.getElementById('usersList');
  if (!list) return;
  list.innerHTML = '<div style="color:var(--text-secondary);padding:8px;">Загрузка…</div>';
  try {
    const r = await api('/api/users');
    const items = (r && r.items) || [];
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML =
        '<div style="color:var(--text-secondary);text-align:center;padding:12px 0;">Пользователей пока нет</div>';
      return;
    }
    items.forEach(u => {
      const row = document.createElement('div');
      row.style.cssText =
        'display:flex;align-items:center;gap:8px;padding:8px 10px;background:var(--bg-hover);border-radius:8px;';
      const info = document.createElement('div');
      info.style.cssText = 'flex:1;';
      const icon = u.is_active ? '🟢' : '🔴';
      info.innerHTML = icon
        + ' <b>' + window.escapeHtml(String(u.username || '')) + '</b>'
        + ' <span style="color:var(--text-secondary);font-size:0.75rem;">· '
        + window.escapeHtml(String(u.role || '')) + '</span>';
      row.appendChild(info);
      const delBtn = document.createElement('button');
      delBtn.className = 'btn btn-ghost btn-sm';
      delBtn.textContent = '✕';
      delBtn.style.color = 'var(--danger)';
      delBtn.onclick = async () => {
        const _okDel = await window.showConfirm('Удалить пользователя?', 'Пользователь ' + u.username + ' будет удалён.'); if (!_okDel) return;
        try {
          await api('/api/users/' + u.id, { method: 'DELETE' });
          await window._refreshUsersList();
        } catch (e) {
          if (window.setError) window.setError(String(e.message).slice(0, 160));
        }
      };
      row.appendChild(delBtn);
      list.appendChild(row);
    });
  } catch (e) {
    list.innerHTML =
      '<div style="color:var(--danger);padding:8px;">Ошибка: '
      + window.escapeHtml(String(e.message)) + '</div>';
  }
};

window.createUserBtn = async function () {
  const u = (document.getElementById('newUserUsername').value || '').trim();
  const p = document.getElementById('newUserPassword').value || '';
  const r = document.getElementById('newUserRole').value || 'annotator';
  if (!u) { if (window.setStatus) window.setStatus('Введите username'); return; }
  try {
    await api('/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p, role: r }),
    });
    document.getElementById('newUserUsername').value = '';
    document.getElementById('newUserPassword').value = '';
    if (window.setSuccess) window.setSuccess('Пользователь создан');
    await window._refreshUsersList();
  } catch (e) {
    if (window.setError) window.setError(String(e.message).slice(0, 160));
  }
};

document.addEventListener('DOMContentLoaded', () => {
  setTimeout(async () => {
    try {
      const me = await api('/api/auth/me');
      if (me && me.role === 'admin') {
        const btn = document.getElementById('usersBtn');
        if (btn) btn.style.display = '';
      }
    } catch (e) { /* silent */ }
  }, 400);
});
// [/PATCH:STAGE2_3:rbac-frontend]

// [PATCH:STAGE3_1:validate-behavior-frontend]
window._validateBehavior = async function () {
  if (!window.currentImageId || !window.currentProjectId) {
    if (window.setStatus) window.setStatus('Выбери изображение');
    return;
  }
  const trueLabel = await window.showPrompt(
    'Истинное поведение (Ground Truth)',
    {
      hint: 'eat / walk / lie / drink / stand / active',
      okText: 'Проверить',
    }
  );
  if (!trueLabel) return;
  const norm = String(trueLabel).trim().toLowerCase();
  const VALID = ['eat', 'walk', 'lie', 'drink', 'stand', 'active'];
  if (VALID.indexOf(norm) < 0) {
    if (window.setStatus) window.setStatus('Недопустимое поведение: ' + norm);
    return;
  }
  try {
    const r = await api(
      `/api/projects/${window.currentProjectId}/validate_behavior`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_id: window.currentImageId,
          true_behavior: norm,
        }),
      }
    );
    const btn = document.getElementById('attrValidateBehBtn');
    if (btn) {
      btn.style.boxShadow = r.is_match
        ? '0 0 0 2px var(--success)'
        : '0 0 0 2px var(--danger)';
      setTimeout(function () { btn.style.boxShadow = ''; }, 4000);
    }
    if (r.is_match) {
      if (window.setSuccess) window.setSuccess(
        `✓ Валидация: "${norm}" совпадает с авто (${r.auto_behavior})`);
    } else {
      if (window.setError) window.setError(
        `✗ Валидация: авто="${r.auto_behavior}", эксперта="${r.true_behavior}"`);
    }
    if (window.haptic) window.haptic(r.is_match ? 'success' : 'warning');
  } catch (e) {
    if (window.setError) window.setError(
      'Валидация: ' + String(e.message).slice(0, 160));
  }
};
// [/PATCH:STAGE3_1:validate-behavior-frontend]

// [PATCH:STAGE3_2:edge-package-frontend]
window.downloadEdgePackage = function (name) {
  if (!name) return;
  const safe = encodeURIComponent(name);
  const stem = String(name).replace(/\.(pt|onnx)$/i, '');
  window.downloadFile(
    `/api/models/${safe}/edge_package`,
    `edge_package_${stem}.zip`,
  );
};
// [/PATCH:STAGE3_2:edge-package-frontend]


// [FIX_V2:data-quality-modal]
window.openDataQualityModal = function () {
  if (window.setStatus) window.setStatus('Запуск валидатора разметки...');
  if (typeof window.openValidateModal === 'function') {
    window.openValidateModal();
  } else {
    if (window.setError) window.setError('Валидатор недоступен');
  }
};

// [FIX_V2:draggable-modals]
function makeModalsDraggable() {
  document.querySelectorAll('.modal').forEach(modal => {
    const header = modal.querySelector('h2') || modal.querySelector('.modal-header');
    if (!header || header.dataset.dragInit) return;
    header.dataset.dragInit = '1';
    header.style.cursor = 'move';

    let isDragging = false, startX, startY, startLeft, startTop;

    header.addEventListener('mousedown', (e) => {
      if (['INPUT', 'BUTTON', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = modal.getBoundingClientRect();
      startLeft = rect.left;
      startTop = rect.top;

      modal.style.position = 'fixed';
      modal.style.margin = '0';
      modal.style.left = startLeft + 'px';
      modal.style.top = startTop + 'px';
      modal.style.transform = 'none';
      modal.style.animation = 'none'; // Отключаем анимацию появления, чтобы не дёргалось

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    });

    function onMouseMove(e) {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      modal.style.left = (startLeft + dx) + 'px';
      modal.style.top = (startTop + dy) + 'px';
    }

    function onMouseUp() {
      isDragging = false;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    }
  });
}
// [/FIX_V2:draggable-modals]

// [HOTFIX:auth-logic]
window.openLogin = function () {
  document.getElementById('loginError').style.display = 'none';
  window.openModal('loginModal');
};
window.closeLogin = function () { window.closeModal('loginModal'); };
window.submitLogin = async function () {
  // [STAGE2:login-real] Cookie-based auth via js/auth.js
  const u = (document.getElementById('loginUsername').value || '').trim();
  const p = document.getElementById('loginPassword').value || '';
  const err = document.getElementById('loginError');
  err.style.display = 'none';
  if (!u || !p) {
    err.textContent = 'Введите логин и пароль';
    err.style.display = 'block';
    return;
  }
  try {
    const mod = await import('./auth.js');
    const user = await mod.login(u, p);
    try { localStorage.setItem('pdb_user', JSON.stringify(user)); } catch (e) {}
    window.closeLogin();
    window.location.reload();
  } catch (e) {
    err.textContent = String(e.message || 'Ошибка входа');
    err.style.display = 'block';
  }
};
window.logout = async function () {
  // [STAGE1:logout-cookie] Revoke server-side session too
  try {
    await fetch('/api/auth/logout', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-Requested-With': 'DatasetBuilder' }
    });
  } catch (e) {}
  localStorage.removeItem('pdb_token');
  localStorage.removeItem('pdb_user');
  window.location.reload();
};
document.addEventListener('DOMContentLoaded', () => {
  try {
    const u = JSON.parse(localStorage.getItem('pdb_user'));
    if (u) {
      const loginBtn = document.getElementById('loginBtn');
      if (loginBtn) {
                        loginBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`;
                        loginBtn.setAttribute('title', `Выйти (${u.username})`);
                        loginBtn.removeAttribute('data-action');
                        const newBtn = loginBtn.cloneNode(true);
                        loginBtn.parentNode.replaceChild(newBtn, loginBtn);
                        newBtn.addEventListener('click', () => window.logout());
                      }
      if (u.role !== 'admin') {
        const sBtn = document.getElementById('settingsBtn');
        if (sBtn) sBtn.style.display = 'none';
        const uBtn = document.getElementById('usersBtn');
        if (uBtn) uBtn.style.display = 'none';
      }
    }
  } catch(e) {}
});
// [/HOTFIX:auth-logic]

// [FIX:S-KEY]
window.addEventListener('keydown', (e) => {
  if ((e.code === 'KeyS' || e.key === 's' || e.key === 'ы') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const tag = (e.target && e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    e.preventDefault();
    if (typeof window.saveAnnotations === 'function') window.saveAnnotations();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    const metaCb = document.querySelector('input[value*="meta"], input[id*="meta"]');
    if (metaCb) metaCb.checked = true;
  }, 500);
});


// ============================================================================
// [STAGE2:auth-hooks] Change-password handlers, auth-required hook,
// must-change-password boot, permissions boot.
// ============================================================================
(function _installAuthHooks() {
  // -- change-password modal --
  window.openChangePassword = function () {
    const el = document.getElementById('changePasswordModal');
    if (!el) { console.warn('[STAGE2] changePasswordModal missing'); return; }
    document.getElementById('cpError').style.display = 'none';
    ['cpOldPw', 'cpNewPw', 'cpNewPw2'].forEach(id => {
      const i = document.getElementById(id); if (i) i.value = '';
    });
    window.openModal('changePasswordModal');
  };
  window.closeChangePassword = function () {
    window.closeModal('changePasswordModal');
  };
  window.submitChangePassword = async function () {
    const err = document.getElementById('cpError');
    err.style.display = 'none';
    const oldPw = document.getElementById('cpOldPw').value;
    const newPw = document.getElementById('cpNewPw').value;
    const newPw2 = document.getElementById('cpNewPw2').value;
    if (newPw.length < 8) {
      err.textContent = 'Пароль минимум 8 символов';
      err.style.display = 'block'; return;
    }
    if (newPw !== newPw2) {
      err.textContent = 'Пароли не совпадают';
      err.style.display = 'block'; return;
    }
    try {
      const mod = await import('./auth.js');
      await mod.changePassword(oldPw, newPw);
      window.closeChangePassword();
      if (typeof window.setSuccess === 'function') window.setSuccess('Пароль изменён');
    } catch (e) {
      err.textContent = String(e.message || e);
      err.style.display = 'block';
    }
  };

  // -- 401 → open login --
  window.addEventListener('pdb-auth-required', () => {
    if (typeof window.isModalOpen === 'function' && window.isModalOpen('loginModal')) return;
    if (typeof window.openLogin === 'function') window.openLogin();
  });

  // -- must_change_password: force change on first login --
  setTimeout(async () => {
    try {
      const mod = await import('./auth.js');
      if (!mod.AUTH_STATE.loaded) await mod.loadAuthStatus();
      const u = mod.AUTH_STATE.user;
      if (u && u.must_change_password) {
        if (typeof window.openChangePassword === 'function') window.openChangePassword();
      }
    } catch (e) {}
  }, 800);
})();
// [/STAGE2:auth-hooks]


// ============================================================================
// [STAGE4:workflow-hooks] assign modal, my-tasks filter, review actions
// ============================================================================
(function _installStage4Hooks() {
  // --- my tasks filter ---
  window._filterMyTasksActive = false;
  setTimeout(() => {
    const wrap = document.getElementById('filterMyTasksWrap');
    const authState = window.AUTH_STATE || {};
    const show = authState.mode === 'team' && authState.user
              && ['annotator', 'reviewer'].includes(authState.user.role);
    if (wrap) wrap.style.display = show ? '' : 'none';

    const cb = document.getElementById('filterMyTasks');
    if (cb) cb.addEventListener('change', () => {
      window._filterMyTasksActive = cb.checked;
      if (typeof window.loadImages === 'function') window.loadImages();
    });
  }, 700);

  // --- assign modal ---
  window.openAssignModal = async function () {
    const sel = Array.from(window.selectedForDelete || []);
    if (!sel.length) {
      if (window.setStatus) window.setStatus('Сначала выбери кадры в списке');
      return;
    }
    const cnt = document.getElementById('assignCount');
    if (cnt) cnt.textContent = String(sel.length);
    const err = document.getElementById('assignError');
    if (err) err.style.display = 'none';

    // populate user dropdowns
    try {
      const r = await fetch('/api/users', {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'DatasetBuilder' },
      }).then(x => x.json());
      const items = (r && r.items) || [];
      const single = document.getElementById('assignUserSelect');
      const multi = document.getElementById('assignUserMulti');
      if (single) single.innerHTML = '';
      if (multi) multi.innerHTML = '';
      items.forEach(u => {
        if (single) {
          const o = document.createElement('option');
          o.value = u.id; o.textContent = u.username + ' (' + u.role + ')';
          single.appendChild(o);
        }
        if (multi) {
          const o = document.createElement('option');
          o.value = u.id; o.textContent = u.username + ' (' + u.role + ')';
          multi.appendChild(o);
        }
      });
    } catch (e) {
      if (window.setError) window.setError('Не удалось загрузить пользователей');
    }
    const modeSel = document.getElementById('assignModeSelect');
    const multiRow = document.getElementById('assignMultiUserRow');
    if (modeSel) modeSel.onchange = () => {
      multiRow.style.display = modeSel.value === 'round_robin' ? '' : 'none';
    };
    if (window.openModal) window.openModal('assignModal');
  };

  window.closeAssignModal = function () {
    if (window.closeModal) window.closeModal('assignModal');
  };

  window.submitAssign = async function () {
    const err = document.getElementById('assignError');
    if (err) err.style.display = 'none';
    const ids = Array.from(window.selectedForDelete || []);
    if (!ids.length) { if (err) { err.textContent = 'Нет выбранных кадров'; err.style.display = 'block'; } return; }
    const pid = window.currentProjectId;
    if (!pid) { if (err) { err.textContent = 'Нет проекта'; err.style.display = 'block'; } return; }

    const mode = document.getElementById('assignModeSelect').value;
    const single = parseInt(document.getElementById('assignUserSelect').value, 10);
    try {
      let url, body;
      if (mode === 'round_robin') {
        const multi = document.getElementById('assignUserMulti');
        const uids = Array.from(multi.selectedOptions).map(o => parseInt(o.value, 10));
        if (!uids.length) uids.push(single);
        url = `/api/projects/${pid}/assign/round_robin`;
        body = { image_ids: ids, user_ids: uids };
      } else {
        if (isNaN(single)) throw new Error('Выберите пользователя');
        url = `/api/projects/${pid}/assign`;
        body = { image_ids: ids, user_id: single };
      }
      const r = await fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json',
                   'X-Requested-With': 'DatasetBuilder' },
        body: JSON.stringify(body),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((data.detail && data.detail.fallback) || 'Ошибка назначения');
      if (window.setSuccess) window.setSuccess('Назначено: ' + (data.assigned || 0));
      window.closeAssignModal();
      if (window.loadImages) window.loadImages();
    } catch (e) {
      if (err) { err.textContent = String(e.message || e); err.style.display = 'block'; }
    }
  };

  // --- review actions ---
  async function _postStatus(imageId, endpoint) {
    const r = await fetch(`/api/images/${imageId}/${endpoint}`, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json',
                 'X-Requested-With': 'DatasetBuilder' },
      body: '{}',
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error((data.detail && data.detail.fallback) || 'Ошибка');
    return data;
  }

  window._submitForReview = async function () {
    if (!window.currentImageId) return;
    try {
      await _postStatus(window.currentImageId, 'submit_for_review');
      if (window.setSuccess) window.setSuccess('Отправлено на проверку');
      if (window.loadImages) window.loadImages();
    } catch (e) { if (window.setError) window.setError(String(e.message || e)); }
  };
  window._approveImage = async function () {
    if (!window.currentImageId) return;
    try {
      await _postStatus(window.currentImageId, 'approve');
      if (window.setSuccess) window.setSuccess('Кадр одобрен');
      if (window.loadImages) window.loadImages();
    } catch (e) { if (window.setError) window.setError(String(e.message || e)); }
  };
  window._rejectImage = async function () {
    if (!window.currentImageId) return;
    let comment = '';
    try {
      if (window.showPrompt) {
        comment = await window.showPrompt('Вернуть на доработку',
          { text: 'Причина (необязательно)', defaultValue: '',
            okText: 'Вернуть' });
      }
    } catch (e) {}
    try {
      const r = await fetch(`/api/images/${window.currentImageId}/reject`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json',
                   'X-Requested-With': 'DatasetBuilder' },
        body: JSON.stringify({ comment: comment || null }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((data.detail && data.detail.fallback) || 'Ошибка');
      if (window.setStatus) window.setStatus('Возвращено на доработку');
      if (window.loadImages) window.loadImages();
    } catch (e) { if (window.setError) window.setError(String(e.message || e)); }
  };

  // --- "assign" entry point from bulk toolbar ---
  // Reuses existing bulk toolbar; hook into `fileOpsMenu` if present.
  const fileOpsBtn = document.getElementById('fileOpsBtn');
  if (fileOpsBtn) {
    // add "assign" button dynamically once DOM ready
    setTimeout(() => {
      const menu = document.getElementById('fileOpsMenu');
      if (!menu) return;
      if (menu.querySelector('[data-action="openAssignModal"]')) return;
      const btn = document.createElement('button');
      btn.setAttribute('data-action', 'openAssignModal');
      btn.innerHTML = '<span>Назначить на пользователя…</span>';
      menu.appendChild(btn);
    }, 900);
  }
})();
// [/STAGE4:workflow-hooks]

