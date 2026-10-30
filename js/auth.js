// [STAGE2:auth-js] Cookie-based auth client for Team Edition.
export const AUTH_STATE = { mode: null, user: null, loaded: false, needsSetup: false, permissions: [] };  // [STAGE6:permissions-matrix]

export async function loadAuthStatus() {
  const r = await fetch('/api/auth/status', { credentials: 'same-origin' });
  if (!r.ok) throw new Error('auth status failed');
  const s = await r.json();
  AUTH_STATE.mode = s.mode;
  AUTH_STATE.user = s.user;
  AUTH_STATE.needsSetup = !!s.needs_setup;
  AUTH_STATE.permissions = Array.isArray(s.permissions) ? s.permissions : [];  // [STAGE6:permissions-matrix]
  AUTH_STATE.loaded = true;
  try { window.dispatchEvent(new CustomEvent('pdb-auth-loaded')); } catch (e) {}
  return AUTH_STATE;
}

function _errMsg(data, fallback) {
  const d = data && data.detail;
  if (typeof d === 'string' && d) return d;
  if (d && typeof d === 'object') return d.fallback || d.key || fallback;
  return fallback;
}

export async function login(username, password) {
  const r = await fetch('/api/auth/login', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json',
               'X-Requested-With': 'DatasetBuilder' },
    body: JSON.stringify({ username, password }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(_errMsg(data, 'Login failed'));
  AUTH_STATE.user = data.user;
  AUTH_STATE.mode = 'team';
  AUTH_STATE.permissions = Array.isArray(data.permissions) ? data.permissions : [];  // [STAGE6:permissions-matrix]
  AUTH_STATE.loaded = true;
  return data.user;
}

export async function logout() {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-Requested-With': 'DatasetBuilder' },
    });
  } catch (e) {}
  AUTH_STATE.user = null;
  try {
    localStorage.removeItem('pdb_user');
    localStorage.removeItem('pdb_token');
  } catch (e) {}
}

export async function changePassword(oldPw, newPw) {
  const r = await fetch('/api/auth/change_password', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json',
               'X-Requested-With': 'DatasetBuilder' },
    body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(_errMsg(data, 'Password change failed'));
  return true;
}

export async function setupAdmin(username, password) {
  const r = await fetch('/api/setup/admin', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json',
               'X-Requested-With': 'DatasetBuilder' },
    body: JSON.stringify({ username, password }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(_errMsg(data, 'Setup failed'));
  AUTH_STATE.user = data.user;
  AUTH_STATE.mode = 'team';
  AUTH_STATE.needsSetup = false;
  AUTH_STATE.permissions = Array.isArray(data.permissions) ? data.permissions : [];  // [STAGE6:permissions-matrix]
  AUTH_STATE.loaded = true;
  return data.user;
}

export function isLocalMode() { return AUTH_STATE.mode === 'local'; }
export function isTeamMode() { return AUTH_STATE.mode === 'team'; }
export function currentUser() { return AUTH_STATE.user; }

window.AUTH_STATE = AUTH_STATE;
window.authLogin = login;
window.authLogout = logout;
window.authChangePassword = changePassword;
window.authSetupAdmin = setupAdmin;
window.authLoadStatus = loadAuthStatus;
// [/STAGE2:auth-js]
