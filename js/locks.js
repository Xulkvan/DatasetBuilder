// [STAGE5:locks-js] Per-image soft lock (advisory).
// Subscribes to State.currentImageId change, acquires lock, sends heartbeat,
// releases on switch. Shows overlay when image is busy.
import { api } from './api.js';
import { subscribe } from './store.js';

const HEARTBEAT_MS = 60000;
const OVERLAY_ID = 'imageLockOverlay';

let _currentLockedId = null;
let _heartbeatTimer = null;
let _acquireToken = 0;
let _overlayEl = null;

function _getOverlay() {
  if (_overlayEl && _overlayEl.parentNode) return _overlayEl;
  const host = document.getElementById('canvasViewport')
            || document.getElementById('canvasHost');
  if (!host) return null;
  const el = document.createElement('div');
  el.id = OVERLAY_ID;
  el.style.cssText = [
    'position:absolute', 'inset:0', 'z-index:50',
    'background:rgba(0,0,0,0.55)',
    'display:none', 'align-items:center', 'justify-content:center',
    'color:#fff', 'font-size:0.95rem', 'font-weight:600',
    'text-align:center', 'padding:24px', 'pointer-events:all',
    'backdrop-filter:blur(2px)',
  ].join(';');
  host.appendChild(el);
  _overlayEl = el;
  return el;
}

function _showOverlay(msg) {
  const el = _getOverlay();
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'flex';
  const vp = document.getElementById('canvasViewport');
  if (vp) vp.style.pointerEvents = 'none';
}

function _hideOverlay() {
  const el = _getOverlay();
  if (!el) return;
  el.style.display = 'none';
  const vp = document.getElementById('canvasViewport');
  if (vp) vp.style.pointerEvents = '';
}

async function _acquire(imageId) {
  if (!imageId) return null;
  try {
    const r = await api(`/api/images/${imageId}/lock`, { method: 'POST' });
    return r;
  } catch (e) {
    return { status: 'error', error: String(e.message || e) };
  }
}

async function _release(imageId) {
  if (!imageId) return;
  try {
    await api(`/api/images/${imageId}/lock`, { method: 'DELETE' });
  } catch (e) { /* ignore */ }
}

function _startHeartbeat(imageId) {
  _stopHeartbeat();
  _heartbeatTimer = setInterval(async () => {
    try { await api(`/api/images/${imageId}/lock/heartbeat`, { method: 'POST' }); }
    catch (e) { /* ignore */ }
  }, HEARTBEAT_MS);
}

function _stopHeartbeat() {
  if (_heartbeatTimer) { clearInterval(_heartbeatTimer); _heartbeatTimer = null; }
}

async function _onImageChange(newId) {
  // [PATCH:FIX-locks-local] соло-режим: не проверяем блокировку
  if (window.AUTH_STATE && window.AUTH_STATE.mode === 'local') {
    _hideOverlay();
    return;
  }
  const token = ++_acquireToken;

  if (_currentLockedId && _currentLockedId !== newId) {
    _stopHeartbeat();
    const oldId = _currentLockedId;
    _currentLockedId = null;
    _release(oldId);
  }
  if (!newId) { _hideOverlay(); return; }

  _showOverlay('Проверяю блокировку кадра…');
  const r = await _acquire(newId);
  if (token !== _acquireToken) return;  // stale

  if (!r) { _hideOverlay(); return; }

  if (r.status === 'acquired') {
    _currentLockedId = newId;
    _startHeartbeat(newId);
    _hideOverlay();
    return;
  }
  if (r.status === 'busy') {
    const who = r.holder && r.holder.username ? r.holder.username : 'другой пользователь';
    _showOverlay(`Кадр редактирует ${who}. Дождитесь освобождения.`);
    return;
  }
  // unknown/error — don't block
  _hideOverlay();
}

window._imageLockRelease = async function () {
  if (_currentLockedId) {
    const id = _currentLockedId;
    _currentLockedId = null;
    _stopHeartbeat();
    await _release(id);
  }
};

window._imageLockStatus = function () {
  return { lockedImageId: _currentLockedId };
};

subscribe((prop, val) => {
  if (prop !== 'currentImageId') return;
  _onImageChange(val).catch(err => {
    console.warn('[locks] onImageChange failed:', err);
    _hideOverlay();
  });
});

window.addEventListener('beforeunload', () => {
  if (_currentLockedId) {
    const id = _currentLockedId;
    // best-effort sync; browser may not wait for this
    navigator.sendBeacon
      ? fetch(`/api/images/${id}/lock`, {
          method: 'DELETE', credentials: 'same-origin',
          headers: { 'X-Requested-With': 'DatasetBuilder' },
          keepalive: true,
        }).catch(() => {})
      : null;
  }
});

document.addEventListener('DOMContentLoaded', () => {
  // If page opens with existing image (reload), acquire lock.
  setTimeout(() => {
    if (window.State && window.State.currentImageId) {
      _onImageChange(window.State.currentImageId).catch(() => {});
    }
  }, 900);
});
// [/STAGE5:locks-js]
