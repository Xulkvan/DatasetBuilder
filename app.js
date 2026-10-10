/* =========================================================
   PigDatasetBuilder — JavaScript
   Финальная сборка: motion + pointer + FLIP + bulk-tag
   ========================================================= */

let APP_VERSION = "__VERSION__";

/* ===== Modal stack ===== */
const MODAL_STACK = [];
function openModal(id) {
  const el = document.getElementById(id);
  if (!el || el.classList.contains('open')) return;
  el.classList.remove('closing');
  el.classList.add('open');
  MODAL_STACK.push(id);
  el.style.zIndex = String(1000 + MODAL_STACK.length * 10);
  trapFocus(el);
  const firstFocusable = el.querySelector('input, button:not([disabled])');
  if (firstFocusable) setTimeout(() => { try { firstFocusable.focus(); } catch(e){} }, 80);
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (!el || el.classList.contains('closing')) return;
  el.classList.add('closing');
  el.classList.remove('open');
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
    const focusables = modalEl.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (!focusables.length) return;
    const first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
}

/* ===== Tooltips ===== */
let _tooltipEl = null, _tooltipTimer = null, _tooltipCurrentEl = null, _tooltipConverting = false;
function _getTooltipEl() {
  if (_tooltipEl) return _tooltipEl;
  _tooltipEl = document.createElement('div');
  _tooltipEl.id = 'global-tooltip';
  _tooltipEl.setAttribute('role', 'tooltip');
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
  const r = el.getBoundingClientRect();
  t.style.left = '0px'; t.style.top = '0px';
  const tr = t.getBoundingClientRect();
  let left = r.left + r.width / 2 - tr.width / 2;
  let top = r.bottom + 8;
  if (top + tr.height > window.innerHeight - 8) { top = r.top - tr.height - 8; if (top < 8) top = 8; }
  if (left < 8) left = 8;
  if (left + tr.width > window.innerWidth - 8) left = window.innerWidth - tr.width - 8;
  t.style.left = left + 'px';
  t.style.top = top + 'px';
}
function hideTooltip() {
  if (_tooltipTimer) { clearTimeout(_tooltipTimer); _tooltipTimer = null; }
  _tooltipCurrentEl = null;
  if (_tooltipEl) _tooltipEl.classList.remove('visible');
}
document.addEventListener('mouseover', (e) => {
  const el = e.target.closest && e.target.closest('[data-tooltip]');
  if (!el || _tooltipCurrentEl === el) return;
  hideTooltip();
  _tooltipCurrentEl = el;
  _tooltipTimer = setTimeout(() => { if (_tooltipCurrentEl === el) showTooltip(el); }, 350);
}, true);
document.addEventListener('mouseout', (e) => {
  const el = e.target.closest && e.target.closest('[data-tooltip]');
  if (el && _tooltipCurrentEl === el) hideTooltip();
}, true);
document.addEventListener('mousedown', () => hideTooltip(), true);
window.addEventListener('scroll', hideTooltip, true);
window.addEventListener('resize', hideTooltip);
function _installTooltipObserver() {
  convertTitlesIn(document.body);
  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'childList') m.addedNodes.forEach(node => convertTitlesIn(node));
      else if (m.type === 'attributes' && m.attributeName === 'title') convertTitleToTooltip(m.target);
    }
  });
  obs.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['title'] });
}

/* ===== Button bounce ===== */
(function _installButtonBounce() {
  document.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const btn = e.target.closest && e.target.closest('button:not(:disabled)');
    if (!btn) return;
    if (btn.classList.contains('no-bounce')) return;
    btn.classList.remove('btn-bounce');
    void btn.offsetWidth;
    btn.classList.add('btn-bounce');
    setTimeout(() => btn.classList.remove('btn-bounce'), 440);
  }, true);
})();

/* ===== Theme / hints ===== */
function getThemeMode() { try { return localStorage.getItem('pdb_theme') || 'auto'; } catch(e) { return 'auto'; } }
function applyTheme() {
  const mode = getThemeMode();
  let eff = mode;
  if (mode === 'auto') eff = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', eff);
  document.documentElement.setAttribute('data-theme-mode', mode);
  updateThemeSegment();
}
function setThemeMode(mode) {
  if (!['auto','light','dark'].includes(mode)) mode = 'auto';
  try { localStorage.setItem('pdb_theme', mode); } catch(e) {}
  applyTheme(); haptic('selection');
}
function updateThemeSegment() {
  const seg = document.getElementById('themeSegment');
  if (!seg) return;
  const cur = getThemeMode();
  seg.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.theme === cur));
}
try {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (getThemeMode() === 'auto') applyTheme();
  });
} catch(e) {}
function getHideHints() { try { return localStorage.getItem('pdb_hide_hints') === '1'; } catch(e) { return false; } }
function setHideHints(v) {
  try { localStorage.setItem('pdb_hide_hints', v ? '1' : '0'); } catch(e) {}
  document.documentElement.setAttribute('data-hide-hints', v ? '1' : '0');
  const cb = document.getElementById('hideHintsToggle');
  if (cb) cb.checked = v;
}

/* ===== Haptics ===== */
function haptic(type = 'light') {
  if (!('vibrate' in navigator)) return;
  const patterns = {
    light: [8], medium: [15], selection: [5],
    success: [10, 40, 12], error: [22, 60, 22, 60, 22], warning: [15, 40, 15],
  };
  try { navigator.vibrate(patterns[type] || patterns.light); } catch (e) {}
}

/* ===== Dialog ===== */
let _dialogResolver = null;
function _openDialog({title, text, showInput, defaultValue, hint, okText, cancelText, danger}) {
  return new Promise((resolve) => {
    _dialogResolver = resolve;
    document.getElementById('dialogTitle').textContent = title || '';
    const textEl = document.getElementById('dialogText');
    if (text) { textEl.textContent = text; textEl.style.display = ''; }
    else { textEl.textContent = ''; textEl.style.display = 'none'; }
    const inputWrap = document.getElementById('dialogInputWrap');
    const input = document.getElementById('dialogInput');
    const hintEl = document.getElementById('dialogHint');
    if (showInput) { inputWrap.style.display = 'block'; input.value = defaultValue || ''; hintEl.textContent = hint || ''; }
    else { inputWrap.style.display = 'none'; input.value = ''; hintEl.textContent = ''; }
    const okBtn = document.getElementById('dialogOk');
    okBtn.textContent = okText || 'OK';
    okBtn.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
    okBtn.onclick = () => _closeDialog(showInput ? input.value : true);
    const cancelBtn = document.getElementById('dialogCancel');
    if (cancelText === null) cancelBtn.style.display = 'none';
    else { cancelBtn.style.display = ''; cancelBtn.textContent = cancelText || 'Отмена'; cancelBtn.onclick = () => _closeDialog(null); }
    input.onkeydown = (e) => { if (showInput && e.key === 'Enter') { e.preventDefault(); _closeDialog(input.value); } };
    openModal('dialogModal');
    if (showInput) setTimeout(() => { try { input.focus(); input.select(); } catch(e){} }, 80);
  });
}
function _closeDialog(value) {
  closeModal('dialogModal');
  const r = _dialogResolver; _dialogResolver = null;
  if (r) r(value);
}
function showAlert(title, text) { return _openDialog({ title, text, showInput: false, okText: 'OK', cancelText: null }); }
function showConfirm(title, text, opts = {}) {
  return _openDialog({ title, text, showInput: false, okText: opts.okText || 'OK', cancelText: 'Отмена', danger: !!opts.danger }).then(v => v === true);
}
function showPrompt(title, opts = {}) {
  return _openDialog({ title, text: opts.text || '', showInput: true, defaultValue: opts.defaultValue || '',
    hint: opts.hint || '', okText: opts.okText || 'OK', cancelText: 'Отмена' });
}

/* ===== Custom select ===== */
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
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'custom-select-trigger';
  trigger.setAttribute('aria-haspopup', 'listbox');
  const triggerText = document.createElement('span');
  triggerText.className = 'custom-select-text';
  trigger.appendChild(triggerText);
  const chev = document.createElement('span');
  chev.className = 'custom-select-chevron';
  chev.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
  trigger.appendChild(chev);
  wrap.appendChild(trigger);
  const menu = document.createElement('div');
  menu.className = 'custom-select-menu';
  menu.setAttribute('role', 'listbox');
  function rebuildMenu() {
    menu.innerHTML = '';
    Array.from(selectEl.options).forEach((opt) => {
      const item = document.createElement('div');
      item.className = 'custom-select-option';
      item.setAttribute('role', 'option');
      item.dataset.value = opt.value;
      const check = document.createElement('span');
      check.className = 'custom-select-check';
      check.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
      item.appendChild(check);
      const label = document.createElement('span');
      label.textContent = opt.textContent;
      item.appendChild(label);
      if (opt.value === selectEl.value) item.classList.add('selected');
      item.onclick = (e) => {
        e.stopPropagation();
        selectEl.value = opt.value;
        selectEl.dispatchEvent(new Event('change', { bubbles: true }));
        close();
        haptic('selection');
      };
      menu.appendChild(item);
    });
  }
  function updateTriggerLabel() {
    const cur = Array.from(selectEl.options).find(o => o.value === selectEl.value);
    triggerText.textContent = cur ? cur.textContent : '';
    menu.querySelectorAll('.custom-select-option').forEach(el => el.classList.toggle('selected', el.dataset.value === selectEl.value));
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
    document.querySelectorAll('.custom-select.open').forEach(other => { if (other !== wrap) other.classList.remove('open'); });
    if (menu.parentNode !== document.body) document.body.appendChild(menu);
    wrap.classList.add('open'); menu.style.display = 'block'; positionMenu(); haptic('selection');
  }
  function close() { wrap.classList.remove('open'); menu.style.display = ''; }
  trigger.onclick = (e) => { e.stopPropagation(); if (wrap.classList.contains('open')) close(); else open(); };
  document.addEventListener('click', (e) => { if (!wrap.contains(e.target) && !menu.contains(e.target)) close(); });
  window.addEventListener('resize', () => { if (wrap.classList.contains('open')) positionMenu(); });
  selectEl.addEventListener('change', updateTriggerLabel);
  const mo = new MutationObserver(() => { rebuildMenu(); updateTriggerLabel(); });
  mo.observe(selectEl, { childList: true, subtree: true, characterData: true });
  rebuildMenu(); updateTriggerLabel();
}
function initCustomSelects() { document.querySelectorAll('select').forEach(upgradeSelect); }

/* ===== Helpers ===== */
async function api(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = '';
    try { detail = (await res.json()).detail || ''; } catch(e) {}
    const err = new Error(detail || res.statusText);
    err.status = res.status; err.detail = detail;
    throw err;
  }
  return res.json();
}
function setStatus(msg, ttl = 3500, variant = null, opts = {}) {
  const el = document.getElementById('status');
  const asHtml = !!opts.html;
  if (asHtml) el.innerHTML = msg; else el.textContent = msg;
  el.classList.remove('error'); el.classList.remove('success');
  if (variant === 'error') el.classList.add('error');
  else if (variant === 'success') el.classList.add('success');
  el.classList.add('visible');
  clearTimeout(setStatus._t);
  if (ttl > 0) {
    setStatus._t = setTimeout(() => { el.classList.remove('visible', 'error', 'success'); }, ttl);
  }
}
function clearStatus() {
  const el = document.getElementById('status');
  clearTimeout(setStatus._t); setStatus._t = null;
  el.classList.remove('visible', 'error', 'success');
}
function setError(msg, ttl = 6000) { setStatus(String(msg), ttl, 'error'); haptic('error'); }
function setSuccess(msg, ttl = 5000) { setStatus(String(msg), ttl, 'success'); }
function getRel(e) {
  const vp = document.getElementById('canvasViewport').getBoundingClientRect();
  const vx = e.clientX - vp.left, vy = e.clientY - vp.top;
  return { x: Math.min(Math.max(((vx - panX) / zoom) / 640, 0), 1),
           y: Math.min(Math.max(((vy - panY) / zoom) / 640, 0), 1) };
}
function clampBox(b) {
  let w = Math.min(Math.max(b.w, 0.005), 1);
  let h = Math.min(Math.max(b.h, 0.005), 1);
  let x = Math.max(0, Math.min(1 - w, b.x));
  let y = Math.max(0, Math.min(1 - h, b.y));
  return { x, y, w, h, label: b.label || 'pig', confidence: (b.confidence ?? null), frozen: !!b.frozen };
}
function showCanvas(show) {
  document.getElementById('emptyState').style.display = show ? 'none' : 'flex';
  document.getElementById('canvasCard').style.display = show ? 'inline-block' : 'none';
}
function getExt(f) { const i = f.lastIndexOf('.'); return i >= 0 ? f.slice(i+1).toLowerCase() : ''; }
function getStem(f) { const i = f.lastIndexOf('.'); return i >= 0 ? f.slice(0, i) : f; }
function pluralImages(n) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return 'изображение';
  if ([2,3,4].includes(m10) && ![12,13,14].includes(m100)) return 'изображения';
  return 'изображений';
}
function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/(1024*1024)).toFixed(1) + ' MB';
}
function animateNumber(el, newText) {
  if (!el || el.textContent === newText) return;
  el.style.transform = 'translateY(-4px)';
  el.style.opacity = '0.4';
  setTimeout(() => { el.textContent = newText; el.style.transform = 'translateY(0)'; el.style.opacity = '1'; }, 100);
}

/* ===== Zoom / Pan ===== */
function applyTransform() {
  const stage = document.getElementById('canvasStage');
  stage.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  stage.style.setProperty('--inv-zoom', (1 / zoom).toFixed(4));
  document.getElementById('zoomBadge').textContent = Math.round(zoom * 100) + '%';
}
function clampPan() {
  const vpSize = 640, stageSize = 640 * zoom;
  if (stageSize <= vpSize) { panX = (vpSize - stageSize) / 2; panY = (vpSize - stageSize) / 2; }
  else { panX = Math.min(0, Math.max(vpSize - stageSize, panX)); panY = Math.min(0, Math.max(vpSize - stageSize, panY)); }
}
function zoomAt(vx, vy, factor) {
  const nz = Math.min(Math.max(zoom * factor, ZOOM_MIN), ZOOM_MAX);
  if (nz === zoom) return;
  const k = nz / zoom;
  panX = vx - (vx - panX) * k; panY = vy - (vy - panY) * k;
  zoom = nz; clampPan(); applyTransform();
}
function zoomToCenter(f) { zoomAt(320, 320, f); }
function zoomReset() { zoom = 1; panX = 0; panY = 0; clampPan(); applyTransform(); }
function zoomFit() { zoomReset(); }

/* ===== Save / undo ===== */
function markDirty() { isDirty = true; updateSaveIndicator(); }
function markClean() { isDirty = false; updateSaveIndicator(); }
function updateSaveIndicator() {
  const el = document.getElementById('saveIndicator');
  if (!el) return;
  el.classList.remove('clean','dirty');
  el.classList.add(isDirty ? 'dirty' : 'clean');
  el.setAttribute('title', isDirty ? 'Есть несохранённые изменения' : 'Все изменения сохранены');
}
function pulseSaveIndicator() {
  const el = document.getElementById('saveIndicator');
  if (!el) return;
  el.classList.remove('saved'); void el.offsetWidth; el.classList.add('saved');
  setTimeout(() => el.classList.remove('saved'), 500);
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
  selectedIndex = -1; multiSelected.clear(); renderBoxes(); markDirty();
  setStatus('Отменено'); haptic('selection');
}
function redo() {
  if (historyIndex >= history.length - 1) return;
  historyIndex++;
  boxes = JSON.parse(JSON.stringify(history[historyIndex]));
  selectedIndex = -1; multiSelected.clear(); renderBoxes(); markDirty();
  setStatus('Повторено'); haptic('selection');
}
window.addEventListener('beforeunload', (e) => {
  if (isDirty) { e.preventDefault(); e.returnValue = ''; return ''; }
});

