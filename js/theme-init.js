// V11.4.0: Вынесено из index.html для ужесточения CSP (нет 'unsafe-inline')
(function() {
  try {
    var mode = localStorage.getItem('pdb_theme') || 'auto';
    if (mode !== 'light' && mode !== 'dark' && mode !== 'auto') mode = 'auto';
    var eff = mode;
    if (mode === 'auto') eff = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', eff);
    document.documentElement.setAttribute('data-theme-mode', mode);
    var hints = localStorage.getItem('pdb_hide_hints') === '1';
    document.documentElement.setAttribute('data-hide-hints', hints ? '1' : '0');
    var focus = localStorage.getItem('pdb_focus_mode') === '1';
    if (focus) document.documentElement.setAttribute('data-focus-mode', '1');
  } catch(e) {}
})();
