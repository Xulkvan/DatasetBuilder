// @ts-check

/**
 * @typedef {import('./types.js').BoxData} BoxData
 * @typedef {import('./types.js').AppState} AppState
 */

// V11.8.0: Extracted Canvas & Pointer logic
import { haptic } from './utils.js';
import { hideTooltip } from './ui.js';

const ZOOM_MIN = 0.5, ZOOM_MAX = 8;
const viewport = document.getElementById('canvasViewport');
let preDragSnapshot = null;
const _activePointers = new Map();
let _pinchStart = null;
let _drawDotEl = null;
let _drawDotTimer = null;

export function getRel(e) {
  const vp = viewport.getBoundingClientRect();
  const vx = e.clientX - vp.left, vy = e.clientY - vp.top;
  return {
    x: Math.min(Math.max(((vx - window.AppState.panX) / window.AppState.zoom) / 640, 0), 1),
    y: Math.min(Math.max(((vy - window.AppState.panY) / window.AppState.zoom) / 640, 0), 1)
  };
}

export function clampBox(b) {
  let w = Math.min(Math.max(b.w, 0.005), 1);
  let h = Math.min(Math.max(b.h, 0.005), 1);
  let x = Math.max(0, Math.min(1 - w, b.x));
  let y = Math.max(0, Math.min(1 - h, b.y));
  return {
    x, y, w, h,
    label: b.label || window.currentObjectClass(),
    confidence: (b.confidence ?? null),
    frozen: !!b.frozen,
    behavior: b.behavior || null,
    animal_id: (b.animal_id != null) ? b.animal_id : null,
    keypoints: Array.isArray(b.keypoints) ? b.keypoints : [],
  };
}

export function applyTransform() {
  const stage = document.getElementById('canvasStage');
  stage.style.transform = `translate(${window.AppState.panX}px, ${window.AppState.panY}px) scale(${window.AppState.zoom})`;
  stage.style.setProperty('--inv-zoom', (1 / window.AppState.zoom).toFixed(4));
  const badge = document.getElementById('zoomBadge');
  badge.textContent = Math.round(window.AppState.zoom * 100) + '%';
  badge.setAttribute('aria-label', `Масштаб ${Math.round(window.AppState.zoom * 100)}%`);
  _updateCanvasCursor();
}

function _updateCanvasCursor() {
  const vp = document.getElementById('canvasViewport');
  if (!vp) return;
  if (window.AppState.zoom > 1) vp.classList.add('can-pan');
  else vp.classList.remove('can-pan');
}

export function clampPan() {
  const vpSize = 640, stageSize = 640 * window.AppState.zoom;
  if (stageSize <= vpSize) {
    window.AppState.panX = (vpSize - stageSize) / 2;
    window.AppState.panY = (vpSize - stageSize) / 2;
  } else {
    window.AppState.panX = Math.min(0, Math.max(vpSize - stageSize, window.AppState.panX));
    window.AppState.panY = Math.min(0, Math.max(vpSize - stageSize, window.AppState.panY));
  }
}

export function zoomAt(vx, vy, factor) {
  const nz = Math.min(Math.max(window.AppState.zoom * factor, ZOOM_MIN), ZOOM_MAX);
  if (nz === window.AppState.zoom) return;
  const k = nz / window.AppState.zoom;
  window.AppState.panX = vx - (vx - window.AppState.panX) * k;
  window.AppState.panY = vy - (vy - window.AppState.panY) * k;
  window.AppState.zoom = nz; clampPan(); applyTransform();
}

export function zoomToCenter(f) { zoomAt(320, 320, f); }
export function zoomReset() { window.AppState.zoom = 1; window.AppState.panX = 0; window.AppState.panY = 0; clampPan(); applyTransform(); }
export function zoomFit() { zoomReset(); }