/* ===== State ===== */
let currentProjectId = null;
let currentImageId = null;
let imagesList = [];
let allImages = [];
let boxes = [];
let selectedIndex = -1;
let multiSelected = new Set();
let dragState = null;
let isDirty = false;
let selectedForDelete = new Set();
let viewMode = 'main';
let exportFormat = 'yolo';
let _originalTrashTtlDays = null;
const ROW_H = (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) ? 44 : 36;
let sortMode = localStorage.getItem('pdb_sortMode') || 'name_asc';
const VALID_SORTS = ['name_asc','name_desc','type_asc','type_desc','conf_asc','conf_desc'];
if (!VALID_SORTS.includes(sortMode)) sortMode = 'name_asc';
let activeFilter = localStorage.getItem('pdb_filter') || 'none';
if (!['none','unannotated','lowconf','hard'].includes(activeFilter)) activeFilter = 'none';
let searchQuery = '';
let activeTagIds = new Set();
let projectTags = [];
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

/* ===== SSE bootstrap ===== */
function subscribeBootstrapEvents() {
  if (bootstrapEventSource) { try { bootstrapEventSource.close(); } catch(e) {} }
  const es = new EventSource('/api/models/bootstrap/events');
  bootstrapEventSource = es;
  es.onmessage = (ev) => {
    try {
      const s = JSON.parse(ev.data);
      renderBootstrapStatus(s);
      if (s.status !== 'downloading') {
        if (s.status === 'done') { loadModelsIntoUI(); setSuccess(s.message || 'Модель загружена'); }
        else if (s.status === 'error') setError(s.message || 'Ошибка загрузки модели', 10000);
        setTimeout(() => { try { es.close(); } catch(e){} bootstrapEventSource = null; }, 800);
      }
    } catch(e) {}
  };
  es.onerror = () => { try { es.close(); } catch(e) {} bootstrapEventSource = null; };
}
function renderBootstrapStatus(s, opts = {}) {
  const skipTerminal = !!opts.skipTerminal;
  if (s.status === 'downloading') {
    const pctTxt = (s.progress != null && s.progress > 0) ? ` ${s.progress.toFixed(1)}%` : '';
    setStatus(`<span class="status-spinner"></span>${escapeHtml(s.message || 'Скачиваем модель…')}${pctTxt}`, 0, null, { html: true });
  }
  const el = document.getElementById('modelDownloadStatus');
  const btn = document.getElementById('downloadBtn');
  if (!el) return;
  if (renderBootstrapStatus._hideT) { clearTimeout(renderBootstrapStatus._hideT); renderBootstrapStatus._hideT = null; }
  if (s.status === 'downloading') {
    el.style.display = 'block'; el.style.background = 'var(--accent-soft)'; el.style.color = 'var(--accent)';
    el.innerHTML = `<span class="status-spinner"></span>${escapeHtml(s.message || 'Скачиваем…')}`;
    if (btn) { btn.disabled = true; btn.textContent = 'Скачиваем…'; }
  } else if (s.status === 'done') {
    if (skipTerminal) { el.style.display = 'none'; if (btn) { btn.disabled = false; btn.textContent = 'Скачать'; } }
    else {
      el.style.display = 'block'; el.style.background = 'rgba(52,199,89,0.15)'; el.style.color = 'var(--success)';
      el.textContent = `✓ ${s.message || 'Модель загружена'}`;
      if (btn) { btn.disabled = false; btn.textContent = 'Скачать'; }
      renderBootstrapStatus._hideT = setTimeout(() => { el.style.display = 'none'; renderBootstrapStatus._hideT = null; }, 5000);
    }
  } else if (s.status === 'error') {
    if (skipTerminal) { el.style.display = 'none'; if (btn) { btn.disabled = false; btn.textContent = 'Скачать'; } }
    else {
      el.style.display = 'block'; el.style.background = 'rgba(255,69,58,0.14)'; el.style.color = 'var(--danger)';
      el.textContent = `✗ ${s.message || 'Ошибка'}`;
      if (btn) { btn.disabled = false; btn.textContent = 'Скачать'; }
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
  if (!projects.length) {
    try { await api('/api/projects', {method:'POST', body: new URLSearchParams({name:'Первый проект'})}); projects = await api('/api/projects'); }
    catch(e) { setError('Не удалось создать проект: ' + String(e.message).slice(0,120)); return; }
  }
  const div = document.getElementById('projects');
  div.innerHTML = '';
  projects.forEach(p => {
    const d = document.createElement('div');
    d.dataset.projectId = p.id;
    const name = document.createElement('span');
    name.className = 'proj-name'; name.textContent = p.name;
    d.appendChild(name);
    const cnt = document.createElement('span');
    cnt.className = 'proj-count'; cnt.textContent = p.images_count;
    d.appendChild(cnt);
    const del = document.createElement('span');
    del.className = 'proj-del'; del.textContent = '×';
    del.setAttribute('role', 'button');
    del.setAttribute('aria-label', 'Удалить проект');
    del.dataset.tooltip = 'Удалить проект';
    del.onclick = async (e) => { e.stopPropagation(); await confirmDeleteProject(p.id, p.name, p.images_count); };
    d.appendChild(del);
    d.onclick = () => {
      currentProjectId = p.id; viewMode = 'main';
      selectedForDelete.clear(); activeTagIds.clear(); sessionSeen = new Set();
      updateSectionUI();
      loadTags().then(() => loadImages());
      highlightProject(d);
    };
    div.appendChild(d);
  });
  if (!currentProjectId || !projects.find(x => x.id === currentProjectId)) {
    currentProjectId = projects[0].id; sessionSeen = new Set();
  }
  loadTags().then(() => loadImages());
  highlightProject(div.querySelector(`[data-project-id="${currentProjectId}"]`) || div.firstChild);
  updateCurrentProjectInfo();
}
function updateCurrentProjectInfo() {
  const el = document.getElementById('currentProjectInfo');
  if (!el) return;
  if (!currentProjectId) { el.textContent = 'Проект не выбран'; return; }
  const activeEl = document.querySelector(`#projects > div[data-project-id="${currentProjectId}"]`);
  const name = activeEl ? (activeEl.querySelector('.proj-name')?.textContent || '') : '';
  el.textContent = name ? `Проект: «${name}» (id=${currentProjectId})` : `Проект id=${currentProjectId}`;
}
function highlightProject(el) {
  document.querySelectorAll('#projects > div').forEach(d => d.classList.remove('active-project'));
  if (el) el.classList.add('active-project');
}
async function createProject() {
  const name = await showPrompt('Новый проект', { text: 'Введите название проекта:', okText: 'Создать' });
  if (name === null) return;
  const trimmed = String(name).trim();
  if (!trimmed) { setStatus('Пустое название'); return; }
  try {
    await api('/api/projects', {method:'POST', body: new URLSearchParams({name: trimmed})});
    await loadProjects();
    setStatus(`Проект «${trimmed}» создан`); haptic('success');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function confirmDeleteProject(id, name, count) {
  const ok = await showConfirm(`Удалить проект «${name}»?`,
    `Все ${count} ${pluralImages(count)} и разметка будут стёрты. Действие необратимо.`,
    { okText: 'Удалить', danger: true });
  if (!ok) return;
  haptic('warning');
  try {
    const r = await api(`/api/projects/${id}`, {method:'DELETE'});
    if (currentProjectId === id) {
      currentImageId = null; boxes = []; selectedIndex = -1; multiSelected.clear();
      document.getElementById('image').removeAttribute('src');
      renderBoxes(); showCanvas(false); resetHistory(); markClean();
    }
    await loadProjects();
    setStatus(`Проект удалён, файлов: ${r.files_removed}`);
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
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
function stopLogsAutoRefresh() { if (_logsRefreshTimer) { clearInterval(_logsRefreshTimer); _logsRefreshTimer = null; } }
async function refreshLogs(silent = false) {
  const body = document.getElementById('logsBody');
  if (!body) return;
  const level = document.getElementById('logsLevelFilter').value;
  const category = document.getElementById('logsCategoryFilter').value;
  const params = new URLSearchParams(); params.set('limit', '500');
  if (level) params.set('level', level);
  if (category) params.set('category', category);
  try {
    const r = await api('/api/logs?' + params.toString());
    renderLogs(r.items || []);
  } catch (e) { if (!silent) body.innerHTML = '<div class="logs-empty">Ошибка загрузки логов: ' + escapeHtml(String(e.message || e)) + '</div>'; }
}
function renderLogs(items) {
  const body = document.getElementById('logsBody');
  if (!body) return;
  if (!items.length) { body.innerHTML = '<div class="logs-empty">Записей нет</div>'; return; }
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
  body.innerHTML = ''; body.appendChild(frag);
  if (nearBottom) body.scrollTop = body.scrollHeight; else body.scrollTop = scrollPos;
}
async function clearLogs() {
  const ok = await showConfirm('Очистить историю статусов?', 'Все записи будут удалены.', { okText: 'Очистить', danger: true });
  if (!ok) return;
  try { await api('/api/logs', { method: 'DELETE' }); refreshLogs(); setStatus('История статусов очищена'); }
  catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}

/* ===== Backup ===== */
async function doBackup() {
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  const btn = document.getElementById('backupBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Бэкапим…'; }
  setStatus('Создаём бэкап проекта…', 60000);
  try {
    const r = await api(`/api/projects/${currentProjectId}/backup`, { method: 'POST' });
    const sizeMb = (r.size / 1024 / 1024).toFixed(2);
    setSuccess(`Бэкап готов: ${r.filename} (${sizeMb} МБ)`, 7000);
    await showAlert('Бэкап создан',
      `Файл: ${r.filename}\nПуть: ${r.path}\n\nИзображений: ${r.images_count}\nРамок: ${r.annotations_count}\nТегов: ${r.tags_count}\nРазмер: ${sizeMb} МБ`);
    haptic('success');
  } catch (e) { setError('Ошибка бэкапа: ' + String(e.message).slice(0, 200), 8000); }
  finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Сделать бэкап';
    }
  }
}

/* ===== Tags ===== */
async function loadTags() {
  if (!currentProjectId) { projectTags = []; return; }
  try { projectTags = await api(`/api/projects/${currentProjectId}/tags`); }
  catch (e) { projectTags = []; }
  renderTagFilter(); renderTagsManager();
}
function renderTagFilter() {
  const list = document.getElementById('tagFilterList');
  list.innerHTML = '';
  if (!projectTags.length) {
    const e = document.createElement('div');
    e.style.cssText = 'padding:6px 10px;font-size:0.75rem;color:var(--text-secondary);';
    e.textContent = 'Нет тегов'; list.appendChild(e); return;
  }
  projectTags.forEach(t => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = activeTagIds.has(t.id);
    cb.addEventListener('change', () => {
      if (cb.checked) activeTagIds.add(t.id); else activeTagIds.delete(t.id);
      updateFilterBadge(); applyFiltersAndRender();
    });
    const dot = document.createElement('span'); dot.className = 'tag-dot'; dot.style.background = t.color;
    const name = document.createElement('span'); name.style.flex = '1'; name.textContent = t.name;
    const cnt = document.createElement('span');
    cnt.style.cssText = 'font-size:0.6875rem;color:var(--text-secondary);'; cnt.textContent = t.count;
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
    e.textContent = 'Тегов пока нет. Создай первый выше.'; list.appendChild(e); return;
  }
  projectTags.forEach(t => {
    const row = document.createElement('div');
    row.className = 'tag-row';
    const dot = document.createElement('span'); dot.className = 'tag-color-dot'; dot.style.background = t.color;
    const name = document.createElement('span'); name.className = 'tag-name'; name.textContent = t.name;
    const cnt = document.createElement('span'); cnt.className = 'tag-count'; cnt.textContent = t.count + ' шт.';
    const editBtn = document.createElement('button');
    editBtn.className = 'icon-btn';
    editBtn.setAttribute('aria-label', 'Редактировать тег'); editBtn.dataset.tooltip = 'Редактировать';
    editBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>';
    editBtn.onclick = () => editTag(t);
    const delBtn = document.createElement('button');
    delBtn.className = 'icon-btn';
    delBtn.setAttribute('aria-label', 'Удалить тег'); delBtn.dataset.tooltip = 'Удалить';
    delBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>';
    delBtn.onclick = () => deleteTag(t);
    row.appendChild(dot); row.appendChild(name); row.appendChild(cnt); row.appendChild(editBtn); row.appendChild(delBtn);
    list.appendChild(row);
  });
}
async function createTag() {
  const name = document.getElementById('newTagName').value.trim();
  const color = document.getElementById('newTagColor').value;
  if (!name) { setStatus('Введите имя тега'); return; }
  try {
    await api(`/api/projects/${currentProjectId}/tags`, { method:'POST', body: new URLSearchParams({name, color}) });
    document.getElementById('newTagName').value = '';
    await loadTags(); await renderTagChips();
    setStatus(`Тег «${name}» создан`); haptic('success');
  } catch (e) {
    if (e.status === 409) setStatus('Такой тег уже существует');
    else setError('Ошибка: ' + String(e.message).slice(0,120));
  }
}
async function editTag(t) {
  const name = await showPrompt('Редактировать тег', { defaultValue: t.name, okText: 'Сохранить' });
  if (name === null) return;
  const nm = String(name).trim();
  if (!nm) return;
  try {
    await api(`/api/tags/${t.id}`, {method:'PATCH', body: new URLSearchParams({name: nm})});
    await loadTags(); await renderTagChips();
    setStatus('Тег обновлён');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function deleteTag(t) {
  const ok = await showConfirm(`Удалить тег «${t.name}»?`, 'Он будет снят со всех изображений.', { okText: 'Удалить', danger: true });
  if (!ok) return;
  haptic('warning');
  try {
    await api(`/api/tags/${t.id}`, {method:'DELETE'});
    activeTagIds.delete(t.id);
    await loadTags(); applyFiltersAndRender(); await renderTagChips();
    setStatus('Тег удалён');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
function openTagsManagerFromSettings() { closeSettings(); setTimeout(() => openTagsManager(), 80); }
function openTagsManager() { renderTagsManager(); openModal('tagsManagerModal'); }
function closeTagsManager() { closeModal('tagsManagerModal'); }

/* ===== Tag chips ===== */
async function renderTagChips() {
  const bar = document.getElementById('tagChipsBar');
  const list = document.getElementById('tagChipsList');
  const bulk = document.getElementById('tagChipsBulk');
  if (!currentProjectId) { bar.style.display = 'none'; return; }
  const hasContext = !!currentImageId || selectedForDelete.size > 0;
  if (!hasContext) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  const n = selectedForDelete.size;
  if (n > 0) { bulk.style.display = ''; bulk.textContent = `Применить к ${n} ${pluralImages(n)}`; }
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
    try { const tags = await api(`/api/images/${currentImageId}/tags`); tags.forEach(x => currentImageTagIds.add(x.id)); } catch(e) {}
  }
  list.innerHTML = '';
  if (!projectTags.length) {
    const e = document.createElement('span');
    e.style.cssText = 'font-size:0.75rem;color:var(--text-secondary);';
    e.textContent = 'Тегов нет — создай первый:'; list.appendChild(e); return;
  }
  projectTags.forEach(tag => {
    const chip = document.createElement('button');
    chip.className = 'tag-chip' + (currentImageTagIds.has(tag.id) ? ' active' : '');
    chip.onclick = (e) => { e.stopPropagation(); toggleTagChip(tag.id); };
    const dot = document.createElement('span'); dot.className = 'tag-chip-dot'; dot.style.background = tag.color;
    chip.appendChild(dot);
    const name = document.createElement('span'); name.textContent = tag.name;
    chip.appendChild(name);
    if (tag.count > 0) {
      const cnt = document.createElement('span'); cnt.className = 'tag-chip-count'; cnt.textContent = tag.count;
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
      body: JSON.stringify({ image_ids: targetIds, add: hasOnAll ? [] : [tagId], remove: hasOnAll ? [tagId] : [] }),
    });
    metas.forEach(m => {
      const s = new Set(m.tag_ids || []);
      if (hasOnAll) s.delete(tagId); else s.add(tagId);
      m.tag_ids = Array.from(s);
    });
    await loadTags(); renderImageList({ flip: true }); await renderTagChips();
    setStatus(hasOnAll ? 'Тег снят' : 'Тег назначен'); haptic('selection');
  } catch (e) { setError('Ошибка тега: ' + String(e.message).slice(0,140)); }
}
function openTagCreate() {
  document.getElementById('newTagNameInline').value = '';
  document.getElementById('newTagColorInline').value = '#0071e3';
  openModal('tagCreateModal');
}
function closeTagCreate() { closeModal('tagCreateModal'); }
async function createTagInline() {
  const name = document.getElementById('newTagNameInline').value.trim();
  const color = document.getElementById('newTagColorInline').value;
  if (!name) { setStatus('Введите имя тега'); return; }
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  try {
    const t = await api(`/api/projects/${currentProjectId}/tags`, { method:'POST', body: new URLSearchParams({name, color}) });
    await loadTags();
    const targetIds = selectedForDelete.size > 0 ? Array.from(selectedForDelete) : (currentImageId ? [currentImageId] : []);
    if (targetIds.length) {
      await api('/api/images/batch_tags', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_ids: targetIds, add: [t.id], remove: [] }),
      });
      targetIds.forEach(iid => {
        const meta = allImages.find(x => x.id === iid);
        if (meta) { const s = new Set(meta.tag_ids || []); s.add(t.id); meta.tag_ids = Array.from(s); }
      });
    }
    await loadTags(); renderImageList({ flip: true }); await renderTagChips();
    closeTagCreate(); setStatus(`Тег «${t.name}» создан`); haptic('success');
  } catch (e) {
    if (e.status === 409) setStatus('Такой тег уже существует');
    else setError('Ошибка: ' + String(e.message).slice(0,120));
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
}
function toggleBulkTagMenu(e) {
  if (e) e.stopPropagation();
  if (selectedForDelete.size === 0) return;
  const menu = document.getElementById('bulkTagMenu');
  const btn = document.getElementById('bulkTagBtn');
  if (menu.classList.contains('open')) { menu.classList.remove('open'); return; }
  document.querySelectorAll('.sort-menu').forEach(m => m.classList.remove('open'));
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
    e.textContent = 'Тегов нет — создай в «+ Тег» под холстом';
    list.appendChild(e); return;
  }
  const ids = Array.from(selectedForDelete);
  const metas = allImages.filter(i => ids.includes(i.id));
  projectTags.forEach(tag => {
    const isOnAll = metas.length > 0 && metas.every(m => (m.tag_ids || []).includes(tag.id));
    const btn = document.createElement('button');
    btn.className = 'bulk-tag-item' + (isOnAll ? ' active' : '');
    btn.setAttribute('role', 'menuitem');
    const dot = document.createElement('span'); dot.className = 'tag-dot'; dot.style.background = tag.color;
    btn.appendChild(dot);
    const name = document.createElement('span'); name.style.flex = '1'; name.textContent = tag.name;
    btn.appendChild(name);
    const check = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    check.setAttribute('viewBox', '0 0 24 24');
    check.classList.add('bulk-tag-check');
    check.innerHTML = '<polyline points="20 6 9 17 4 12"/>';
    btn.appendChild(check);
    btn.onclick = async (e) => { e.stopPropagation(); await bulkToggleTag(tag.id); };
    list.appendChild(btn);
  });
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
    });
    await loadTags(); renderImageList({ flip: true }); renderBulkTagMenu();
    setStatus(hasOnAll ? 'Тег снят' : 'Тег назначен'); haptic('selection');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0, 140)); }
}

