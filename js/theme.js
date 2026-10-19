// @ts-check
// V11.7.0: Extracted Theme & Focus Mode logic
import { haptic } from './utils.js';

export function getThemeMode() { try { return localStorage.getItem('pdb_theme') || 'auto'; } catch (e) { return 'auto'; } }
export function applyTheme() {
  const mode = getThemeMode();
  let eff = mode;
  if (mode === 'auto') eff = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', eff);
  document.documentElement.setAttribute('data-theme-mode', mode);
  updateThemeSegment();
}
export function setThemeMode(mode) {
  if (!['auto', 'light', 'dark'].includes(mode)) mode = 'auto';
  try { localStorage.setItem('pdb_theme', mode); } catch (e) {}
  applyTheme(); haptic('selection');
}
export function updateThemeSegment() {
  const seg = document.getElementById('themeSegment');
  if (!seg) return;
  const cur = getThemeMode();
  seg.querySelectorAll('button').forEach(b => {
    const isActive = b.dataset.mode === cur;
    b.classList.toggle('active', isActive);
    b.setAttribute('aria-checked', isActive ? 'true' : 'false');
    b.setAttribute('tabindex', isActive ? '0' : '-1');
  });
}
try {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (getThemeMode() === 'auto') applyTheme();
  });
} catch (e) {}

export function getHideHints() { try { return localStorage.getItem('pdb_hide_hints') === '1'; } catch (e) { return false; } }
export function setHideHints(v) {
  try { localStorage.setItem('pdb_hide_hints', v ? '1' : '0'); } catch (e) {}
  document.documentElement.setAttribute('data-hide-hints', v ? '1' : '0');
  const cb = document.getElementById('hideHintsToggle');
  if (cb) cb.checked = v;
}

export function getFocusMode() { try { return localStorage.getItem('pdb_focus_mode') === '1'; } catch (e) { return false; } }
export function setFocusMode(v) {
  try { localStorage.setItem('pdb_focus_mode', v ? '1' : '0'); } catch (e) {}
  applyFocusMode();
  haptic('selection');
}
export function toggleFocusMode() { setFocusMode(!getFocusMode()); }
export function applyFocusMode() {
  const on = getFocusMode();
  document.documentElement.setAttribute('data-focus-mode', on ? '1' : '0');
  const btn = document.getElementById('focusModeBtn');
  if (btn) {
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    const tt = on ? 'Выйти из focus-режима (⌘\\)' : 'Focus-режим (⌘\\)';
    btn.setAttribute('aria-label', tt);
    btn.dataset.tooltip = tt;
  }
}
