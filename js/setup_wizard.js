// First-run admin wizard (auto-shown when needs_setup).
import { setupAdmin } from './auth.js';

export function openSetupWizard() {
  const el = document.getElementById('setupWizardModal');
  if (!el) {
    console.error('[setup_wizard] #setupWizardModal missing in DOM');
    return;
  }
  if (typeof window.openModal !== 'function') {
    console.error('[setup_wizard] window.openModal unavailable');
    return;
  }
  window.openModal('setupWizardModal');
  _wireSetupWizardHandlers();
}

function _wireSetupWizardHandlers() {
  const btn = document.getElementById('setupSubmitBtn');
  if (!btn || btn.__setupWired) return;
  btn.__setupWired = true;

  const submit = async () => {
    const u = document.getElementById('setupUsername').value.trim();
    const p = document.getElementById('setupPassword').value;
    const p2 = document.getElementById('setupPassword2').value;
    const err = document.getElementById('setupError');
    err.style.display = 'none';
    if (u.length < 3) {
      err.textContent = 'Логин минимум 3 символа';
      err.style.display = 'block';
      return;
    }
    if (p.length < 8) {
      err.textContent = 'Пароль минимум 8 символов';
      err.style.display = 'block';
      return;
    }
    if (p !== p2) {
      err.textContent = 'Пароли не совпадают';
      err.style.display = 'block';
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Создаём…';
    try {
      await setupAdmin(u, p);
      if (typeof window.closeModal === 'function') {
        window.closeModal('setupWizardModal');
      }
      window.location.reload();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.style.display = 'block';
      btn.disabled = false;
      btn.textContent = (typeof window.t === 'function')
        ? (window.t('setup.createAdmin') || 'Создать администратора')
        : 'Создать администратора';
    }
  };

  btn.onclick = submit;
  ['setupUsername', 'setupPassword', 'setupPassword2'].forEach((id) => {
    const inp = document.getElementById(id);
    if (inp) {
      inp.onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
      };
    }
  });
  setTimeout(() => {
    const u = document.getElementById('setupUsername');
    if (u) u.focus();
  }, 100);
}


window.openSetupWizard = openSetupWizard;