/* ===== Trash ===== */
async function toggleTrash() {
  viewMode = viewMode === 'main' ? 'trash' : 'main';
  haptic('selection');
  selectedForDelete.clear();
  if (viewMode === 'trash') {
    currentImageId = null; boxes = []; selectedIndex = -1; multiSelected.clear();
    document.getElementById('image').removeAttribute('src');
    renderBoxes(); showCanvas(false); resetHistory(); markClean(); updateDelBoxBtn();
  }
  updateSectionUI();
  await loadImages(); await renderTagChips();
}
function updateSectionUI() {
  const section = document.getElementById('imagesSection');
  const title = document.getElementById('sectionTitle');
  const btn = document.getElementById('trashToggleBtn');
  const trashBar = document.getElementById('trashActionsBar');
  const bulkBar = document.getElementById('bulkBar');
  const trashBulkBar = document.getElementById('trashBar');
  if (viewMode === 'trash') {
    section.classList.add('trash-mode');
    title.textContent = 'Корзина'; btn.classList.add('active');
    trashBar.style.display = 'flex'; bulkBar.classList.remove('open');
  } else {
    section.classList.remove('trash-mode');
    title.textContent = 'Изображения'; btn.classList.remove('active');
    trashBar.style.display = 'none'; trashBulkBar.classList.remove('open');
  }
  updateBulkBar(); updateTrashBar(); updateSelectAllCheck(); updateFilterBadge();
  updateBulkTagBtn();
}

