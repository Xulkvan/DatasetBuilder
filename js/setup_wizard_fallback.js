// [PATCH:FIX-setup-script]
// [PATCH:FIX-setup-script] Первичный Setup Wizard (fallback).
// Показывается, если /api/setup/status вернул needs_setup=true,
// а существующий setup_wizard.js (этапы 1-5) не сработал.

window.openSetupWizard = function () {
  const modal = document.getElementById('setupWizardModal');
  if (!modal) { alert('setupWizardModal не найден — перезагрузите страницу (Ctrl+F5)'); return; }
  window.openModal('setupWizardModal');
  setTimeout(() => {
    const inp = document.getElementById('setupUsername');
    if (inp) try { inp.focus(); } catch (e) {}
  }, 120);
};

(function () {
  function _bind() {
    const btn = document.getElementById('setupSubmitBtn');
    if (!btn || btn.__bound) return;
    btn.__bound = true;
    btn.addEventListener('click', async () => {
      const err = document.getElementById('setupError');
      err.style.display = 'none';

      const u = (document.getElementById('setupUsername').value || '').trim();
      const p1 = document.getElementById('setupPassword').value || '';
      const p2 = document.getElementById('setupPassword2').value || '';

      if (u.length < 3) { err.textContent = 'Логин ≥ 3 символов'; err.style.display = 'block'; return; }
      if (p1.length < 8) { err.textContent = 'Пароль ≥ 8 символов'; err.style.display = 'block'; return; }
      if (p1 !== p2) { err.textContent = 'Пароли не совпадают'; err.style.display = 'block'; return; }

      btn.disabled = true;
      try {
        let r = await fetch('/api/setup/bootstrap_admin', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json',
                     'X-Requested-With': 'DatasetBuilder' },
          body: JSON.stringify({ username: u, password: p1 }),
        });
        if (r.status === 404) {
          // Fallback на существующий /api/setup/admin (Form)
          const fd = new FormData();
          fd.append('username', u);
          fd.append('password', p1);
          r = await fetch('/api/setup/admin', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'DatasetBuilder' },
            body: fd,
          });
        }
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          const msg = (d.detail && (d.detail.fallback || d.detail)) || ('HTTP ' + r.status);
          throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
        window.location.reload();
      } catch (e) {
        err.textContent = String(e.message || e).slice(0, 200);
        err.style.display = 'block';
      } finally {
        btn.disabled = false;
      }
    });
  }
  document.addEventListener('DOMContentLoaded', _bind);
  if (document.readyState !== 'loading') _bind();
})();
