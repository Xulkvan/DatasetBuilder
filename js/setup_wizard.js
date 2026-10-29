// [STAGE2:setup-wizard-js] First-run admin wizard (auto-shown when needs_setup).
import { setupAdmin } from './auth.js';

export function openSetupWizard() {
  let m = document.getElementById('setupWizardModal');
  if (!m) {
    m = document.createElement('div');
    m.id = 'setupWizardModal';
    m.className = 'modal-backdrop';
    m.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" style="max-width: 480px;">
        <h2 style="margin-top:0;">Первичная настройка</h2>
        <p style="color:var(--text-secondary);font-size:0.875rem;margin:0 0 12px;">
          В системе ещё нет пользователей. Создайте аккаунт Администратора,
          чтобы начать работу.
        </p>
        <div style="display:flex;flex-direction:column;gap:8px;">
          <input type="text" id="setupUsername" class="modal-input"
                 placeholder="Логин (мин. 3 символа)" autocomplete="username">
          <input type="password" id="setupPassword" class="modal-input"
                 placeholder="Пароль (мин. 8 символов)" autocomplete="new-password">
          <input type="password" id="setupPassword2" class="modal-input"
                 placeholder="Пароль ещё раз" autocomplete="new-password">
        </div>
        <div id="setupError"
             style="color:var(--danger);font-size:0.8125rem;display:none;margin-top:8px;"></div>
        <div class="modal-actions" style="justify-content:flex-end;">
          <button class="btn btn-primary" id="setupSubmitBtn">Создать администратора</button>
        </div>
      </div>
    `;
    document.body.appendChild(m);
  }
  m.style.display = 'flex';
  m.classList.add('open');
  m.style.zIndex = '99999';
  m.style.opacity = '1';

  const submit = async () => {
    const u = document.getElementById('setupUsername').value.trim();
    const p = document.getElementById('setupPassword').value;
    const p2 = document.getElementById('setupPassword2').value;
    const err = document.getElementById('setupError');
    err.style.display = 'none';
    if (u.length < 3) {
      err.textContent = 'Логин минимум 3 символа';
      err.style.display = 'block'; return;
    }
    if (p.length < 8) {
      err.textContent = 'Пароль минимум 8 символов';
      err.style.display = 'block'; return;
    }
    if (p !== p2) {
      err.textContent = 'Пароли не совпадают';
      err.style.display = 'block'; return;
    }
    const btn = document.getElementById('setupSubmitBtn');
    btn.disabled = true; btn.textContent = 'Создаём…';
    try {
      await setupAdmin(u, p);
      m.style.display = 'none';
      m.classList.remove('open');
      window.location.reload();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Создать администратора';
    }
  };
  document.getElementById('setupSubmitBtn').onclick = submit;
  ['setupUsername', 'setupPassword', 'setupPassword2'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.onkeydown = e => { if (e.key === 'Enter') submit(); };
  });
  setTimeout(() => {
    const el = document.getElementById('setupUsername');
    if (el) el.focus();
  }, 100);
}

window.openSetupWizard = openSetupWizard;
// [/STAGE2:setup-wizard-js]