export function zoomToSelection() {
  const indices = window.getSelectedIndices();
  if (!indices.length) { zoomReset(); window.setStatus(window.t('toast.nothingToZoom')); return; }
  let x1 = 1, y1 = 1, x2 = 0, y2 = 0;
  indices.forEach(i => {
    const b = window.AppState.boxes[i];
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
  window.AppState.zoom = newZoom;
  window.AppState.panX = 320 - cx * window.AppState.zoom;
  window.AppState.panY = 320 - cy * window.AppState.zoom;
  clampPan();
  applyTransform();
  haptic('selection');
}

function flashDrawDot(x, y) {
  if (window.prefersReducedMotion()) return;
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
  window.AppState.panX = mx - (mxs - _pinchStart.panX) * k;
  window.AppState.panY = my - (mys - _pinchStart.panY) * k;
  window.AppState.zoom = targetZoom;
  clampPan(); applyTransform();
}

export function installCanvasListeners() {
  // V11.8.3: dblclick listener (через elementFromPoint, т.к. pointer capture)
  viewport.addEventListener('dblclick', (e) => {
    if (!window.skeletonMode) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const dot = el && el.closest ? el.closest('.skeleton-point') : null;
    if (!dot) return;
    e.preventDefault();
    e.stopPropagation();
    const i = parseInt(dot.dataset.kpIdx, 10);
    if (!isNaN(i) && typeof window._toggleKeypointVisibility === 'function') {
      window._toggleKeypointVisibility(i);
    }
  });

  viewport.addEventListener('pointerdown', e => {
    if (!window.currentImageId) return;
    if (e.target.closest && e.target.closest('.zoom-controls')) return;
    if (e.target.closest && e.target.closest('.zoom-badge')) return;
    if (e.pointerType === 'mouse' && e.button !== 0 && e.button !== 1) return;
    e.preventDefault();
    _activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (_activePointers.size === 2) {
      if (window.dragState) { window.dragState = null; const dp = document.getElementById('drawPreview'); if (dp) dp.remove(); }
      if (window.isPanning) { window.isPanning = false; viewport.classList.remove('panning'); }
      const mid = _midTwoPointers();
      _pinchStart = { distance: _distTwoPointers(), midClientX: mid.x, midClientY: mid.y, zoom: window.AppState.zoom, panX: window.AppState.panX, panY: window.AppState.panY };
      return;
    }
    if (_activePointers.size > 2) return;

    const t = e.target;
    const isDelete = t.classList && t.classList.contains('box-delete');
    if (isDelete) return;

    if (window.samMode) {
      const p = getRel(e);
      window._samClickAt(p.x, p.y);
      return;
    }

    if (window.skeletonMode) {
      const _skelEmpty = !t.closest || !t.closest('.box');
      const _wantPan = window.spacePressed || e.button === 1
                       || (window.AppState.zoom > 1 && _skelEmpty && !e.shiftKey
                           && !(t.classList && t.classList.contains('skeleton-point')));
      if (_wantPan) {
        window.isPanning = true;
        window.panStart = { x: e.clientX - window.AppState.panX, y: e.clientY - window.AppState.panY };
        viewport.classList.add('panning');
        try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
        return;
      }
      const _isKp = t.classList && t.classList.contains('skeleton-point');
      if (_isKp) {
        window.keypointDragIdx = parseInt(t.dataset.kpIdx, 10);
        try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
        return;
      }
      const _boxEl = t.closest ? t.closest('.box') : null;
      const _hasSel = window._targetAnnotationId() >= 0;
      if (_boxEl) {
        const _bi = +_boxEl.dataset.idx;
        if (window.State.selectedIndex !== _bi) {
          window.State.selectedIndex = _bi;
          window.State.multiSelected.clear();
          window.updateSelectionClasses();
          return;
        }
        // Если рамка уже выделена, не ставим точку, а позволяем её двигать
        // [FIX] Если рамка уже выделена, позволяем её двигать/ресайзить, проваливаясь ниже
      } else if (e.button === 0) {
        if (!_hasSel) {
          window.setStatus(window.t('skeleton.status.selectFirst'), 2000);
          haptic('warning');
          return;
        }
        const p = getRel(e);
        window._placeNextKeypoint(p.x, p.y, e.shiftKey ? 0.0 : 1.0);
        return;
      }
    }

    const isHandle = t.classList && t.classList.contains('handle') && !!t.dataset.handle;
    const isEdge = t.classList && t.classList.contains('box-edge');
    const boxEl = t.closest ? t.closest('.box') : null;
    const isEmpty = !boxEl;

    // V13.3.2: Клик ВНУТРЬ рамки (не по краю/ручке) — выделяет и двигает её
    if (boxEl && !isHandle && !isEdge && !(t.classList && t.classList.contains('box-delete'))) {
      const idx = +boxEl.dataset.idx;
      if (e.shiftKey) {
        if (typeof window.toggleMultiSelect === 'function') window.toggleMultiSelect(idx);
      } else {
        window.State.selectedIndex = idx;
        window.State.multiSelected.clear();
      }
      if (window.AppState.boxes[idx].frozen) {
        window.updateSelectionClasses();
        return;
      }
      const p = getRel(e);
      const o = window.AppState.boxes[idx];
      window.dragState = {
        mode: 'move', idx, startX: p.x, startY: p.y,
        orig: { x: o.x, y: o.y, w: o.w, h: o.h },
        moveAll: window.State.multiSelected.size > 0
      };
      try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
      window.updateSelectionClasses();
      return;
    }

    const shouldPan = window.spacePressed || e.button === 1 || (window.AppState.zoom > 1 && isEmpty && !e.shiftKey);
    // V11.10.19: deselect on pan — при zoom>1 клик по пустому месту (не space, не middle, не shift)
    // снимает выделение до старта pan. Иначе оно «залипает» на увеличенном холсте.
    if (shouldPan && !window.spacePressed && e.button !== 1 && !e.shiftKey && isEmpty) {
      try {
        if (typeof window.clearSelection === 'function') window.clearSelection();
      } catch (_e) {}
    }
    if (shouldPan) {
      window.isPanning = true;
      window.panStart = { x: e.clientX - window.AppState.panX, y: e.clientY - window.AppState.panY };
      viewport.classList.add('panning');
      try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
      return;
    }
    preDragSnapshot = window.snapshot();
    if (isHandle && boxEl) {
      const idx = +boxEl.dataset.idx;
      if (window.AppState.boxes[idx].frozen) return;
      if (e.shiftKey) { if (typeof window.toggleMultiSelect === 'function') window.toggleMultiSelect(idx); }
      else { window.State.selectedIndex = idx; window.State.multiSelected.clear(); }
      const p = getRel(e);
      const o = window.AppState.boxes[idx];
      window.dragState = { mode: 'resize', handle: t.dataset.handle, idx, startX: p.x, startY: p.y, orig: { x: o.x, y: o.y, w: o.w, h: o.h } };
      try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
      window.updateSelectionClasses();
      return;
    }
    if (isEdge && boxEl) {
      const idx = +boxEl.dataset.idx;
      if (e.shiftKey) { if (typeof window.toggleMultiSelect === 'function') window.toggleMultiSelect(idx); }
      else { window.State.selectedIndex = idx; window.State.multiSelected.clear(); }  // V11.10.16: use State, not bare window prop
      if (window.AppState.boxes[idx].frozen) { window.updateSelectionClasses(); return; }
      const p = getRel(e);
      const o = window.AppState.boxes[idx];
      window.dragState = { mode: 'move', idx, startX: p.x, startY: p.y, orig: { x: o.x, y: o.y, w: o.w, h: o.h }, moveAll: window.State.multiSelected.size > 0 };
      try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
      window.updateSelectionClasses();
      return;
    }
    // V11.10.16: bulletproof deselect
    try {
      if (typeof window.clearSelection === 'function') {
        window.clearSelection();
      } else {
        if (window.State) {
          window.State.selectedIndex = -1;
          if (window.State.multiSelected) window.State.multiSelected.clear();
        }
        if (typeof window.updateSelectionClasses === 'function') {
          window.updateSelectionClasses();
        }
      }
    } catch (_e) {
      console.warn('[deselect] clearSelection threw:', _e);
    }
    // Прямая очистка DOM — гарантирует визуальный деселект даже если
    // updateSelectionClasses не отработал (например, из-за ошибки в _refreshAttrBar).
    document.querySelectorAll('#boxes .box').forEach(el => {
      el.classList.remove('selected', 'multi-selected');
    });
    try {
      const _ae = document.activeElement;
      if (_ae && _ae.classList && _ae.classList.contains('box')) _ae.blur();
    } catch (_e) {}
    const p = getRel(e);
    window.dragState = { mode: 'draw', startX: p.x, startY: p.y };
    const prev = document.createElement('div');
    prev.id = 'drawPreview';
    prev.className = 'box preview';
    prev.setAttribute('aria-hidden', 'true');
    document.getElementById('boxes').appendChild(prev);
    window.dragState.previewEl = prev;
    flashDrawDot(p.x, p.y);
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
  });

  // V11.9.0: rAF Throttling для плавного рендеринга (120Hz)
  let _rafPending = false;
  let _lastMoveEvent = null;

  function _processMove(e) {
    _rafPending = false;
    if (!e) return;
    const p = getRel(e);

    if (window.keypointDragIdx >= 0 && window.keypointDragIdx < window.keypoints.length) {
      window.keypoints[window.keypointDragIdx].x = p.x;
      window.keypoints[window.keypointDragIdx].y = p.y;
      window._syncKeypointsToBox();
      window.renderSkeleton();
      return;
    }
    if (!window.dragState) return;

    if (window.dragState.mode === 'move') {
      const o = window.dragState.orig;
      const dx = p.x - window.dragState.startX, dy = p.y - window.dragState.startY;
      if (window.dragState.moveAll) {
        const indices = window.getSelectedIndices().filter(i => !window.AppState.boxes[i].frozen);
        const snap = preDragSnapshot;
        indices.forEach(i => {
          const so = snap[i];
          window.AppState.boxes[i] = clampBox({
            x: so.x + dx, y: so.y + dy, w: so.w, h: so.h,
            label: so.label, confidence: so.confidence, frozen: so.frozen,
            behavior: so.behavior || null, animal_id: (so.animal_id != null) ? so.animal_id : null,
            keypoints: so.keypoints,
          });
          window.updateBoxInPlace(i);
        });
      } else {
        const b = window.AppState.boxes[window.dragState.idx];
        window.AppState.boxes[window.dragState.idx] = clampBox({
          x: o.x + dx, y: o.y + dy, w: o.w, h: o.h,
          label: b.label, confidence: b.confidence, frozen: b.frozen,
          behavior: b.behavior || null, animal_id: (b.animal_id != null) ? b.animal_id : null,
          keypoints: b.keypoints,
        });
        window.updateBoxInPlace(window.dragState.idx);
      }
      return;
    }
    if (window.dragState.mode === 'resize') {
      const o = window.dragState.orig;
      const dx = p.x - window.dragState.startX, dy = p.y - window.dragState.startY;
      let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
      const h = window.dragState.handle;
      if (h.includes('w')) x1 = o.x + dx;
      if (h.includes('e')) x2 = o.x + o.w + dx;
      if (h.includes('n')) y1 = o.y + dy;
      if (h.includes('s')) y2 = o.y + o.h + dy;
      if (x1 > x2) { const t = x1; x1 = x2; x2 = t; }
      if (y1 > y2) { const t = y1; y1 = y2; y2 = t; }
      x1 = Math.max(0, x1); y1 = Math.max(0, y1);
      x2 = Math.min(1, x2); y2 = Math.min(1, y2);
      const b = window.AppState.boxes[window.dragState.idx];
      window.AppState.boxes[window.dragState.idx] = {
        x: x1, y: y1, w: Math.max(0, x2 - x1), h: Math.max(0, y2 - y1),
        label: b.label, confidence: b.confidence, frozen: b.frozen,
        behavior: b.behavior || null, animal_id: (b.animal_id != null) ? b.animal_id : null,
        keypoints: Array.isArray(b.keypoints) ? b.keypoints : [],
      };
      window.updateBoxInPlace(window.dragState.idx);
      return;
    }
    if (window.dragState.mode === 'draw') {
      const prev = window.dragState.previewEl;
      if (!prev) return;
      const x = Math.min(window.dragState.startX, p.x);
      const y = Math.min(window.dragState.startY, p.y);
      const w = Math.abs(p.x - window.dragState.startX);
      const h = Math.abs(p.y - window.dragState.startY);
      prev.style.transform = `translate(${x * 640}px, ${y * 640}px)`;
      prev.style.width = (w * 640) + 'px';
      prev.style.height = (h * 640) + 'px';
    }
  }

  window.addEventListener('pointermove', e => {
    if (_activePointers.has(e.pointerId)) _activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    // Синхронные операции (без задержек)
    if (_pinchStart && _activePointers.size >= 2) { e.preventDefault(); _handlePinch(); return; }
    if (window.isPanning) {
      window.AppState.panX = e.clientX - window.panStart.x;
      window.AppState.panY = e.clientY - window.panStart.y;
      clampPan(); applyTransform();
      return;
    }

    // Асинхронные операции (перетаскивание) — через rAF
    if (window.dragState || (window.keypointDragIdx >= 0)) {
      if (e.cancelable) e.preventDefault(); // предотвращаем выделение текста
      _lastMoveEvent = e;
      if (!_rafPending) {
        _rafPending = true;
        requestAnimationFrame(() => _processMove(_lastMoveEvent));
      }
    }
  }, { passive: false });

  function _endPointer(e) {
    if (window.keypointDragIdx >= 0) {
      window.keypointDragIdx = -1;
      window.pushHistory();
      window.markDirty();
      haptic('selection');
    }
    _activePointers.delete(e.pointerId);
    if (_activePointers.size < 2) _pinchStart = null;
    if (window.isPanning) { window.isPanning = false; viewport.classList.remove('panning'); return; }
    if (!window.dragState) return;
    let changed = false;
    let settlingIdx = -1;
    if (window.dragState.mode === 'draw') {
      if (window.dragState.previewEl) { window.dragState.previewEl.remove(); window.dragState.previewEl = null; }
      const p = getRel(e);
      const x = Math.min(window.dragState.startX, p.x);
      const y = Math.min(window.dragState.startY, p.y);
      const w = Math.abs(p.x - window.dragState.startX);
      const h = Math.abs(p.y - window.dragState.startY);
      if (w > 0.01 && h > 0.01) {
        window.AppState.boxes.push({ x, y, w, h, label: window.currentObjectClass(), confidence: null, frozen: false, behavior: null, animal_id: null, keypoints: [] });
        window.State.selectedIndex = window.AppState.boxes.length - 1;
        window.State.multiSelected.clear();
        changed = true;
        settlingIdx = window.AppState.boxes.length - 1;
        const layer = document.getElementById('boxes');
        const newBoxEl = window._createBoxElement(window.AppState.boxes[settlingIdx], settlingIdx);
        if (!window.prefersReducedMotion()) {
          newBoxEl.classList.add('settling', 'box-enter');
          setTimeout(() => newBoxEl.classList.remove('settling', 'box-enter'), 400);
        }
        layer.appendChild(newBoxEl);
        window.updateSelectionClasses(); window.updateDelBoxBtn(); window.updateFreezeBtn();
      }
    } else if (window.dragState.mode === 'move' || window.dragState.mode === 'resize') {
      if (preDragSnapshot && JSON.stringify(preDragSnapshot) !== JSON.stringify(window.AppState.boxes)) {
        changed = true;
        if (window.dragState.mode === 'move' && window.dragState.moveAll) {
          window.getSelectedIndices().forEach(i => { if (window.AppState.boxes[i] && !window.AppState.boxes[i].frozen) { window.AppState.boxes[i].confidence = null; window.updateBoxInPlace(i); } });
        } else if (window.AppState.boxes[window.dragState.idx]) {
          window.AppState.boxes[window.dragState.idx].confidence = null;
          window.updateBoxInPlace(window.dragState.idx);
        }
      }
    }
    window.dragState = null;
    preDragSnapshot = null;
    if (changed) { window.pushHistory(); window.markDirty(); }
  }

  window.addEventListener('pointerup', _endPointer);
  window.addEventListener('pointercancel', _endPointer);

  viewport.addEventListener('wheel', (e) => {
    if (!window.currentImageId) return;
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const vp = viewport.getBoundingClientRect();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    zoomAt(e.clientX - vp.left, e.clientY - vp.top, factor);
  }, { passive: false });

  // V11.8.4: RMB-логика скелета — по ЯВНОЙ ГЕОМЕТРИИ, а не elementFromPoint.
  // elementFromPoint мог ложно возвращать .skeleton-point, если курсор
  // попадал в CSS-рамку точки (12×12 px) — из-за этого удалялась не та
  // точка, по которой визуально кликнули (например, холка вместо носа).
  viewport.addEventListener('contextmenu', (e) => {
    if (!window.skeletonMode || !window.currentImageId) return;
    e.preventDefault();

    const kps = Array.isArray(window.keypoints) ? window.keypoints : [];
    const vp = viewport.getBoundingClientRect();
    const vx = e.clientX - vp.left;
    const vy = e.clientY - vp.top;
    const zoom = window.AppState.zoom || 1;

    // Координаты клика в системе 640x640 (без учёта zoom/pan).
    const px = (vx - window.AppState.panX) / zoom;
    const py = (vy - window.AppState.panY) / zoom;

    // Порог 12px на экране; на увеличенном фото попасть проще.
    const threshold640 = 12 / zoom;

    let bestIdx = -1;
    let bestDist = threshold640;
    for (let i = 0; i < kps.length; i++) {
      const dx = kps[i].x * 640 - px;
      const dy = kps[i].y * 640 - py;
      const dist = Math.hypot(dx, dy);
      if (dist < bestDist) {
        bestDist = dist;
        bestIdx = i;
      }
    }

    if (bestIdx >= 0 && typeof window._removeKeypoint === 'function') {
      window._removeKeypoint(bestIdx);
    } else if (typeof window._removeLastKeypoint === 'function') {
      window._removeLastKeypoint();
    }
  });
}
