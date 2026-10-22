// @ts-check
// V11.5.0: Extracted Utilities
export function haptic(type = 'light') {
  if (!('vibrate' in navigator)) return;
  try {
    const ua = navigator.userActivation;
    if (ua && typeof ua.hasBeenActive === 'boolean' && !ua.hasBeenActive) return;
  } catch (e) {}
  const patterns = {
    light: [8], medium: [15], selection: [5],
    success: [10, 40, 12], error: [22, 60, 22, 60, 22], warning: [15, 40, 15],
  };
  try { navigator.vibrate(patterns[type] || patterns.light); } catch (e) {}
}

// ============================================================================
// V11.12.0: Вынесено из main.js для очистки кода
// ============================================================================

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;',
    '"': '&quot;', "'": '&#39;'
  }[c]));
}

export function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if ([2, 3, 4].includes(m10) && ![12, 13, 14].includes(m100)) return few;
  return many;
}

export function pluralImages(n) {
  if (typeof window.getLang === 'function' && window.getLang() === 'en') return n === 1 ? 'image' : 'images';
  return plural(n, 'изображение', 'изображения', 'изображений');
}

export function pluralProjects(n) {
  if (typeof window.getLang === 'function' && window.getLang() === 'en') return n === 1 ? 'project' : 'projects';
  return plural(n, 'проект', 'проекта', 'проектов');
}

export function pluralGroups(n) {
  if (typeof window.getLang === 'function' && window.getLang() === 'en') return n === 1 ? 'group' : 'groups';
  return plural(n, 'группа', 'группы', 'групп');
}

export function onActivate(el, handler, opts = {}) {
  el.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    if (opts.stop) e.stopPropagation();
    handler(e);
  });
}

export function getExt(f) { const i = f.lastIndexOf('.'); return i >= 0 ? f.slice(i + 1).toLowerCase() : ''; }
export function getStem(f) { const i = f.lastIndexOf('.'); return i >= 0 ? f.slice(0, i) : f; }

export function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

export function _fmtBytes(n) {
  if (!n || n < 1024) return (n || 0) + ' Б';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' КБ';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' МБ';
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' ГБ';
}

export function animateNumber(el, newText) {
  if (!el || el.textContent === newText) return;
  el.style.transform = 'translateY(-4px)';
  el.style.opacity = '0.4';
  setTimeout(() => {
    el.textContent = newText;
    el.style.transform = 'translateY(0)';
    el.style.opacity = '1';
  }, 100);
}