/* ===== Filters / sort ===== */
function applyFiltersAndRender() {
  const arr = viewMode === 'trash' ? allImages : filterList(allImages);
  imagesList = sortImages(arr, sortMode);
  renderImageList({ flip: true });
  updateProgress(); updateSelectAllCheck(); updateHardBtn(); updateSimilarBtn();
  updateBulkTagBtn();
}
function filterList(arr) {
  let out = arr;
  if (activeFilter === 'unannotated') out = out.filter(x => (x.annotation_count || 0) === 0);
  else if (activeFilter === 'lowconf') out = out.filter(x => (x.low_conf_count || 0) > 0);
  else if (activeFilter === 'hard') out = out.filter(x => !!x.is_hard);
  if (activeTagIds.size > 0) {
    out = out.filter(x => {
      const ids = x.tag_ids || [];
      for (const tid of activeTagIds) if (ids.includes(tid)) return true;
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
  if ((x.annotation_count || 0) === 0) return -1;
  if (x.min_confidence != null) return x.min_confidence;
  return 1.0;
}
function sortImages(images, mode) {
  const arr = [...images];
  switch (mode) {
    case 'name_asc': return arr.sort((a,b) => a.filename.localeCompare(b.filename,'ru',{numeric:true}));
    case 'name_desc': return arr.sort((a,b) => b.filename.localeCompare(a.filename,'ru',{numeric:true}));
    case 'type_asc': return arr.sort((a,b) => {
      const c = getExt(a.filename).localeCompare(getExt(b.filename));
      return c !== 0 ? c : a.filename.localeCompare(b.filename,'ru',{numeric:true});
    });
    case 'type_desc': return arr.sort((a,b) => {
      const c = getExt(b.filename).localeCompare(getExt(a.filename));
      return c !== 0 ? c : a.filename.localeCompare(b.filename,'ru',{numeric:true});
    });
    case 'conf_asc': return arr.sort((a,b) => confSortKey(a) - confSortKey(b));
    case 'conf_desc': return arr.sort((a,b) => confSortKey(b) - confSortKey(a));
    default: return arr;
  }
}
async function loadImages() {
  if (!currentProjectId) return;
  showImageSkeleton();
  try {
    const raw = viewMode === 'trash'
      ? await api(`/api/projects/${currentProjectId}/trash`)
      : await api(`/api/projects/${currentProjectId}/images`);
    allImages = raw;
    applyFiltersAndRender();
    updateTrashActionsBar(); updateBulkBar(); updateTrashBar(); updateFilterBadge();
  } catch (e) {
    console.error('loadImages failed:', e);
    allImages = []; imagesList = [];
    renderImageList();
    setError('Ошибка загрузки: ' + String(e.message || e).slice(0,120), 6000);
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
  status.setAttribute('aria-label', title); status.dataset.tooltip = title;
  return status;
}
function makeHardIndicator(isHard) {
  const el = document.createElement('span');
  el.className = 'img-hard' + (isHard ? ' flagged' : '');
  if (isHard) { el.setAttribute('aria-label', 'Помечен как сложный'); el.dataset.tooltip = 'Помечен как сложный'; }
  el.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 2v20h2v-8h14l-3-5 3-5H6V2H4z"/></svg>';
  return el;
}
function makeTagsMini(tagIds) {
  const wrap = document.createElement('span');
  wrap.className = 'img-tags-mini';
  if (!tagIds || !tagIds.length) return wrap;
  tagIds.slice(0, 4).forEach(tid => {
    const t = projectTags.find(x => x.id === tid);
    if (!t) return;
    const dot = document.createElement('span');
    dot.className = 'img-tag-dot'; dot.style.background = t.color;
    dot.setAttribute('aria-label', t.name); dot.dataset.tooltip = t.name;
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

/* ===== Virtual scroll + FLIP ===== */
let renderRafPending = false;
let _lastRenderIds = new Set();
let _lastRenderPositions = new Map();

function renderImageList(opts = {}) {
  const container = document.getElementById('imageList');
  const inner = document.getElementById('imageListInner');
  const flip = !!opts.flip;
  const highlights = opts.highlightIds instanceof Set ? opts.highlightIds : null;

  if (!imagesList.length) {
    inner.style.height = 'auto'; inner.innerHTML = '';
    const e = document.createElement('div');
    e.style.cssText = 'padding:20px 8px;font-size:0.8125rem;color:var(--text-secondary);text-align:center;';
    e.textContent = viewMode === 'trash' ? 'Корзина пуста'
      : (activeFilter !== 'none' || activeTagIds.size || searchQuery ? 'Нет изображений по фильтрам' : 'Нет изображений');
    inner.appendChild(e);
    _lastRenderIds = new Set(); _lastRenderPositions = new Map();
    return;
  }

  inner.style.height = (imagesList.length * ROW_H) + 'px';
  const scrollTop = container.scrollTop;
  const viewH = container.clientHeight || 400;
  const overscan = 3;
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - overscan);
  const endIdx = Math.min(imagesList.length, Math.ceil((scrollTop + viewH) / ROW_H) + overscan);

  const beforePositions = new Map();
  if (flip) {
    inner.querySelectorAll('.img-row').forEach(r => {
      const id = r.dataset.imageId;
      if (id) beforePositions.set(id, parseFloat(r.style.top) || 0);
    });
  }

  const newIds = new Set();
  for (let i = startIdx; i < endIdx; i++) newIds.add(String(imagesList[i].id));

  const toRemove = [];
  inner.querySelectorAll('.img-row').forEach(r => {
    const id = r.dataset.imageId;
    if (!id) { r.remove(); return; }
    if (!newIds.has(id)) {
      if (flip) { r.classList.add('row-leaving'); toRemove.push(r); }
      else r.remove();
    }
  });
  if (toRemove.length) setTimeout(() => { toRemove.forEach(r => { try { r.remove(); } catch(_) {} }); }, 240);

  const existing = new Map();
  inner.querySelectorAll('.img-row').forEach(r => {
    const id = r.dataset.imageId;
    if (id && !r.classList.contains('row-leaving')) existing.set(id, r);
  });

  for (let i = startIdx; i < endIdx; i++) {
    const img = imagesList[i];
    const id = String(img.id);
    const targetTop = i * ROW_H;
    let row = existing.get(id);
    if (!row) {
      row = viewMode === 'trash' ? makeTrashRow(img, i) : makeMainRow(img, i);
      row.style.top = targetTop + 'px';
      if (flip && _lastRenderIds.has(id)) row.classList.add('row-entering');
      if (highlights && highlights.has(img.id)) row.classList.add('just-highlighted');
      inner.appendChild(row);
    } else {
      row.dataset.index = i;
      row.style.top = targetTop + 'px';
      row.classList.toggle('active', img.id === currentImageId);
      const cb = row.querySelector('.img-check');
      if (cb) cb.checked = selectedForDelete.has(img.id);
    }
  }

  if (flip && beforePositions.size) {
    inner.querySelectorAll('.img-row').forEach(r => {
      const id = r.dataset.imageId;
      if (!id || r.classList.contains('row-entering') || r.classList.contains('row-leaving')) return;
      const oldTop = beforePositions.get(id);
      if (oldTop == null) return;
      const newTop = parseFloat(r.style.top) || 0;
      const delta = oldTop - newTop;
      if (Math.abs(delta) < 1) return;
      r.style.transform = `translateY(${delta}px)`;
      r.style.transition = 'none';
      requestAnimationFrame(() => {
        r.classList.add('flipping');
        r.style.transition = '';
        r.style.transform = 'translateY(0)';
        setTimeout(() => { r.classList.remove('flipping'); }, 280);
      });
    });
  }

  _lastRenderIds = newIds;
  _lastRenderPositions = new Map();
  imagesList.forEach((img, i) => _lastRenderPositions.set(String(img.id), i * ROW_H));
}

function makeMainRow(img, index) {
  const row = document.createElement('div');
  row.className = 'img-row';
  row.dataset.imageId = img.id; row.dataset.index = index;
  if (img.id === currentImageId) row.classList.add('active');
  const check = document.createElement('input');
  check.type = 'checkbox'; check.className = 'img-check';
  check.checked = selectedForDelete.has(img.id);
  check.addEventListener('click', e => e.stopPropagation());
  check.addEventListener('change', () => {
    if (check.checked) selectedForDelete.add(img.id); else selectedForDelete.delete(img.id);
    updateBulkBar(); updateSelectAllCheck(); renderTagChips(); haptic('selection');
  });
  row.appendChild(check);
  const thumb = document.createElement('img');
  thumb.className = 'img-thumb'; thumb.loading = 'lazy'; thumb.alt = '';
  thumb.src = `/api/images/${img.id}/thumb`;
  row.appendChild(thumb);
  row.appendChild(makeStatusDot(img));
  row.appendChild(makeHardIndicator(!!img.is_hard));
  const name = document.createElement('span');
  name.className = 'img-name'; name.textContent = img.filename;
  name.setAttribute('aria-label', img.filename); name.dataset.tooltip = img.filename;
  name.onclick = () => selectImage(img.id);
  row.appendChild(name);
  if (img.tag_ids && img.tag_ids.length) row.appendChild(makeTagsMini(img.tag_ids));
  const rename = document.createElement('span');
  rename.className = 'img-action img-rename';
  rename.setAttribute('role','button');
  rename.setAttribute('aria-label','Переименовать'); rename.dataset.tooltip = 'Переименовать';
  rename.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>';
  rename.onclick = (e) => { e.stopPropagation(); renameImage(img.id, img.filename); };
  row.appendChild(rename);
  const del = document.createElement('span');
  del.className = 'img-action img-del';
  del.setAttribute('role','button');
  del.setAttribute('aria-label','Удалить изображение'); del.dataset.tooltip = 'Удалить';
  del.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
  del.onclick = (e) => { e.stopPropagation(); deleteImage(img.id, img.filename); };
  row.appendChild(del);
  return row;
}
function makeTrashRow(img, index) {
  const row = document.createElement('div');
  row.className = 'img-row trash-row';
  row.dataset.imageId = img.id; row.dataset.index = index;
  const check = document.createElement('input');
  check.type = 'checkbox'; check.className = 'img-check';
  check.checked = selectedForDelete.has(img.id);
  check.addEventListener('click', e => e.stopPropagation());
  check.addEventListener('change', () => {
    if (check.checked) selectedForDelete.add(img.id); else selectedForDelete.delete(img.id);
    updateTrashBar(); updateSelectAllCheck(); haptic('selection');
  });
  row.appendChild(check);
  const thumb = document.createElement('img');
  thumb.className = 'img-thumb'; thumb.loading = 'lazy'; thumb.alt = '';
  thumb.src = `/api/images/${img.id}/thumb`;
  row.appendChild(thumb);
  const name = document.createElement('span');
  name.className = 'img-name'; name.textContent = img.filename;
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
  restore.setAttribute('aria-label','Восстановить'); restore.dataset.tooltip = 'Восстановить';
  restore.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>';
  restore.onclick = (e) => { e.stopPropagation(); restoreImage(img.id); };
  actions.appendChild(restore);
  const perm = document.createElement('button');
  perm.className = 'trash-act perm-del';
  perm.setAttribute('aria-label','Удалить навсегда'); perm.dataset.tooltip = 'Удалить навсегда';
  perm.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
  perm.onclick = (e) => { e.stopPropagation(); permanentDelete(img.id, img.filename); };
  actions.appendChild(perm);
  row.appendChild(actions);
  row.onclick = (e) => {
    if (e.target.closest('.trash-actions')) return;
    if (e.target.classList.contains('img-check')) return;
    openPreview(img.id, img.filename, img.days_left);
  };
  return row;
}
function onListScroll() {
  if (renderRafPending) return;
  renderRafPending = true;
  requestAnimationFrame(() => { renderRafPending = false; renderImageList(); });
}
function scrollListToImage(id) {
  const idx = imagesList.findIndex(x => x.id === id);
  if (idx < 0) return;
  const container = document.getElementById('imageList');
  const viewH = container.clientHeight || 400;
  const target = idx * ROW_H - viewH / 2 + ROW_H / 2;
  container.scrollTop = Math.max(0, target);
}

/* ===== Progress / bulk bars ===== */
function updateProgress() {
  if (viewMode === 'trash') return;
  const total = allImages.length;
  const done = allImages.filter(i => (i.annotation_count || 0) > 0).length;
  const block = document.getElementById('progressBlock');
  if (block) block.classList.toggle('hidden', total === 0);
  animateNumber(document.getElementById('progressText'), `${done} / ${total}`);
  document.getElementById('progressFill').style.width = (total ? (done/total)*100 : 0) + '%';
  document.getElementById('progressLabel').textContent = 'Размечено';
  document.getElementById('progressFill').classList.remove('batch');
}
function updateBulkBar() {
  const bar = document.getElementById('bulkBar');
  const n = selectedForDelete.size;
  if (n > 0 && viewMode === 'main') {
    bar.classList.add('open');
    document.getElementById('bulkCount').textContent = `${n} ${pluralImages(n)} выбрано`;
  } else bar.classList.remove('open');
  updateBulkTagBtn();
}
function updateTrashBar() {
  const bar = document.getElementById('trashBar');
  const n = selectedForDelete.size;
  if (n > 0 && viewMode === 'trash') {
    bar.classList.add('open');
    document.getElementById('trashCount').textContent = `${n} ${pluralImages(n)} выбрано`;
  } else bar.classList.remove('open');
}
function updateTrashActionsBar() {
  if (viewMode !== 'trash') return;
  const el = document.getElementById('trashTotal');
  const n = allImages.length;
  el.textContent = n === 0 ? 'Корзина пуста' : `${n} ${pluralImages(n)} в корзине`;
}
function updateSelectAllCheck() {
  const check = document.getElementById('selectAllCheck');
  if (!check) return;
  if (!imagesList.length) { check.checked = false; check.indeterminate = false; check.disabled = true; return; }
  check.disabled = false;
  const total = imagesList.length;
  const selected = imagesList.filter(i => selectedForDelete.has(i.id)).length;
  check.checked = selected === total && total > 0;
  check.indeterminate = selected > 0 && selected < total;
}
function toggleSelectAll() {
  const check = document.getElementById('selectAllCheck');
  const ids = imagesList.map(i => i.id);
  if (check.checked) ids.forEach(id => selectedForDelete.add(id));
  else ids.forEach(id => selectedForDelete.delete(id));
  renderImageList(); updateBulkBar(); updateTrashBar(); updateSelectAllCheck(); renderTagChips(); haptic('selection');
}
function clearSelection() {
  selectedForDelete.clear();
  renderImageList(); updateBulkBar(); updateTrashBar(); updateSelectAllCheck(); renderTagChips();
}
function updateFilterBadge() {
  const badge = document.getElementById('filterBadge');
  const btn = document.getElementById('filterBtn');
  const n = (activeFilter !== 'none' ? 1 : 0) + activeTagIds.size;
  if (n > 0) { badge.style.display = 'block'; badge.textContent = String(n); btn.classList.add('active'); }
  else { badge.style.display = 'none'; btn.classList.remove('active'); }
}
function updateHardBtn() {
  const btn = document.getElementById('hardBtn');
  if (!btn) return;
  const meta = allImages.find(i => i.id === currentImageId);
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
  applyFiltersAndRender();
}

/* ===== Upload / import ===== */
async function uploadImages() {
  const input = document.getElementById('fileInput');
  if (!input.files.length) return;
  if (viewMode === 'trash') { viewMode = 'main'; updateSectionUI(); }
  setStatus('Загрузка...', 60000);
  let added = 0, dup = 0, failed = 0, renamed = 0;
  const dupNames = [];
  for (const file of input.files) {
    const fd = new FormData(); fd.append('file', file);
    try {
      const res = await fetch(`/api/projects/${currentProjectId}/images`, {method:'POST', body: fd});
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
  const parts = [`Загружено: ${added}`];
  if (renamed) parts.push(`переименовано: ${renamed}`);
  if (dup) parts.push(`дубликатов: ${dup}`);
  if (failed) parts.push(`ошибок: ${failed}`);
  setStatus(parts.join(', '), 6000);
  if (added > 0) haptic('success');
  if (dupNames.length) {
    const lines = dupNames.slice(0, 15).map(d => `• ${d.name}\n   → ${d.reason}`).join('\n');
    const more = dupNames.length > 15 ? `\n... и ещё ${dupNames.length - 15}` : '';
    await showAlert(`Пропущены дубликаты (${dupNames.length})`, `${lines}${more}`);
  }
}
async function handleImport() {
  const input = document.getElementById('importInput');
  if (!input.files.length) return;
  const file = input.files[0];
  input.value = '';
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  const status = document.getElementById('importStatus');
  const result = document.getElementById('importResult');
  const closeBtn = document.getElementById('importCloseBtn');
  status.textContent = 'Идёт обработка архива… (может занять несколько минут для больших датасетов)';
  status.style.color = '';
  result.style.display = 'none'; result.innerHTML = '';
  closeBtn.style.display = 'none';
  openModal('importModal');
  const fd = new FormData(); fd.append('file', file);
  try {
    const res = await fetch(`/api/projects/${currentProjectId}/import`, { method:'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = 'Ошибка импорта'; status.style.color = 'var(--danger)';
      result.style.display = 'block'; result.textContent = data.detail || 'Не удалось импортировать.';
    } else {
      status.textContent = 'Импорт завершён ✓'; status.style.color = 'var(--success)';
      result.style.display = 'block';
      const fmt = ({coco:'COCO', yolo:'YOLO', cvat:'CVAT XML', ls:'Label Studio', images_only:'Только изображения'})[data.format] || data.format;
      let html = `<div>Формат: <b>${escapeHtml(fmt)}</b></div>`;
      if (data.imported_images) html += `<div>Загружено изображений: <b>${data.imported_images}</b></div>`;
      if (data.skipped_duplicates) html += `<div>Пропущено дубликатов: <b>${data.skipped_duplicates}</b></div>`;
      if (data.failed_images) html += `<div>Не удалось открыть: <b>${data.failed_images}</b></div>`;
      html += `<div>Совпало изображений: <b>${data.matched_images}</b></div>`;
      html += `<div>Добавлено рамок: <b>${data.added_annotations}</b></div>`;
      if (data.unmatched_count) html += `<div style="margin-top:8px;">Не найдено: <b>${data.unmatched_count}</b></div>`;
      result.innerHTML = html;
      await loadImages(); haptic('success');
    }
  } catch (e) {
    status.textContent = 'Ошибка сети'; status.style.color = 'var(--danger)';
    result.style.display = 'block'; result.textContent = String(e.message || e);
  }
  closeBtn.style.display = 'inline-flex';
}
function closeImportModal() { closeModal('importModal'); }

/* ===== Image select / delete / rename ===== */
async function selectImage(id, {autoAutolabel = false, skipDirtyCheck = false} = {}) {
  if (viewMode === 'trash') return;
  if (!skipDirtyCheck && isDirty && currentImageId && currentImageId !== id) {
    const ok = await showConfirm('Есть несохранённые изменения',
      'Перейти к другому изображению без сохранения?', { okText: 'Перейти', danger: true });
    if (!ok) return;
  }
  currentImageId = id;
  selectedIndex = -1; multiSelected.clear(); dragState = null;
  showCanvas(true); updateDelBoxBtn();
  scrollListToImage(id); renderImageList();
  const img = document.getElementById('image');
  img.style.transition = 'none';
  img.style.opacity = '0';
  img.style.transform = 'scale(0.985)';
  const imgLoadPromise = new Promise(r => { img.onload = r; img.onerror = r; img.src = `/api/images/${id}/file?t=${Date.now()}`; });
  const [_, anns, tagsRes] = await Promise.all([
    imgLoadPromise,
    api(`/api/images/${id}/annotations`).catch(() => []),
    api(`/api/images/${id}/tags`).catch(() => []),
  ]);
  void img.offsetWidth;
  img.style.transition = '';
  img.style.opacity = '1';
  img.style.transform = 'scale(1)';
  boxes = anns;
  currentImageTagIds = new Set(tagsRes.map(t => t.id));
  renderBoxes(); resetHistory(); markClean(); zoomReset();
  updateHardBtn(); updateSimilarBtn(); updateFreezeBtn();
  await renderTagChips();
  const meta = allImages.find(i => i.id === id);
  const isNewInSession = !sessionSeen.has(id);
  sessionSeen.add(id);
  if (autoAutolabel && isNewInSession && (!meta || (meta.annotation_count || 0) === 0)) {
    await runAutolabel();
  }
}
async function deleteImage(id, filename) {
  const ok = await showConfirm('Удалить изображение?', `«${filename}» перейдёт в корзину.`, { okText: 'В корзину' });
  if (!ok) return;
  haptic('warning');
  try {
    await api(`/api/images/${id}`, {method:'DELETE'});
    sessionSeen.delete(id); selectedForDelete.delete(id);
    if (currentImageId === id) {
      currentImageId = null; boxes = []; selectedIndex = -1; multiSelected.clear();
      document.getElementById('image').removeAttribute('src');
      renderBoxes(); showCanvas(false); resetHistory(); markClean(); updateDelBoxBtn();
    }
    await loadImages(); await renderTagChips();
    setStatus('Перемещено в корзину');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function renameImage(id, currentName) {
  const oldExt = getExt(currentName);
  const oldStem = getStem(currentName);
  const hint = oldExt ? `Расширение .${oldExt} сохраняется автоматически. Недопустимые: \\ / : * ? " < > |`
                      : 'Недопустимые символы: \\ / : * ? " < > |';
  const input = await showPrompt('Переименовать файл', {
    text: 'Введите новое имя файла:', defaultValue: oldStem, hint, okText: 'Переименовать'
  });
  if (input === null) return;
  const newStem = String(input).trim();
  if (!newStem) { setStatus('Пустое имя'); return; }
  if (newStem === oldStem) return;
  if (/[\\/:*?"<>|]/.test(newStem)) { setError('Недопустимые символы', 5000); return; }
  try {
    const r = await api(`/api/images/${id}/rename`, { method:'POST', body: new URLSearchParams({ filename: newStem }) });
    await loadImages();
    setStatus(`Переименовано: ${r.filename}`);
  } catch (e) {
    if (e.status === 409) setStatus('Имя уже занято', 4000);
    else setError(String(e.message || e).slice(0,140), 4000);
  }
}
async function restoreImage(id) {
  try {
    await api(`/api/images/${id}/restore`, {method:'POST'});
    selectedForDelete.delete(id);
    await loadImages(); setStatus('Восстановлено');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function permanentDelete(id, filename) {
  const ok = await showConfirm('Удалить навсегда?', `«${filename}» будет стёрт с диска.`, { okText: 'Удалить', danger: true });
  if (!ok) return;
  haptic('warning');
  try {
    await api(`/api/images/${id}/permanent`, {method:'DELETE'});
    selectedForDelete.delete(id);
    await loadImages(); setStatus('Удалено навсегда');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}

/* ===== Hard / freeze ===== */
async function toggleHardCurrent() {
  if (!currentImageId) return;
  try {
    const r = await api(`/api/images/${currentImageId}/toggle_hard`, {method:'POST'});
    const meta = allImages.find(i => i.id === currentImageId);
    if (meta) meta.is_hard = !!r.is_hard;
    applyFiltersAndRender(); updateHardBtn(); haptic('selection');
    setStatus(r.is_hard ? 'Помечен как сложный ⚑' : 'Пометка снята');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
function toggleFreezeSelected() {
  const indices = getSelectedIndices();
  if (!indices.length) { setStatus('Сначала выдели рамки'); return; }
  const allFrozen = indices.every(i => boxes[i].frozen);
  indices.forEach(i => { boxes[i].frozen = !allFrozen; });
  renderBoxes(); pushHistory(); markDirty(); haptic('selection');
  setStatus(allFrozen ? 'Разморожено' : 'Заморожено');
}

/* ===== Batch ===== */
async function confirmBatchDelete() {
  const n = selectedForDelete.size; if (!n) return;
  const ok = await showConfirm(`Переместить ${n} ${pluralImages(n)} в корзину?`, 'Можно восстановить.', { okText: 'В корзину' });
  if (!ok) return;
  haptic('warning');
  try {
    const r = await api('/api/images/batch_delete', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(Array.from(selectedForDelete)),
    });
    if (Array.from(selectedForDelete).includes(currentImageId)) {
      currentImageId = null; boxes = []; selectedIndex = -1; multiSelected.clear();
      document.getElementById('image').removeAttribute('src');
      renderBoxes(); showCanvas(false); resetHistory(); markClean(); updateDelBoxBtn();
    }
    selectedForDelete.clear();
    await loadImages(); await renderTagChips();
    setStatus(`В корзину: ${r.deleted}`);
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function confirmBatchPermanentDelete() {
  const n = selectedForDelete.size; if (!n) return;
  const ok = await showConfirm(`Удалить ${n} ${pluralImages(n)} навсегда?`, 'Файлы будут стёрты.', { okText: 'Удалить', danger: true });
  if (!ok) return;
  haptic('warning');
  try {
    const r = await api('/api/images/batch_permanent_delete', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(Array.from(selectedForDelete)),
    });
    selectedForDelete.clear();
    await loadImages(); setStatus(`Удалено: ${r.deleted}`);
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function confirmEmptyTrash() {
  const n = allImages.length;
  if (!n) { setStatus('Корзина уже пуста'); return; }
  const ok = await showConfirm(`Очистить корзину (${n})?`, 'Все будут удалены навсегда.', { okText: 'Очистить', danger: true });
  if (!ok) return;
  haptic('warning');
  try {
    const r = await api(`/api/projects/${currentProjectId}/trash/empty`, {method:'POST'});
    selectedForDelete.clear();
    await loadImages(); setStatus(`Очищено: ${r.deleted}`);
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function batchRestore() {
  const ids = Array.from(selectedForDelete); if (!ids.length) return;
  try {
    const r = await api('/api/images/batch_restore', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(ids),
    });
    selectedForDelete.clear();
    await loadImages();
    let msg = `Восстановлено: ${r.restored}`;
    if (r.renamed) msg += ` (переименовано: ${r.renamed})`;
    setStatus(msg, 5000); haptic('success');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}

/* ===== Preview / Stats / Validate ===== */
function openPreview(id, filename, daysLeft) {
  document.getElementById('previewName').textContent = filename;
  document.getElementById('previewDays').textContent = daysLeft != null ? (daysLeft <= 0 ? 'истекает' : `осталось ${daysLeft} дн.`) : '';
  document.getElementById('previewImg').src = `/api/images/${id}/file?t=${Date.now()}`;
  openModal('previewModal');
}
function closePreview() {
  closeModal('previewModal');
  document.getElementById('previewImg').removeAttribute('src');
}
async function downloadStatsCsv() {
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  await downloadFile(`/api/projects/${currentProjectId}/stats.csv`, `stats_project_${currentProjectId}.csv`);
}
async function openStats() {
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  try {
    const s = await api(`/api/projects/${currentProjectId}/stats`);
    document.getElementById('statTotal').textContent = s.total_images;
    document.getElementById('statAnnotated').textContent = s.annotated_images;
    document.getElementById('statUnannotated').textContent = s.unannotated_images;
    document.getElementById('statBoxes').textContent = s.total_boxes;
    const c = s.confidence;
    const maxVal = Math.max(c.manual, c.low, c.mid, c.high, 1);
    document.getElementById('barHigh').style.width = (c.high/maxVal*100) + '%';
    document.getElementById('barMid').style.width = (c.mid/maxVal*100) + '%';
    document.getElementById('barLow').style.width = (c.low/maxVal*100) + '%';
    document.getElementById('barManual').style.width = (c.manual/maxVal*100) + '%';
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
        row.onclick = async () => {
          closeStats();
          if (viewMode === 'trash') { viewMode = 'main'; updateSectionUI(); }
          await selectImage(item.id, {skipDirtyCheck: true});
        };
        list.appendChild(row);
      });
    }
    openModal('statsModal');
  } catch (e) { setError('Статистика недоступна: ' + String(e.message).slice(0,120), 5000); }
}
function closeStats() { closeModal('statsModal'); }
function openValidateFromExport() { closeExportModal(); setTimeout(() => openValidateModal(), 80); }
async function openValidateModal() {
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  const body = document.getElementById('validateBody');
  body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;">Идёт проверка… (может занять несколько секунд)</p>';
  openModal('validateModal');
  try {
    const r = await api(`/api/projects/${currentProjectId}/validate?deep=true`);
    const bt = r.by_type || {};
    let html = '';
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card"><div class="stat-value" style="color:var(--box-low)">${bt.small_box || 0}</div><div class="stat-label">Маленькие</div></div>`;
    html += `<div class="stat-card"><div class="stat-value" style="color:var(--warning)">${bt.overlap || 0}</div><div class="stat-label">Дубли</div></div>`;
    html += `<div class="stat-card"><div class="stat-value" style="color:var(--danger)">${bt.out_of_bounds || 0}</div><div class="stat-label">Вне холста</div></div>`;
    html += `</div>`;
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card"><div class="stat-value" style="color:#ff375f">${bt.nested_box || 0}</div><div class="stat-label">Вложенные</div></div>`;
    html += `<div class="stat-card"><div class="stat-value">${bt.aspect || 0}</div><div class="stat-label">Аспект</div></div>`;
    html += `<div class="stat-card"><div class="stat-value">${r.unannotated.length}</div><div class="stat-label">Без разметки</div></div>`;
    html += `</div>`;
    html += `<div class="validator-summary">`;
    html += `<div class="stat-card" style="grid-column: 1 / -1;"><div class="stat-value" style="color:${r.total_issues ? 'var(--danger)' : 'var(--success)'}">${r.total_issues}</div><div class="stat-label">Всего проблем</div></div>`;
    html += `</div>`;
    if (!r.total_issues && !r.unannotated.length) {
      html += `<p style="color:var(--success);font-size:0.875rem;text-align:center;padding:20px 0;">✓ Проблем не найдено</p>`;
    } else {
      if (r.issues.length) {
        html += `<div class="stats-section-title">Проблемы</div>`;
        const typeName = {small_box:'малая', overlap:'пересеч.', out_of_bounds:'вне', aspect:'аспект', nested_box:'вложено'};
        r.issues.forEach(it => {
          const detailShort = escapeHtml(String(it.detail).slice(0,70));
          html += `<div class="validator-issue ${it.type}" data-image-id="${it.image_id}">`;
          html += `<span class="vi-type">${typeName[it.type] || it.type}</span>`;
          html += `<span class="vi-name">${escapeHtml(it.filename)}</span>`;
          html += `<span class="vi-detail">${detailShort}</span>`;
          html += `</div>`;
        });
      }
      if (r.unannotated.length) {
        html += `<div class="stats-section-title" style="margin-top:16px;">Без разметки (${r.unannotated.length})</div>`;
        r.unannotated.forEach(it => {
          html += `<div class="validator-issue aspect" data-image-id="${it.id}">`;
          html += `<span class="vi-type">пусто</span>`;
          html += `<span class="vi-name">${escapeHtml(it.filename)}</span>`;
          html += `</div>`;
        });
      }
    }
    body.innerHTML = html;
    body.querySelectorAll('.validator-issue').forEach(el => {
      el.onclick = async () => {
        const iid = parseInt(el.dataset.imageId, 10);
        closeValidateModal();
        if (viewMode === 'trash') { viewMode = 'main'; updateSectionUI(); }
        await loadImages();
        await selectImage(iid, {autoAutolabel: false, skipDirtyCheck: true});
      };
    });
  } catch (e) { body.innerHTML = '<p style="color:var(--danger);">Ошибка: ' + escapeHtml(String(e.message || e)) + '</p>'; }
}
function closeValidateModal() { closeModal('validateModal'); }

/* ===== Similar ===== */
async function openSimilarModal() {
  if (!currentImageId) return;
  const body = document.getElementById('similarBody');
  body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;padding:8px 0;">Ищу похожие…</p>';
  openModal('similarModal');
  try {
    const r = await api(`/api/projects/${currentProjectId}/similar/${currentImageId}`);
    body.innerHTML = '';
    if (!r.items.length) {
      body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;padding:12px 0;text-align:center;">Похожих кадров не найдено</p>';
      return;
    }
    r.items.forEach(it => {
      const row = document.createElement('div');
      row.className = 'similar-row';
      const img = document.createElement('img');
      img.className = 'similar-thumb'; img.loading = 'lazy';
      img.src = `/api/images/${it.id}/thumb`;
      row.appendChild(img);
      const info = document.createElement('div');
      info.className = 'similar-info';
      const nm = document.createElement('div');
      nm.className = 'similar-name'; nm.textContent = it.filename;
      const meta = document.createElement('div');
      meta.className = 'similar-meta';
      meta.textContent = `Hamming: ${it.distance} · рамок: ${it.annotation_count}`;
      info.appendChild(nm); info.appendChild(meta);
      row.appendChild(info);
      const actions = document.createElement('div');
      actions.className = 'similar-actions';
      const openBtn = document.createElement('button');
      openBtn.className = 'btn btn-ghost btn-sm'; openBtn.textContent = 'Открыть';
      openBtn.onclick = async () => {
        closeSimilarModal();
        if (viewMode === 'trash') { viewMode = 'main'; updateSectionUI(); }
        await selectImage(it.id, {autoAutolabel: false, skipDirtyCheck: true});
      };
      actions.appendChild(openBtn);
      if (it.annotation_count > 0) {
        const copyBtn = document.createElement('button');
        copyBtn.className = 'btn btn-primary btn-sm';
        copyBtn.textContent = `Копировать (${it.annotation_count})`;
        copyBtn.onclick = async () => {
          const meta = allImages.find(x => x.id === currentImageId);
          if (meta && (meta.annotation_count || 0) > 0) {
            const ok = await showConfirm('Перезаписать разметку?',
              `На текущем кадре уже есть ${meta.annotation_count} рамок. Они будут заменены на ${it.annotation_count}.`,
              { okText: 'Заменить', danger: true });
            if (!ok) return;
          }
          try {
            const res = await api(`/api/images/${currentImageId}/copy_annotations_from/${it.id}`, {method:'POST'});
            boxes = await api(`/api/images/${currentImageId}/annotations`);
            renderBoxes({ animateIndices: new Set(boxes.map((_, i) => i)) });
            resetHistory(); markClean();
            await loadImages(); closeSimilarModal();
            setStatus(`Скопировано рамок: ${res.count}`); haptic('success');
          } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
        };
        actions.appendChild(copyBtn);
      }
      row.appendChild(actions);
      body.appendChild(row);
    });
  } catch (e) { body.innerHTML = '<p style="color:var(--danger);">Ошибка: ' + escapeHtml(String(e.message || e)) + '</p>'; }
}
function closeSimilarModal() { closeModal('similarModal'); }

/* ===== Version history ===== */
const VERSION_HISTORY = [
{ version: 'V5.5', current: true, changes: [
    'Файлы проекта разбиты и структурированы',
  ]},
  { version: 'V5.4.4', changes: [
    'Zoom-кнопки на холсте снова работают: pointerdown на viewport больше',
    '  не перехватывает клики по .zoom-controls.',
    'Убрана избыточная кнопка «100%»',
    'Интенсивность нажатия кнопок смягчена: овершут 4px вместо 6px, провал 0.95, длительность 400ms.',
    'Окно горячих клавиш (H) дополнено: Cmd-варианты для macOS,',
    '  Backspace, ⇧⌘Z, Numpad-клавиши, новая секция «Мышь и жесты».',
  ]},
  { version: 'V5.4.3', changes: [
    'H / ? — toggle: то же нажатие закрывает окно горячих клавиш.',
    'Кнопка «?» перенесена из тулбара в сайдбар, слева от настроек.',
    'Кнопка «Назначить тег» скрывается, когда ничего не выделено,',
    '  появляется только при активном выделении.',
  ]},
  { version: 'V5.4.2', changes: [
  'Анимация нажатия кнопок: press-down 70ms → overshoot 60ms →',
    '  settle 20ms → return. Bounce через keyframe, не через CSS transition.',
    'Работает через JS-триггер на mousedown — независимо от специфичности',
    '  CSS-правил для button (фикс не сработал через чистый CSS).',
  ]},
  { version: 'V5.4.1', changes: [
    'Скроллбар в модалках прижат к самому правому краю — как в системных окнах.',
    'Убран scrollbar-gutter: stable, который резервировал 15px справа и сдвигал контент.',
    'Модалки: padding только сверху/снизу, боковые отступы заданы дочерним элементам.',
    'Контент симметричен: 24px слева / 24px справа от любого инпута, кнопки, сегмента.',
    'Кнопки в модалках и тулбаре больше не выходят за границы своих контейнеров:',
    '  лифт -1px, компактная тень, иконки масштабируются от центра без Y-сдвига.',
    'Сайдбар — строго overflow: hidden (без визуальных утечек за края).',
    'Мягкий hover-lift сохранён: bounce остался, но не выпрыгивает из плашки.',
  ]},
  { version: 'V5.4.0', changes: [
    'Pointer events: единый ввод мышь/тач/перо, pinch-zoom, панорама двумя пальцами. Работает на iPad.',
    'FLIP-анимация списка: смена фильтра/сортировки/удаление перестраивает строки плавно.',
    'Bulk-tag menu в тулбаре: выдели N фото → один клик по тегу в меню.',
    'Импорт датасета: in-memory pHash-бакеты + batch-commit — до ×20 быстрее на больших zip.',
    'Хендлы, чекбоксы и строки списка увеличены для пальцев (pointer: coarse).',
  ]},
  { version: 'V5.3.0', changes: [
    'Motion: реальный hover-lift (-3px / -2px / scale), settle-плюх при рисовании рамки, draw-dot, каскад после авторазметки, кроссфейд кадра.',
    'Fix XSS: setStatus экранирует по умолчанию.',
    'Fix: авторазметка сохраняет замороженные рамки.',
    'Fix: копирование разметки предупреждает о перезаписи.',
    'Perf: batch /api/images/batch_tags, кэш DCT-таблицы.',
    'Cmd/Ctrl+S — сохранить, H — toggle окна горячих клавиш.',
    'freeze слоёв ≤ 9 (реальный стек YOLOv8n).',
  ]},
  { version: 'V5.2.1', changes: [
    'Fix: сообщение бэкапа больше не выходит за рамки —',
    '  #dialogText получил white-space: pre-wrap + word-break.',
    'Скроллбар прижат вплотную к правому краю модалки:',
    '  .modal перешёл на асимметричный padding, .modal-body',
    '  доходит до края — thumb у самой границы, как нативный.',
  ]},
  { version: 'V5.2.0', changes: [
    'Импорт датасета целиком: если в zip есть и картинки, и разметка —',
    '  фотографии загружаются в проект, разметка привязывается к ним.',
    '  Дубликаты по pHash отсекаются, дедуп имён через make_unique_filename.',
    'История статусов: in-memory лог на 1000 событий, endpoint GET/DELETE /api/logs.',
    '  Кнопка в настройках → модалка с фильтрами по уровню и категории.',
    'Бэкап проекта: POST /api/projects/{id}/backup — полная копия в',
    '  backups/backup_project_{id}_{name}.zip (перезаписывается при повторе).',
    'Скроллбар в меню: тонкий thumb с прозрачной рамкой, отступ от текста.',
  ]},
  { version: 'V5.1.1', changes: [
    'Fix: custom-select menu вынесено в document.body — меню открывается',
    '  под триггером, а не уезжает вбок из-за backdrop-filter модалки.',
    'Fix: тултипы больше не всплывают на программный фокус в модалке.',
    'Возвращены apple-style hover: translateY(-1px) + тень для кнопок,',
    '  scale(1.15) для иконок, spring-возврат с overshoot ~1.05.',
    'Toolbar: overflow visible + flex-wrap — hover-анимации без скроллбара.',
  ]},
  { version: 'V5.1.0', changes: [
    'Кастомные тултипы вместо браузерных title — не обрезаются overflow',
    'Убран hover-scale у кнопок (не выходят за границы меню и тулбара)',
    'model-row / stat-card: hover без подъёма, только тень',
    'Анимации добавлены у всех интерактивных элементов: label-меню, чекбоксы,',
    '  радио, .link-btn, .version-badge, .segmented, .search-clear, color-picker,',
    '  .img-action, .trash-act, .proj-del, .custom-select-option, .save-indicator (пульс)',
    'Liquid Glass: modal/backdrop/меню/тулбар с backdrop-filter + градиентом',
    'Materialization-анимация модалок: scale + blur → 1 + blur(0)',
    'Reduce Motion покрывает все новые hover/press',
  ]},
  { version: 'V5.0.0', changes: [
    'Motion-токены Apple HIG + Haptics + Skeleton shimmer',
    'Кастомные дропдауны OpenImages V7 / COCO',
  ]},
  { version: 'V4.5.0', changes: [
    'Дефолт — yolov8n-oiv7.pt (в OpenImages V7 есть Pig, в COCO — нет)',
    'Авторазметка фильтрует классы: pig/wild boar/boar/hog/piglet/swine',
    'SSE bootstrap корректно закрывается, retry скачивания',
    'batch_restore восстанавливает с уникальными именами',
    'Валидация hex-цвета тега, logging, host 127.0.0.1',
  ]},
  { version: 'V4.4.8', changes: [
    'В блок подсказок вернулась легенда цветов рамок (ручная / ≥ 0.75 / 0.5–0.75 / < 0.5)',
    'В легенду добавлен пункт «заморожена» (пунктирная серая рамка, hotkey L)',
  ]},
  { version: 'V4.4.7', changes: [
    'Длинные названия опций в кастомных селектах больше не обрезаются',
    'Меню селекта растягивается под содержимое (до 360px)',
    'Тексты опций предобучения укорочены для узких полей',
  ]},
  { version: 'V4.4.6', changes: [
    'Кастомные выпадающие списки — скруглённое меню в стиле интерфейса',
    'Переключение модели кликом по всей строке работает всегда',
  ]},
  { version: 'V4.4.5', changes: [
    'Статус скачивания модели авто-скрывается через 5 секунд',
    'При открытии настроек не показывается устаревший статус done/error',
    'Клик по всей строке модели активирует её',
    'Переключение модели больше не пересобирает список',
    'Все <select> в UI приведены к закруглённому виду через CSS',
  ]},
  { version: 'V4.4.4', changes: [
    'SSE-статус автозагрузки дефолтной модели при первом запуске',
    'Кнопка ручного скачивания YOLO-модели (COCO / OpenImages V7, n/s/m)',
    'Прогресс скачивания в реальном времени',
    'Авто-активация первой скачанной / обученной модели',
  ]},
  { version: 'V4.4.3', changes: [
    'При первом запуске модель yolov8n.pt скачивается автоматически',
    'После обучения новая модель автоматически становится активной',
    'Клик «Авторазметка» без модели даёт понятную подсказку',
  ]},
  { version: 'V4.4.2', changes: [
    'Разрешено переименование и удаление pig.pt',
    'Удаление блокируется только для активной модели и последней в папке',
    'Кнопки карандаша/корзины у всех моделей',
  ]},
  { version: 'V4.4.1', changes: [
    'Прогресс и эпоха обучения в UI корректны (строгий regex)',
    'Убрано монотонное условие прогресса (залипало на 89.9%)',
    'Предупреждение в форме обучения при недостатке размеченных фото',
    'Дефолтные эпохи 100',
    'Возможность задать имя обучаемой модели и переименовать существующую',
  ]},
  { version: 'V4.4', changes: [
    'Выбор предобученного датасета: COCO или OpenImages V7',
    'Параметры fine-tune: freeze, lr0, patience, cos_lr, warmup',
    'Опция «Текущая активная модель» для continual learning',
    'prepare_training_dataset: отсеивание неразмеченных, честный train/val split',
  ]},
  { version: 'V4.3.1', changes: [
    'Кликабельной сделана только сама версия (Vn.n.n)',
    'Сайдбар: убран двойной вертикальный скролл',
    'Модалка статистики: убран вложенный скролл',
    'Fix: диалог подтверждения поверх открытых модалок',
  ]},
  { version: 'V4.3', changes: [
    'Из валидатора удалены near_duplicate и possible_missed',
    'Версия приложения стала кликабельной — история версий',
    'Fix: case() в project_stats (500 ошибка в статистике)',
    'Глобальный exception handler',
  ]},
  { version: 'V4.2', changes: [
    'Pydantic-схемы для аннотаций и batch-запросов',
    'Индексы БД (images, annotations, tags, image_tags)',
    'Кэш YOLO-моделей, bucket-поиск pHash',
    'Защита от path traversal и zip-slip',
    'TOCTOU-фиксы в train/start и batch/start',
    'Sync upload/import (FastAPI threadpool)',
    'SSE с threading.Event вместо sleep-поллинга',
    'Focus-trap в модалках, Escape закрывает верхнюю',
    'Counter-scale handles/labels при zoom',
    'Blob-экспорт, ARIA-атрибуты, prefers-reduced-motion',
  ]},
  { version: 'V4.1', changes: [
    'Тег-чипсы под холстом (1 клик = назначить/снять)',
    'Инлайн-создание тега прямо из чипс-бара',
    'Заморозка/разморозка рамок (L)',
    'Хоткеи N/P/R/L/H и окно всех шорткатов (?)',
    'Улучшенный валидатор',
    'CSV-экспорт статистики проекта',
  ]},
  { version: 'V4.0', changes: [
    'Virtual scrolling списка изображений',
    'Превью-миниатюры 64×64 (кэш на сервере)',
    'SSE-прогресс массовой авторазметки',
    'Фикс z-index диалоговых окон',
  ]},
  { version: 'V3.11', changes: [
    'Обучение модели прямо из UI + SSE-прогресс',
    'Выбор активной модели',
    'Кластеризация похожих кадров по pHash',
  ]},
  { version: 'V3.10', changes: [
    'Импорт разметки: COCO / YOLO / CVAT / Label Studio',
    'Train / Val / Test split при экспорте',
    'Поиск по имени, теги, фильтр по тегу',
    'Валидатор разметки',
  ]},
  { version: 'V3.9', changes: [
    'Zoom/Pan холста',
    '«Принять и далее» (Enter)',
    'Флаг сложных кадров (F)',
    'Мультивыбор и групповые операции над рамками',
  ]},
  { version: 'V3.8', changes: [
    'Кастомные модалки вместо alert/confirm/prompt',
    'Экспорт с выбором имён',
    'Фиксация расширения при переименовании',
  ]},
  { version: 'V3.7', changes: [
    'Уникальные имена файлов (name (N))',
    'Кнопка переименования изображения',
  ]},
  { version: 'V3.6', changes: [
    'Статистика проекта',
    'Автоочистка корзины через N дней',
    'Тема «Авто»',
  ]},
  { version: 'V3.5', changes: [
    '4 уровня confidence для рамок',
    'XOR-фильтры',
    'Корзина с восстановлением',
  ]},
  { version: 'V3.3', changes: [
    'pHash-дедупликация при загрузке',
    'Удаление проектов',
  ]},
  { version: 'V3.0', changes: [
    'Zoom/Pan холста, undo/redo',
    'Мультивыбор, нудж стрелками',
    'Флаг сложных кадров',
  ]},
  { version: 'V2.0', changes: [
    'Корзина и мягкое удаление',
    'Импорт разметки',
    'Экспорт статистики',
  ]},
  { version: 'V1.0', changes: [
    'Первый MVP: загрузка, letterbox 640×640',
    'Авторазметка YOLO, экспорт YOLO/COCO',
  ]},
];
function openVersions() { renderVersions(); openModal('versionsModal'); }
function closeVersions() { closeModal('versionsModal'); }
function renderVersions() {
  const list = document.getElementById('versionsList');
  if (!list) return;
  list.innerHTML = '';
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
      cur.className = 'version-current'; cur.textContent = 'текущая';
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
    list.appendChild(div);
  });
}

/* ===== Shortcuts / Settings ===== */
function openShortcuts() { openModal('shortcutsModal'); }
function closeShortcuts() { closeModal('shortcutsModal'); }
async function openSettings() {
  updateThemeSegment();
  document.getElementById('hideHintsToggle').checked = getHideHints();
  try {
    const s = await api('/api/settings/trash_ttl');
    document.getElementById('trashTtlInput').value = s.days;
    _originalTrashTtlDays = s.days;
  } catch (e) { document.getElementById('trashTtlInput').value = 30; _originalTrashTtlDays = 30; }
  await loadModelsIntoUI();
  updateCurrentProjectInfo();
  try {
    const bs = await api('/api/models/bootstrap/status');
    if (bs.status === 'downloading') renderBootstrapStatus(bs);
    else renderBootstrapStatus({status: 'idle'}, {skipTerminal: true});
  } catch(e) {}
  openModal('settingsModal');
}
function closeSettings() { closeModal('settingsModal'); }
async function saveSettings() {
  const days = parseInt(document.getElementById('trashTtlInput').value, 10);
  if (isNaN(days) || days < 0) { setStatus('Введите число ≥ 0'); return; }
  const changed = (days !== _originalTrashTtlDays);
  try {
    await api('/api/settings/trash_ttl', {method:'POST', body: new URLSearchParams({days: String(days)})});
    _originalTrashTtlDays = days;
    closeSettings();
    if (changed) setStatus(`Автоочистка: ${days === 0 ? 'выключена' : days + ' дн.'}`);
    haptic('success');
    if (viewMode === 'trash') await loadImages();
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function downloadModel() {
  const pretrain = document.getElementById('downloadPretrain').value;
  const size = document.getElementById('downloadSize').value;
  try {
    await api('/api/models/download', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ size, pretrain }),
    });
    setStatus(`<span class="status-spinner"></span>Скачиваем yolov8${size}${pretrain === 'oiv7' ? '-oiv7' : ''}.pt…`, 0, null, { html: true });
    subscribeBootstrapEvents(); haptic('light');
  } catch (e) {
    if (e.status === 409) setStatus('Уже идёт скачивание другой модели');
    else setError('Ошибка: ' + String(e.message).slice(0,140));
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
      wrap.appendChild(e); return;
    }
    r.models.forEach(m => {
      const row = document.createElement('div');
      row.className = 'model-row' + (m.name === r.active ? ' active' : '');
      row.dataset.modelName = m.name;
      row.onclick = async (e) => {
        if (e.target.closest('.model-edit') || e.target.closest('.model-del')) return;
        const curActiveEl = document.querySelector('#modelsList .model-row.active');
        const curActive = curActiveEl ? curActiveEl.dataset.modelName : null;
        if (m.name === curActive) return;
        await activateModel(m.name);
      };
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.className = 'model-radio';
      radio.name = 'active_model_radio';
      radio.checked = (m.name === r.active);
      radio.onclick = (e) => { e.preventDefault(); };
      row.appendChild(radio);
      const name = document.createElement('span');
      name.className = 'model-name'; name.textContent = m.name;
      row.appendChild(name);
      const meta = document.createElement('span');
      meta.className = 'model-meta';
      meta.textContent = fmtSize(m.size) + ' · ' + m.created_at.replace('T', ' ').slice(0, 16);
      row.appendChild(meta);
      const editBtn = document.createElement('button');
      editBtn.className = 'model-edit';
      editBtn.setAttribute('aria-label','Переименовать модель'); editBtn.dataset.tooltip = 'Переименовать';
      editBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>';
      editBtn.onclick = async (e) => { e.stopPropagation(); await renameModel(m.name); };
      row.appendChild(editBtn);
      const del = document.createElement('button');
      del.className = 'model-del';
      del.setAttribute('aria-label','Удалить модель'); del.dataset.tooltip = 'Удалить';
      del.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>';
      del.onclick = async (e) => { e.stopPropagation(); await deleteModel(m.name); };
      row.appendChild(del);
      wrap.appendChild(row);
    });
  } catch (e) {
    wrap.innerHTML = '<div style="font-size:0.8125rem;color:var(--danger);padding:8px 4px;">Ошибка: ' + escapeHtml(e.message) + '</div>';
  }
}
async function activateModel(name) {
  try {
    await api('/api/models/activate', {method:'POST', body: new URLSearchParams({name})});
    document.querySelectorAll('#modelsList .model-row').forEach(row => {
      const isActive = (row.dataset.modelName === name);
      row.classList.toggle('active', isActive);
      const radio = row.querySelector('.model-radio');
      if (radio) radio.checked = isActive;
    });
    setStatus(`Активная модель: ${name}`); haptic('selection');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
}
async function deleteModel(name) {
  const ok = await showConfirm(`Удалить модель «${name}»?`, 'Файл .pt будет удалён с диска.', { okText: 'Удалить', danger: true });
  if (!ok) return;
  haptic('warning');
  try { await api(`/api/models/${encodeURIComponent(name)}`, {method:'DELETE'}); await loadModelsIntoUI(); setStatus('Модель удалена'); }
  catch (e) {
    if (e.status === 400) setStatus(String(e.message).slice(0, 160));
    else setError('Ошибка: ' + String(e.message).slice(0, 160));
  }
}
async function renameModel(oldName) {
  const stem = oldName.toLowerCase().endsWith('.pt') ? oldName.slice(0, -3) : oldName;
  const newName = await showPrompt('Переименовать модель', {
    text: `Новое имя для «${oldName}»:`, defaultValue: stem,
    hint: 'Латиница, цифры, дефис, подчёркивание, точка, пробел, скобки. Расширение .pt добавится автоматически.',
    okText: 'Переименовать',
  });
  if (newName === null) return;
  const nm = String(newName).trim();
  if (!nm) { setStatus('Пустое имя'); return; }
  if (nm === stem) return;
  try {
    const r = await api(`/api/models/${encodeURIComponent(oldName)}/rename`, { method: 'POST', body: new URLSearchParams({ new_name: nm }) });
    await loadModelsIntoUI();
    setStatus(`Переименовано: ${r.old} → ${r.name}`); haptic('success');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,140)); }
}

/* ===== Training ===== */
async function openTrainModal() {
  closeSettings();
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  const warnEl = document.getElementById('trainDatasetWarn');
  warnEl.style.display = 'none';
  try {
    const s = await api(`/api/projects/${currentProjectId}/stats`);
    const annotated = s.annotated_images || 0;
    if (annotated < 30) {
      warnEl.style.display = 'block'; warnEl.style.background = 'rgba(255,149,0,0.12)'; warnEl.style.color = 'var(--warning)';
      warnEl.innerHTML = `⚠ <b>Размечено всего ${annotated} из ${s.total_images} фото.</b> Для нормального обучения нужно <b>минимум 30–50</b>, лучше 100–300.`;
    } else if (annotated < 100) {
      warnEl.style.display = 'block'; warnEl.style.background = 'rgba(10,132,255,0.1)'; warnEl.style.color = 'var(--accent)';
      warnEl.innerHTML = `ℹ Размечено ${annotated} фото. Обучаемо, но лучше 100+. Поставь <b>эпох ≥ 100</b>.`;
    }
  } catch(e) {}
  setTimeout(() => { openModal('trainModal'); refreshTrainStatus(); }, 80);
}
function closeTrainModal() {
  closeModal('trainModal');
  if (trainEventSource) { try { trainEventSource.close(); } catch(e) {} trainEventSource = null; }
}
async function startTraining() {
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  const pretrain = document.getElementById('trainPretrain').value;
  const baseModel = document.getElementById('trainBaseModel').value;
  const customName = document.getElementById('trainModelName').value.trim();
  const epochs = parseInt(document.getElementById('trainEpochs').value, 10) || 50;
  const imgsz = parseInt(document.getElementById('trainImgsz').value, 10) || 640;
  const freeze = parseInt(document.getElementById('trainFreeze').value, 10);
  const lr0 = parseFloat(document.getElementById('trainLr0').value);
  const fd = new FormData();
  fd.append('project_id', String(currentProjectId));
  fd.append('base_model', baseModel);
  fd.append('pretrain_dataset', pretrain);
  fd.append('model_name', customName);
  fd.append('epochs', String(epochs));
  fd.append('imgsz', String(imgsz));
  fd.append('freeze', String(isNaN(freeze) ? 8 : Math.min(9, Math.max(0, freeze))));
  fd.append('lr0', String(isNaN(lr0) ? 0.001 : lr0));
  try {
    await api('/api/train/start', {method:'POST', body: fd});
    document.getElementById('trainForm').style.display = 'none';
    document.getElementById('trainProgressWrap').style.display = '';
    document.getElementById('trainStartBtn').style.display = 'none';
    document.getElementById('trainStopBtn').style.display = '';
    setStatus('Обучение запущено');
    subscribeTrainEvents(); haptic('success');
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,140)); }
}
async function stopTraining() {
  try { await api('/api/train/stop', {method:'POST'}); setStatus('Останавливаю...'); }
  catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); }
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
  if (trainEventSource) { try { trainEventSource.close(); } catch(e) {} }
  const es = new EventSource('/api/train/events');
  trainEventSource = es;
  es.onmessage = (ev) => {
    try {
      const s = JSON.parse(ev.data);
      renderTrainState(s);
      if (s.status === 'done' || s.status === 'error' || s.status === 'stopped') {
        es.close(); trainEventSource = null; loadModelsIntoUI();
      }
    } catch(e) {}
  };
  es.onerror = () => { try { es.close(); } catch(e) {} trainEventSource = null; };
}
function renderTrainState(s) {
  const badge = document.getElementById('trainStatusBadge');
  const map = {idle:'Ожидание', preparing:'Подготовка', running:'Обучение', stopping:'Остановка', done:'Готово', error:'Ошибка', stopped:'Остановлено'};
  badge.textContent = map[s.status] || s.status;
  badge.className = 'train-status-badge ' + (s.status === 'stopping' || s.status === 'preparing' ? 'running' : s.status);
  document.getElementById('trainProgressFill').style.width = (s.progress || 0) + '%';
  document.getElementById('trainEpochText').textContent = `Эпоха ${s.current_epoch || 0} / ${s.total_epochs || 0}`;
  document.getElementById('trainPercentText').textContent = (s.progress || 0).toFixed(1) + '%';
  document.getElementById('trainMessage').textContent = s.message || '';
  document.getElementById('trainModelResult').textContent = s.model_name ? `→ ${s.model_name}` : '';
  const logEl = document.getElementById('trainLog');
  if (logEl && s.log_lines && s.log_lines.length) {
    logEl.textContent = s.log_lines.slice(-80).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
  }
  if (s.status === 'done' || s.status === 'error' || s.status === 'stopped') {
    document.getElementById('trainStartBtn').style.display = '';
    document.getElementById('trainStopBtn').style.display = 'none';
  }
}

/* ===== Batch autolabel ===== */
async function autolabelAllUnlabeled() {
  if (viewMode === 'trash') return;
  if (batchRunning) { setStatus('Батч уже идёт'); return; }
  const unlabeled = allImages.filter(i => (i.annotation_count || 0) === 0);
  if (!unlabeled.length) { setStatus('Все уже размечены'); return; }
  const ok = await showConfirm(`Авторазметить ${unlabeled.length} ${pluralImages(unlabeled.length)}?`,
    'Результат сохранится автоматически.', { okText: 'Запустить' });
  if (!ok) return;
  const ids = unlabeled.map(i => i.id);
  try {
    await api('/api/autolabel/batch/start', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ image_ids: ids, project_id: currentProjectId }),
    });
    batchRunning = true;
    subscribeBatchEvents();
  } catch (e) {
    if (e.status === 501) setStatus('Авторазметка недоступна: нет активной модели. Открой Настройки → Обучить модель.', 8000);
    else setError('Ошибка: ' + String(e.message).slice(0,140));
  }
}
function subscribeBatchEvents() {
  if (batchEventSource) { try { batchEventSource.close(); } catch(e) {} }
  const es = new EventSource('/api/autolabel/batch/events');
  batchEventSource = es;
  es.onmessage = (ev) => {
    try {
      const s = JSON.parse(ev.data);
      renderBatchState(s);
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
    } catch(e) {}
  };
  es.onerror = () => { try { es.close(); } catch(e) {} batchEventSource = null; batchRunning = false; };
}
function renderBatchState(s) {
  const fill = document.getElementById('progressFill');
  const label = document.getElementById('progressLabel');
  const text = document.getElementById('progressText');
  const btn = document.getElementById('batchAutolabelBtn');
  if (s.status === 'running') {
    label.textContent = 'Авторазметка';
    const pct = s.total > 0 ? (s.done / s.total * 100) : 0;
    fill.style.width = pct.toFixed(1) + '%'; fill.classList.add('batch');
    text.textContent = `${s.done} / ${s.total}`;
    btn.disabled = true; btn.style.opacity = '0.5';
    if (s.current_filename) setStatus(`Авторазметка: ${s.done}/${s.total} · ${s.current_filename}`, 600000);
  } else {
    btn.disabled = false; btn.style.opacity = '';
    fill.classList.remove('batch');
    if (s.status === 'done') { setSuccess(`Готово: ${s.done - s.failed} из ${s.total}` + (s.failed ? `, ошибок: ${s.failed}` : ''), 6000); haptic('success'); }
    else if (s.status === 'stopped') setStatus(`Остановлено. Обработано: ${s.done - s.failed}, ошибок: ${s.failed}`, 6000);
    else if (s.status === 'error') setError('Ошибка батча: ' + s.message, 6000);
    setTimeout(() => updateProgress(), 1500);
  }
}

/* ===== Export ===== */
async function downloadFile(url, fallbackName) {
  try {
    setStatus('Готовим файл…', 60000);
    const res = await fetch(url);
    if (!res.ok) { let msg = 'Ошибка экспорта'; try { msg = (await res.json()).detail || msg; } catch(e) {} throw new Error(msg); }
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
  } catch(e) { setError('Ошибка экспорта: ' + String(e.message).slice(0,160)); }
}
function toggleExportMenu(e) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('exportMenu');
  const btn = document.getElementById('exportBtn');
  const isOpen = menu.classList.contains('open');
  document.querySelectorAll('.sort-menu').forEach(m => m.classList.remove('open'));
  if (isOpen) return;
  const r = btn.getBoundingClientRect();
  const MENU_W = 200;
  let left = r.left;
  if (left + MENU_W > window.innerWidth - 8) left = Math.max(8, window.innerWidth - MENU_W - 8);
  menu.style.left = left + 'px'; menu.style.top = (r.bottom + 6) + 'px';
  menu.classList.add('open');
}
function exportYolo() { exportFormat = 'yolo'; document.getElementById('exportMenu').classList.remove('open'); openExportModal(); }
function exportCoco() { exportFormat = 'coco'; document.getElementById('exportMenu').classList.remove('open'); openExportModal(); }
function openExportModal() { openModal('exportModal'); }
function closeExportModal() { closeModal('exportModal'); }
async function executeExport() {
  if (!currentProjectId) { setStatus('Сначала выбери проект'); return; }
  const naming = (document.querySelector('input[name="export_naming"]:checked') || {}).value || 'numbered';
  const split = (document.querySelector('input[name="export_split"]:checked') || {}).value || 'none';
  closeExportModal();
  const url = `/api/projects/${currentProjectId}/export/${exportFormat}?naming=${encodeURIComponent(naming)}&split=${encodeURIComponent(split)}`;
  const fallback = `${exportFormat}_project_${currentProjectId}.zip`;
  await downloadFile(url, fallback);
}

/* ===== Navigation ===== */
async function navigateImage(direction) {
  if (viewMode === 'trash') return;
  if (!imagesList.length) return;
  let idx = imagesList.findIndex(img => img.id === currentImageId);
  if (idx < 0) idx = direction > 0 ? -1 : imagesList.length;
  idx += direction;
  if (idx < 0) idx = 0;
  if (idx >= imagesList.length) idx = imagesList.length - 1;
  const target = imagesList[idx];
  if (!target || target.id === currentImageId) return;
  await selectImage(target.id);
}
async function navigateToNextUnlabeled() {
  if (viewMode === 'trash') return;
  if (!imagesList.length) return;
  const idx = imagesList.findIndex(i => i.id === currentImageId);
  for (let i = idx + 1; i < imagesList.length; i++) if ((imagesList[i].annotation_count || 0) === 0) { await selectImage(imagesList[i].id, {skipDirtyCheck: true}); return; }
  for (let i = 0; i < Math.max(0, idx); i++) if ((imagesList[i].annotation_count || 0) === 0) { await selectImage(imagesList[i].id, {skipDirtyCheck: true}); return; }
  setStatus('Все размечены');
}
async function navigateToPrevUnlabeled() {
  if (viewMode === 'trash') return;
  if (!imagesList.length) return;
  let idx = imagesList.findIndex(i => i.id === currentImageId);
  if (idx < 0) idx = imagesList.length;
  for (let i = idx - 1; i >= 0; i--) if ((imagesList[i].annotation_count || 0) === 0) { await selectImage(imagesList[i].id, {skipDirtyCheck: true}); return; }
  for (let i = imagesList.length - 1; i > idx; i--) if ((imagesList[i].annotation_count || 0) === 0) { await selectImage(imagesList[i].id, {skipDirtyCheck: true}); return; }
  setStatus('Все размечены');
}
async function acceptAndNext() {
  if (!currentImageId) return;
  try {
    await api(`/api/images/${currentImageId}/annotations`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(boxes),
    });
    markClean(); await loadImages();
  } catch (e) { setError('Ошибка: ' + String(e.message).slice(0,120)); return; }
  if (!imagesList.length) return;
  const idx = imagesList.findIndex(i => i.id === currentImageId);
  let next = null;
  for (let i = idx + 1; i < imagesList.length; i++) if ((imagesList[i].annotation_count || 0) === 0) { next = imagesList[i]; break; }
  if (!next) for (let i = 0; i < idx; i++) if ((imagesList[i].annotation_count || 0) === 0) { next = imagesList[i]; break; }
  if (!next && idx + 1 < imagesList.length) next = imagesList[idx + 1];
  if (next) { await selectImage(next.id, {skipDirtyCheck: true}); setStatus(`Принято → ${next.filename}`); }
  else setStatus('Достигнут конец списка');
}

/* ===== Boxes ===== */
function confColor(conf) {
  if (conf == null) return 'var(--box-manual)';
  if (conf >= 0.75) return 'var(--box-high)';
  if (conf >= 0.5) return 'var(--box-mid)';
  return 'var(--box-low)';
}
function confLabelText(b) {
  if (b.confidence == null) return b.label || 'pig';
  return `${b.label || 'pig'} ${b.confidence.toFixed(2)}`;
}
function renderBoxes(opts = {}) {
  const layer = document.getElementById('boxes');
  layer.innerHTML = '';
  const animateIndices = opts.animateIndices || null;
  const settlingIdx = (typeof opts.settlingIdx === 'number') ? opts.settlingIdx : -1;
  const animList = animateIndices ? Array.from(animateIndices) : null;
  boxes.forEach((b, i) => {
    const div = document.createElement('div');
    div.className = 'box';
    if (b.frozen) div.classList.add('frozen');
    if (i === selectedIndex) div.classList.add('selected');
    if (multiSelected.has(i)) div.classList.add('multi-selected');
    if (b.y * 640 < 26) div.classList.add('label-below');
    div.dataset.idx = i;
    div.style.setProperty('--box-color', confColor(b.confidence));
    div.style.left = (b.x * 640) + 'px'; div.style.top = (b.y * 640) + 'px';
    div.style.width = (b.w * 640) + 'px'; div.style.height = (b.h * 640) + 'px';
    if (animList && animList.includes(i)) {
      div.classList.add('box-enter');
      const order = animList.indexOf(i);
      div.style.animationDelay = Math.min(order * 25, 300) + 'ms';
    }
    if (i === settlingIdx) div.classList.add('settling');
    const label = document.createElement('span');
    label.className = 'box-label'; label.textContent = confLabelText(b);
    div.appendChild(label);
    if (!b.frozen) {
      const del = document.createElement('div');
      del.className = 'box-delete'; del.textContent = '×';
      del.setAttribute('role','button');
      del.setAttribute('aria-label','Удалить рамку'); del.dataset.tooltip = 'Удалить';
      del.addEventListener('mousedown', e => e.stopPropagation());
      del.addEventListener('click', e => { e.stopPropagation(); deleteBox(i); });
      div.appendChild(del);
      ['nw','n','ne','e','se','s','sw','w'].forEach(h => {
        const hd = document.createElement('div');
        hd.className = 'handle handle-' + h; hd.dataset.handle = h;
        div.appendChild(hd);
      });
    } else {
      const fr = document.createElement('span');
      fr.className = 'box-freeze-badge'; fr.textContent = '🔒';
      div.appendChild(fr);
    }
    layer.appendChild(div);
  });
  updateDelBoxBtn(); updateFreezeBtn();
}
function updateBoxInPlace(idx) {
  const el = document.querySelector(`#boxes .box[data-idx="${idx}"]`);
  if (!el) return;
  const b = boxes[idx];
  el.style.left = (b.x * 640) + 'px'; el.style.top = (b.y * 640) + 'px';
  el.style.width = (b.w * 640) + 'px'; el.style.height = (b.h * 640) + 'px';
  el.style.setProperty('--box-color', confColor(b.confidence));
  if (b.y * 640 < 26) el.classList.add('label-below'); else el.classList.remove('label-below');
  const lbl = el.querySelector('.box-label');
  if (lbl) lbl.textContent = confLabelText(b);
}
function updateSelectionClasses() {
  document.querySelectorAll('#boxes .box').forEach((el, i) => {
    el.classList.toggle('selected', i === selectedIndex);
    el.classList.toggle('multi-selected', multiSelected.has(i));
  });
  updateDelBoxBtn(); updateFreezeBtn();
}
function updateDelBoxBtn() {
  const btn = document.getElementById('delBoxBtn');
  if (!btn) return;
  const indices = getSelectedIndices();
  const freezable = indices.filter(i => !boxes[i].frozen);
  const ok = freezable.length > 0;
  btn.disabled = !ok; btn.style.opacity = ok ? '' : '0.5';
  btn.innerHTML = (ok && freezable.length > 1) ? `Удалить (${freezable.length}) <kbd>D</kbd>` : `Удалить рамку <kbd>D</kbd>`;
}
function getSelectedIndices() {
  const set = new Set(multiSelected);
  if (selectedIndex >= 0 && selectedIndex < boxes.length) set.add(selectedIndex);
  return Array.from(set).sort((a, b) => a - b);
}
function deleteBox(idx) {
  if (idx < 0 || idx >= boxes.length) return;
  if (boxes[idx].frozen) { setStatus('Рамка заморожена. Нажми L чтобы разморозить.'); return; }
  boxes.splice(idx, 1);
  const newMulti = new Set();
  multiSelected.forEach(i => { if (i < idx) newMulti.add(i); else if (i > idx) newMulti.add(i - 1); });
  multiSelected = newMulti;
  if (selectedIndex === idx) selectedIndex = -1;
  else if (selectedIndex > idx) selectedIndex -= 1;
  renderBoxes(); pushHistory(); markDirty();
}
function deleteSelectedBox() {
  const indices = getSelectedIndices().filter(i => !boxes[i].frozen);
  if (!indices.length) return;
  for (let i = indices.length - 1; i >= 0; i--) boxes.splice(indices[i], 1);
  const removed = indices.length;
  selectedIndex = -1; multiSelected.clear();
  renderBoxes(); pushHistory(); markDirty();
  setStatus(`Удалено: ${removed}`);
}
async function clearBoxes() {
  if (!boxes.length) return;
  if (boxes.length > 1) {
    const ok = await showConfirm('Очистить все рамки?',
      `Будет удалено ${boxes.length} рамок. Можно отменить через Ctrl+Z.`,
      { okText: 'Очистить', danger: true });
    if (!ok) return;
  }
  boxes = []; selectedIndex = -1; multiSelected.clear();
  renderBoxes(); pushHistory(); markDirty();
}
async function saveAnnotations() {
  if (!currentImageId) return;
  try {
    await api(`/api/images/${currentImageId}/annotations`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(boxes),
    });
    markClean(); pulseSaveIndicator();
    await loadImages();
    setStatus(`Сохранено: ${boxes.length} рамок`); haptic('success');
  } catch (e) { setError('Ошибка сохранения: ' + String(e.message).slice(0,140)); }
}
async function runAutolabel() {
  if (!currentImageId) return;
  setStatus('Авторазметка...', 60000);
  try {
    boxes = await api(`/api/images/${currentImageId}/autolabel`, {method:'POST'});
    selectedIndex = -1; multiSelected.clear();
    const animateIndices = new Set(boxes.map((_, i) => i));
    renderBoxes({ animateIndices });
    resetHistory(); markClean();
    await loadImages();
    setStatus(`Авторазметка: ${boxes.length} рамок (сохранено)`); haptic('success');
  } catch (e) {
    haptic('error');
    if (e.status === 501) setStatus('Авторазметка недоступна: нет активной модели. Открой Настройки → Обучить модель.', 8000);
    else setError('Авторазметка недоступна: ' + String(e.message).slice(0,160), 5000);
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
  updateSortUI(); applyFiltersAndRender();
}
function setupSortMenu() {
  const btn = document.getElementById('sortBtn');
  const menu = document.getElementById('sortMenu');
  btn.addEventListener('click', (e) => { e.stopPropagation(); menu.classList.toggle('open'); });
  menu.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', (e) => { e.stopPropagation(); setSortMode(b.dataset.sort); menu.classList.remove('open'); });
  });
  updateSortUI();
}
function setupFilterMenu() {
  const btn = document.getElementById('filterBtn');
  const menu = document.getElementById('filterMenu');
  const cbUA = document.getElementById('filterUnannotated');
  const cbLC = document.getElementById('filterLowConf');
  const cbH = document.getElementById('filterHard');
  cbUA.checked = activeFilter === 'unannotated';
  cbLC.checked = activeFilter === 'lowconf';
  cbH.checked = activeFilter === 'hard';
  btn.addEventListener('click', (e) => { e.stopPropagation(); menu.classList.toggle('open'); });
  menu.addEventListener('click', (e) => e.stopPropagation());
  async function setFilter(name, checked) {
    cbUA.checked = false; cbLC.checked = false; cbH.checked = false;
    if (checked) {
      activeFilter = name;
      if (name === 'unannotated') cbUA.checked = true;
      if (name === 'lowconf') cbLC.checked = true;
      if (name === 'hard') cbH.checked = true;
    } else activeFilter = 'none';
    localStorage.setItem('pdb_filter', activeFilter);
    updateFilterBadge(); applyFiltersAndRender();
  }
  cbUA.addEventListener('change', () => setFilter('unannotated', cbUA.checked));
  cbLC.addEventListener('change', () => setFilter('lowconf', cbLC.checked));
  cbH.addEventListener('change', () => setFilter('hard', cbH.checked));
  updateFilterBadge();
}

/* ===== Pointer / Touch / Mouse ===== */
const viewport = document.getElementById('canvasViewport');
let preDragSnapshot = null;
const _activePointers = new Map();
let _pinchStart = null;

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
  const mxs = _pinchStart.midClientX - vp.left, mys = _pinchStart.midClientY - vp.top;
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
  if (e.pointerType === 'mouse' && e.button !== 0) return;
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
  if (spacePressed) {
    isPanning = true;
    panStart = { x: e.clientX - panX, y: e.clientY - panY };
    viewport.classList.add('panning');
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    return;
  }
  const t = e.target;
  const boxEl = t.closest ? t.closest('.box') : null;
  const isHandle = t.classList && t.classList.contains('handle') && !!t.dataset.handle;
  const isDelete = t.classList && t.classList.contains('box-delete');
  if (isDelete) return;
  preDragSnapshot = snapshot();
  if (isHandle && boxEl) {
    const idx = +boxEl.dataset.idx;
    if (boxes[idx].frozen) return;
    if (e.shiftKey) toggleMultiSelect(idx);
    else { selectedIndex = idx; multiSelected.clear(); }
    const p = getRel(e);
    const o = boxes[idx];
    dragState = { mode:'resize', handle: t.dataset.handle, idx, startX: p.x, startY: p.y, orig: {x:o.x, y:o.y, w:o.w, h:o.h} };
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    updateSelectionClasses(); return;
  }
  if (boxEl) {
    const idx = +boxEl.dataset.idx;
    if (e.shiftKey) toggleMultiSelect(idx);
    else { selectedIndex = idx; multiSelected.clear(); }
    if (boxes[idx].frozen) { updateSelectionClasses(); return; }
    const p = getRel(e);
    const o = boxes[idx];
    dragState = { mode:'move', idx, startX: p.x, startY: p.y, orig: {x:o.x, y:o.y, w:o.w, h:o.h}, moveAll: multiSelected.size > 0 };
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    updateSelectionClasses(); return;
  }
  selectedIndex = -1; multiSelected.clear();
  updateSelectionClasses();
  const p = getRel(e);
  dragState = { mode:'draw', startX: p.x, startY: p.y };
  try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
  const dot = document.createElement('div');
  dot.className = 'draw-dot';
  dot.style.left = (p.x * 640) + 'px';
  dot.style.top = (p.y * 640) + 'px';
  document.getElementById('boxes').appendChild(dot);
  setTimeout(() => { try { dot.remove(); } catch(e) {} }, 160);
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
  if (path.some(el => el && el.classList && (el.classList.contains('modal-backdrop') || el.classList.contains('sidebar')))) return;
  selectedIndex = -1; multiSelected.clear(); updateSelectionClasses();
});
window.addEventListener('pointermove', e => {
  if (_activePointers.has(e.pointerId)) _activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (_pinchStart && _activePointers.size >= 2) { e.preventDefault(); _handlePinch(); return; }
  if (isPanning) { panX = e.clientX - panStart.x; panY = e.clientY - panStart.y; clampPan(); applyTransform(); return; }
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
        boxes[i] = clampBox({ x: so.x + dx, y: so.y + dy, w: so.w, h: so.h, label: so.label, confidence: so.confidence, frozen: so.frozen });
        updateBoxInPlace(i);
      });
    } else {
      const b = boxes[dragState.idx];
      boxes[dragState.idx] = clampBox({ x: o.x + dx, y: o.y + dy, w: o.w, h: o.h, label: b.label, confidence: b.confidence, frozen: b.frozen });
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
    x1 = Math.max(0, x1); y1 = Math.max(0, y1); x2 = Math.min(1, x2); y2 = Math.min(1, y2);
    const b = boxes[dragState.idx];
    boxes[dragState.idx] = { x: x1, y: y1, w: Math.max(0, x2-x1), h: Math.max(0, y2-y1), label: b.label, confidence: b.confidence, frozen: b.frozen };
    updateBoxInPlace(dragState.idx);
    return;
  }
  if (dragState.mode === 'draw') {
    let prev = document.getElementById('drawPreview');
    if (!prev) {
      prev = document.createElement('div');
      prev.id = 'drawPreview'; prev.className = 'box preview';
      document.getElementById('boxes').appendChild(prev);
    }
    const x = Math.min(dragState.startX, p.x);
    const y = Math.min(dragState.startY, p.y);
    const w = Math.abs(p.x - dragState.startX);
    const h = Math.abs(p.y - dragState.startY);
    prev.style.left = (x * 640) + 'px'; prev.style.top = (y * 640) + 'px';
    prev.style.width = (w * 640) + 'px'; prev.style.height = (h * 640) + 'px';
  }
}, { passive: false });

