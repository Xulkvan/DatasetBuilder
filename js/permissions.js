// [STAGE2:permissions-js] Role-based UI helpers.
// [STAGE6:role-matrix-fallback] Локальная копия — fallback, если backend
// недоступен при bootstrap. Источник правды — /api/auth/status.permissions.
const _FALLBACK_ROLE_PERMISSIONS = {
  admin: new Set([
    'user.manage', 'project.delete_hard', 'project.manage',
    'dataset.export', 'model.manage', 'model.inference',
    'annotation.write', 'annotation.review', 'image.delete',
    'tag.manage', 'blur.manage', 'stream.manage', 'pipeline.run',
    'webhook.manage', 'audit.read', 'logs.read',
  ]),
  manager: new Set([
    'project.manage', 'dataset.export', 'model.manage',
    'model.inference', 'annotation.write', 'annotation.review',
    'image.delete', 'tag.manage', 'stream.manage', 'pipeline.run',
    'webhook.manage', 'logs.read',
  ]),
  annotator: new Set(['annotation.write', 'model.inference', 'tag.manage']),
  reviewer: new Set(['annotation.write', 'annotation.review',
                     'model.inference', 'logs.read']),
};

export function can(perm) {
  const st = window.AUTH_STATE || {};
  if (st.mode === 'local') return true;
  const u = st.user;
  if (!u) return false;
  if (u.username === 'local') return true;
  // [STAGE6:permissions-matrix] Основной источник — серверная матрица
  if (Array.isArray(st.permissions) && st.permissions.length > 0) {
    return st.permissions.indexOf(perm) !== -1;
  }
  // Fallback: bootstrap не отработал (offline / ранний вызов)
  return (_FALLBACK_ROLE_PERMISSIONS[u.role] || new Set()).has(perm);
}

export function applyPermissionsToDOM() {
  const st = window.AUTH_STATE || {};
  const isLocal = st.mode === 'local';
  document.querySelectorAll('[data-requires]').forEach(el => {
    if (isLocal && el.hasAttribute('data-hide-in-local')) {
      el.style.display = 'none';
      return;
    } // [PATCH:FIX_LOCAL_USERS_BTN]
    const need = (el.dataset.requires || '').split(',')
      .map(s => s.trim()).filter(Boolean);
    if (!need.length) return;
    const ok = need.every(can);
    el.style.display = ok ? '' : 'none';
    if (el.tagName === 'BUTTON') el.disabled = !ok;
  });
}

window.can = can;
window.applyPermissionsToDOM = applyPermissionsToDOM;

document.addEventListener('DOMContentLoaded', () => {
  setTimeout(async () => {
    try {
      if (!window.AUTH_STATE || !window.AUTH_STATE.loaded) {
        const mod = await import('./auth.js');
        await mod.loadAuthStatus();
      }
    } catch (e) {}
    applyPermissionsToDOM();
  }, 400);
  window.addEventListener('pdb-auth-loaded', () => applyPermissionsToDOM());
});
// [/STAGE2:permissions-js]

// [STAGE6:ROLE-MATRIX-RESOLVED] Матрица прав приходит с сервера
// через /api/auth/status.permissions. Локальный _FALLBACK_ROLE_PERMISSIONS
// оставлен только на случай недоступности backend при bootstrap.
