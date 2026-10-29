// [STAGE2:permissions-js] Role-based UI helpers.
const ROLE_PERMISSIONS = {
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
  return (ROLE_PERMISSIONS[u.role] || new Set()).has(perm);
}

export function applyPermissionsToDOM() {
  document.querySelectorAll('[data-requires]').forEach(el => {
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