function _endPointer(e) {
  _activePointers.delete(e.pointerId);
  if (_activePointers.size < 2) _pinchStart = null;
  if (isPanning) { isPanning = false; viewport.classList.remove('panning'); return; }
  if (!dragState) return;
  let changed = false;
  let settlingIdx = -1;
  if (dragState.mode === 'draw') {
    const prev = document.getElementById('drawPreview');
    if (prev) prev.remove();
    const p = getRel(e);
    const x = Math.min(dragState.startX, p.x);
    const y = Math.min(dragState.startY, p.y);
    const w = Math.abs(p.x - dragState.startX);
    const h = Math.abs(p.y - dragState.startY);
    if (w > 0.01 && h > 0.01) {
      boxes.push({ x, y, w, h, label:'pig', confidence:null, frozen:false });
      selectedIndex = boxes.length - 1; multiSelected.clear();
      changed = true;
      settlingIdx = boxes.length - 1;
      renderBoxes({ settlingIdx });
    }
  } else if (dragState.mode === 'move' || dragState.mode === 'resize') {
    if (preDragSnapshot && JSON.stringify(preDragSnapshot) !== JSON.stringify(boxes)) {
      changed = true;
      if (dragState.mode === 'move' && dragState.moveAll) {
        getSelectedIndices().forEach(i => { if (boxes[i] && !boxes[i].frozen) boxes[i].confidence = null; });
      } else if (boxes[dragState.idx]) boxes[dragState.idx].confidence = null;
    }
  }
  dragState = null; preDragSnapshot = null;
  if (changed) { pushHistory(); markDirty(); }
}
window.addEventListener('pointerup', _endPointer);
window.addEventListener('pointercancel', _endPointer);

viewport.addEventListener('wheel', (e) => {
  if (!currentImageId) return;
  e.preventDefault();
  const vp = viewport.getBoundingClientRect();
  const factor = e.deltaY < 0 ? 1.15 : 1/1.15;
  zoomAt(e.clientX - vp.left, e.clientY - vp.top, factor);
}, { passive: false });

/* ===== Keyboard ===== */
document.addEventListener('keydown', e => {
  const tag = (e.target && e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
  if (isModalOpen('dialogModal')) {
    if (e.code === 'Escape') { e.preventDefault(); _closeDialog(null); }
    return;
  }
  // H / ? — toggle шпаргалки, даже когда открыта
  if ((e.code === 'KeyH' || e.key === '?') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (isModalOpen('shortcutsModal')) { e.preventDefault(); closeShortcuts(); return; }
    if (MODAL_STACK.length === 0)       { e.preventDefault(); openShortcuts(); return; }
    return;
  }
  if (MODAL_STACK.length) {
    if (e.code === 'Escape') {
      e.preventDefault();
      const top = MODAL_STACK[MODAL_STACK.length - 1];
      if (top === 'previewModal') closePreview();
      else if (top === 'statsModal') closeStats();
      else if (top === 'settingsModal') closeSettings();
      else if (top === 'exportModal') closeExportModal();
      else if (top === 'validateModal') closeValidateModal();
      else if (top === 'tagsManagerModal') closeTagsManager();
      else if (top === 'importModal') closeImportModal();
      else if (top === 'trainModal') closeTrainModal();
      else if (top === 'similarModal') closeSimilarModal();
      else if (top === 'shortcutsModal') closeShortcuts();
      else if (top === 'tagCreateModal') closeTagCreate();
      else if (top === 'versionsModal') closeVersions();
      else if (top === 'logsModal') closeLogs();
      else closeModal(top);
    }
    return;
  }
  const code = e.code || '';
  if (code === 'Space' && !spacePressed) {
    e.preventDefault(); spacePressed = true; viewport.classList.add('space-held'); return;
  }
  if ((e.ctrlKey || e.metaKey) && code === 'KeyS') { e.preventDefault(); saveAnnotations(); return; }
  if ((e.ctrlKey || e.metaKey) && code === 'KeyZ' && !e.shiftKey) { e.preventDefault(); undo(); return; }
  if ((e.ctrlKey || e.metaKey) && (code === 'KeyY' || (e.shiftKey && code === 'KeyZ'))) { e.preventDefault(); redo(); return; }
  if ((e.ctrlKey || e.metaKey) && code === 'KeyA') {
    e.preventDefault();
    if (boxes.length) {
      multiSelected = new Set(boxes.map((_, i) => i));
      selectedIndex = -1; updateSelectionClasses();
      setStatus(`Выделено рамок: ${boxes.length}`);
    }
    return;
  }
  if (!e.ctrlKey && !e.metaKey && !e.altKey) {
    if (code === 'KeyA') { e.preventDefault(); autolabel(); return; }
    if (code === 'KeyS') { e.preventDefault(); saveAnnotations(); return; }
    if (code === 'KeyD') { e.preventDefault(); deleteSelectedBox(); return; }
    if (code === 'KeyC') { e.preventDefault(); clearBoxes(); return; }
    if (code === 'KeyF') { e.preventDefault(); toggleHardCurrent(); return; }
    if (code === 'KeyL') { e.preventDefault(); toggleFreezeSelected(); return; }
    if (code === 'KeyR') { e.preventDefault(); runAutolabel(); return; }
    if (code === 'KeyN') { e.preventDefault(); navigateToNextUnlabeled(); return; }
    if (code === 'KeyP') { e.preventDefault(); navigateToPrevUnlabeled(); return; }
    if (code === 'Enter' || code === 'NumpadEnter') { e.preventDefault(); acceptAndNext(); return; }
    if (code === 'Equal' || code === 'NumpadAdd') { e.preventDefault(); zoomToCenter(1.25); return; }
    if (code === 'Minus' || code === 'NumpadSubtract') { e.preventDefault(); zoomToCenter(0.8); return; }
    if (code === 'Digit0' || code === 'Numpad0') { e.preventDefault(); zoomReset(); return; }
    if (code === 'Escape') {
      selectedIndex = -1; multiSelected.clear(); updateSelectionClasses();
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
      if (indices.length > 1) {
        indices.forEach(i => {
          const b = boxes[i];
          boxes[i] = clampBox({ x: b.x+dx, y: b.y+dy, w: b.w, h: b.h, label: b.label, confidence: null, frozen: false });
        });
      } else if (e.shiftKey) {
        const i = indices[0]; const b = boxes[i];
        boxes[i] = clampBox({ x: b.x, y: b.y, w: b.w+dx, h: b.h+dy, label: b.label, confidence: null, frozen: false });
      } else {
        const i = indices[0]; const b = boxes[i];
        boxes[i] = clampBox({ x: b.x+dx, y: b.y+dy, w: b.w, h: b.h, label: b.label, confidence: null, frozen: false });
      }
      renderBoxes(); pushHistory(); markDirty(); return;
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

/* ===== Init ===== */
async function checkModelsAvailability() {
  try {
    const r = await api('/api/models');
    if (!r.models.length) {
      try { const bs = await api('/api/models/bootstrap/status'); if (bs.status === 'downloading') return; } catch(e) {}
      setStatus('Моделей нет — авторазметка выключена. Скачай или обучи модель в Настройках.', 8000);
    }
  } catch(e) {}
}

document.addEventListener('DOMContentLoaded', () => {
  _installTooltipObserver();
  applyTheme();
  setHideHints(getHideHints());
  showCanvas(false);
  initCustomSelects();
  setupSortMenu();
  setupFilterMenu();
  updateSaveIndicator();
  updateBulkBar();
  updateTrashBar();
  updateSectionUI();
  applyTransform();

  api('/api/version').then(v => {
    if (v && v.version) {
      APP_VERSION = v.version;
      document.querySelectorAll('.version-badge').forEach(b => { b.textContent = v.version; });
    }
  }).catch(() => {});

  document.getElementById('selectAllCheck').addEventListener('change', toggleSelectAll);
  document.getElementById('themeSegment').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-theme]');
    if (!b) return;
    setThemeMode(b.dataset.theme);
  });
  document.getElementById('hideHintsToggle').addEventListener('change', (e) => setHideHints(e.target.checked));

  const si = document.getElementById('searchInput');
  const sc = document.getElementById('searchClear');
  si.addEventListener('input', () => {
    searchQuery = si.value.trim().toLowerCase();
    sc.classList.toggle('visible', !!searchQuery);
    applyFiltersAndRender();
  });

  document.getElementById('imageList').addEventListener('scroll', onListScroll, { passive: true });
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
    importModal: () => { if (document.getElementById('importCloseBtn').style.display !== 'none') closeImportModal(); },
    tagCreateModal: () => closeTagCreate(),
    shortcutsModal: () => closeShortcuts(),
    versionsModal: () => closeVersions(),
    logsModal: () => closeLogs(),
  };
  Object.entries(closeHandlers).forEach(([id, fn]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('mousedown', (e) => { if (e.target.id === id) fn(); });
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
  });

  loadProjects();
  subscribeBootstrapEvents();
  api('/api/train/status').then(s => { if (s.status === 'running' || s.status === 'stopping') subscribeTrainEvents(); }).catch(() => {});
  api('/api/autolabel/batch/status').then(s => { if (s.status === 'running') { batchRunning = true; subscribeBatchEvents(); } }).catch(() => {});
  setTimeout(checkModelsAvailability, 1500);
});