// @ts-check

/**
 * @typedef {import('./types.js').BoxData} BoxData
 * @typedef {import('./types.js').ImageData} ImageData
 */

// V11.7.0: Extracted Command Palette
import { haptic } from './utils.js';
import { getFocusMode, toggleFocusMode, setThemeMode, getHideHints, setHideHints } from './theme.js';

let _paletteActiveIdx = 0;
let _paletteItems = [];

export const PALETTE_HISTORY_LIMIT = 5;
export let _paletteHistory = [];
try {
  const saved = JSON.parse(localStorage.getItem('pdb_palette_history') || '[]');
  if (Array.isArray(saved)) _paletteHistory = saved.slice(0, PALETTE_HISTORY_LIMIT);
} catch (e) {}
export function _pushPaletteHistory(id) {
  _paletteHistory = [id, ..._paletteHistory.filter(x => x !== id)].slice(0, PALETTE_HISTORY_LIMIT);
  try { localStorage.setItem('pdb_palette_history', JSON.stringify(_paletteHistory)); } catch (e) {}
}

export function _getCommands() {
  const cmds = [];
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || '');
  const CMD = isMac ? '⌘' : 'Ctrl+';
  const modBackslash = isMac ? '⌘\\' : 'Ctrl+\\';

  cmds.push({ id: 'focus-mode', category: window.t('cmd.cat.view'),
    title: getFocusMode() ? window.t('cmd.focus.exit') : window.t('cmd.focus.enter'),
    keywords: 'focus fullscreen sidebar hide ui', shortcut: modBackslash, action: toggleFocusMode });
  cmds.push({ id: 'theme-auto', category: window.t('cmd.cat.view'), title: window.t('cmd.theme.auto'),
    keywords: 'theme auto system', action: () => setThemeMode('auto') });
  cmds.push({ id: 'theme-light', category: window.t('cmd.cat.view'), title: window.t('cmd.theme.light'),
    keywords: 'theme light', action: () => setThemeMode('light') });
  cmds.push({ id: 'theme-dark', category: window.t('cmd.cat.view'), title: window.t('cmd.theme.dark'),
    keywords: 'theme dark night', action: () => setThemeMode('dark') });
  cmds.push({ id: 'hints', category: window.t('cmd.cat.view'),
    title: getHideHints() ? window.t('cmd.hints.show') : window.t('cmd.hints.hide'),
    keywords: 'hints tips toggle', action: () => setHideHints(!getHideHints()) });

  cmds.push({ id: 'proj-new', category: window.t('cmd.cat.projects'), title: window.t('cmd.proj.new'),
    keywords: 'new project create add', action: () => window.openProjectCreate() });
  (window._cachedProjectsList || []).forEach(p => {
    if (p.id === window.currentProjectId) return;
    cmds.push({
      id: 'proj-switch-' + p.id,
      category: window.t('cmd.cat.projects'),
      title: window.t('cmd.proj.open', { name: p.name }),
      keywords: 'switch open project ' + p.name + ' ' + (p.object_class || ''),
      action: () => {
        const el = document.querySelector(`#projects > div[data-project-id="${p.id}"]`);
        if (el) el.click();
      },
    });
  });
  if (window.currentProjectId) {
    cmds.push({ id: 'proj-settings', category: window.t('cmd.cat.projects'), title: window.t('cmd.proj.settings'),
      keywords: 'project settings class object', action: () => {
      const el = document.querySelector(`#projects > div[data-project-id="${window.currentProjectId}"]`);
      if (el) { const b = el.querySelector('.proj-settings'); if (b) b.click(); }
    }});
    cmds.push({ id: 'proj-backup', category: window.t('cmd.cat.projects'), title: window.t('cmd.proj.backup'),
      keywords: 'backup zip export save', action: () => window.doBackup() });
    cmds.push({ id: 'proj-delete', category: window.t('cmd.cat.projects'), title: window.t('cmd.proj.delete'),
      keywords: 'delete project remove trash', action: () => {
      if (!window.currentProjectMeta) return;
      window.confirmDeleteProject(window.currentProjectMeta.id, window.currentProjectMeta.name, window.currentProjectMeta.images_count || 0);
    }});
  }

  cmds.push({ id: 'filter-none', category: window.t('cmd.cat.filters'), title: window.t('cmd.filter.reset'),
    keywords: 'filter reset clear', action: () => {
    window.activeFilter = 'none'; window.activeTagIds.clear();
    try { localStorage.setItem('pdb_filter', 'none'); } catch (e) {}
    document.getElementById('filterUnannotated').checked = false;
    document.getElementById('filterLowConf').checked = false;
    document.getElementById('filterHard').checked = false;
    window.updateFilterBadge(); window.loadImages();
  }});
  cmds.push({ id: 'filter-un', category: window.t('cmd.cat.filters'), title: window.t('cmd.filter.un'),
    keywords: 'filter unannotated empty', action: () => {
    window.activeFilter = 'unannotated';
    document.getElementById('filterUnannotated').checked = true;
    document.getElementById('filterLowConf').checked = false;
    document.getElementById('filterHard').checked = false;
    try { localStorage.setItem('pdb_filter', 'unannotated'); } catch (e) {}
    window.updateFilterBadge(); window.loadImages();
  }});
  cmds.push({ id: 'filter-hard', category: window.t('cmd.cat.filters'), title: window.t('cmd.filter.hard'),
    keywords: 'filter hard flag', action: () => {
    window.activeFilter = 'hard';
    document.getElementById('filterUnannotated').checked = false;
    document.getElementById('filterLowConf').checked = false;
    document.getElementById('filterHard').checked = true;
    try { localStorage.setItem('pdb_filter', 'hard'); } catch (e) {}
    window.updateFilterBadge(); window.loadImages();
  }});
  cmds.push({ id: 'filter-low', category: window.t('cmd.cat.filters'), title: window.t('cmd.filter.low'),
    keywords: 'filter low conf', action: () => {
    window.activeFilter = 'lowconf';
    document.getElementById('filterUnannotated').checked = false;
    document.getElementById('filterLowConf').checked = true;
    document.getElementById('filterHard').checked = false;
    try { localStorage.setItem('pdb_filter', 'lowconf'); } catch (e) {}
    window.updateFilterBadge(); window.loadImages();
  }});

  const sortLabels = {
    name_asc: window.t('cmd.sort.nameAsc'), name_desc: window.t('cmd.sort.nameDesc'),
    type_asc: window.t('cmd.sort.typeAsc'), type_desc: window.t('cmd.sort.typeDesc'),
    conf_asc: window.t('cmd.sort.confAsc'), conf_desc: window.t('cmd.sort.confDesc'),
    date_desc: window.t('cmd.sort.dateDesc'), date_asc: window.t('cmd.sort.dateAsc'),
    size_desc: window.t('cmd.sort.sizeDesc'), size_asc: window.t('cmd.sort.sizeAsc'),
  };
  Object.entries(sortLabels).forEach(([k, l]) => {
    cmds.push({ id: 'sort-' + k, category: window.t('cmd.cat.sort'), title: l, keywords: 'sort order ' + k, action: () => window.setSortMode(k) });
  });

  if (window.currentImageId) {
    cmds.push({ id: 'act-autolabel', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.autolabel'), keywords: 'autolabel detect auto', shortcut: 'A', action: () => window.autolabel() });
    cmds.push({ id: 'act-save', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.save'), keywords: 'save store', shortcut: CMD + 'S', action: () => window.saveAnnotations() });
    cmds.push({ id: 'act-clear', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.clear'), keywords: 'clear reset boxes', shortcut: 'C', action: () => window.clearBoxes() });
    cmds.push({ id: 'act-hard', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.hard'), keywords: 'hard flag difficult', shortcut: 'F', action: () => window.toggleHardCurrent() });
    cmds.push({ id: 'act-zoomsel', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.zoomsel'), keywords: 'zoom selection fit', shortcut: 'Z', action: () => window.zoomToSelection() });
    cmds.push({ id: 'act-sam', category: window.t('cmd.cat.actions'), title: window.samMode ? window.t('cmd.act.samOff') : window.t('cmd.act.samOn'), keywords: 'sam segment mask click', shortcut: 'M', action: () => window.toggleSamMode() });
    cmds.push({ id: 'act-metrics', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.metrics'), keywords: 'metrics map chart confusion', action: () => window.openMetricsModal() });
    cmds.push({ id: 'act-compare', category: window.t('cmd.cat.actions'), title: 'Сравнить модели (side-by-side)', keywords: 'compare models runs mAP diff', action: () => window.openModelCompare() });
  }
  cmds.push({ id: 'act-batch', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.batch'), keywords: 'batch all autolabel', action: () => window.autolabelAllUnlabeled() });
  cmds.push({ id: 'act-stats', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.stats'), keywords: 'stats statistics charts', action: () => window.openStats() });
  cmds.push({ id: 'act-validate', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.validate'), keywords: 'validate check issues', action: () => window.openValidateModal() });
  cmds.push({ id: 'act-train', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.train'), keywords: 'train model yolo', action: () => { window.closeSettings(); setTimeout(() => window.openTrainModal(), 100); }});
  cmds.push({ id: 'extract-frames', category: window.t('cmd.cat.actions'), title: window.t('cmd.act.extract'), keywords: 'video extract frames mp4', action: () => window.triggerVideoExtract() });
  cmds.push({
    id: 'toggle-debug',
    category: window.t('cmd.cat.actions'),
    title: window.getDebugMode() ? window.t('cmd.act.debugOff') : window.t('cmd.act.debugOn'),
    keywords: 'debug yolo show all classes',
    action: () => window.setDebugMode(!window.getDebugMode()),
  });

  cmds.push({ id: 'file-rename', category: window.t('cmd.cat.files'), title: window.t('cmd.file.rename'), keywords: 'rename bulk mask pattern', action: () => window.openBulkRename() });
  cmds.push({ id: 'file-move', category: window.t('cmd.cat.files'), title: window.t('cmd.file.move'), keywords: 'move transfer project', action: () => window.openMoveCopyDialog('move') });
  cmds.push({ id: 'file-copy', category: window.t('cmd.cat.files'), title: window.t('cmd.file.copy'), keywords: 'copy duplicate project', action: () => window.openMoveCopyDialog('copy') });
  cmds.push({ id: 'file-dups', category: window.t('cmd.cat.files'), title: window.t('cmd.file.dups'), keywords: 'duplicates phash similar find', action: () => window.openDuplicatesModal() });
  cmds.push({ id: 'file-csv', category: window.t('cmd.cat.files'), title: window.t('cmd.file.csv'), keywords: 'csv export files list', action: () => window.downloadFilesCsv() });

  cmds.push({ id: 'import-url', category: window.t('cmd.cat.import'), title: window.t('cmd.imp.url'), keywords: 'import url link zip http s3 gcs', action: () => window.importFromUrl() });
  cmds.push({ id: 'import-roboflow', category: window.t('cmd.cat.import'), title: window.t('cmd.imp.roboflow'), keywords: 'import roboflow api', action: () => window.importFromRoboflow() });
  cmds.push({ id: 'import-supervisely', category: window.t('cmd.cat.import'), title: window.t('cmd.imp.supervisely'), keywords: 'import supervisely api', action: () => window.importFromSupervisely() });
  cmds.push({ id: 'import-folder', category: window.t('cmd.cat.import'), title: window.t('cmd.imp.folder'), keywords: 'import folder local path', action: () => window.importFromLocalFolder() });
  cmds.push({ id: 'import-labelbox', category: window.t('cmd.cat.import'), title: window.t('cmd.imp.labelbox'), keywords: 'import labelbox api', action: () => window.importFromLabelbox() });
  cmds.push({ id: 'import-scale', category: window.t('cmd.cat.import'), title: window.t('cmd.imp.scale'), keywords: 'import scale ai nucleus', action: () => window.importFromScale() });
  cmds.push({ id: 'import-darwin', category: window.t('cmd.cat.import'), title: window.t('cmd.imp.darwin'), keywords: 'import darwin v7', action: () => window.importFromDarwin() });

  cmds.push({ id: 'exp-yolo', category: window.t('cmd.cat.export'), title: window.t('cmd.exp.yolo'), keywords: 'export yolo download zip', action: () => { window.exportFormat = 'yolo'; window.openExportModal(); }});
  cmds.push({ id: 'exp-coco', category: window.t('cmd.cat.export'), title: window.t('cmd.exp.coco'), keywords: 'export coco download zip', action: () => { window.exportFormat = 'coco'; window.openExportModal(); }});
  cmds.push({ id: 'exp-csv', category: window.t('cmd.cat.export'), title: window.t('cmd.exp.csv'), keywords: 'csv stats export', action: () => window.downloadStatsCsv() });

  cmds.push({ id: 'nav-trash', category: window.t('cmd.cat.nav'),
    title: window.viewMode === 'trash' ? window.t('cmd.nav.trashExit') : window.t('cmd.nav.trashEnter'),
    keywords: 'trash bin deleted', action: () => window.toggleTrash() });
  cmds.push({ id: 'nav-settings', category: window.t('cmd.cat.nav'), title: window.t('cmd.nav.settings'), keywords: 'settings preferences options', action: () => window.openSettings() });
  cmds.push({ id: 'storage-backup', category: window.t('cmd.cat.nav'), title: window.t('cmd.nav.backup'), keywords: 'backup database storage db download', action: () => { window.openSettings(); setTimeout(() => window._refreshStorageInfo(), 200); }});
  cmds.push({ id: 'storage-migrate', category: window.t('cmd.cat.nav'), title: window.t('cmd.nav.migrate'), keywords: 'migrate sqlite mysql move switch local-first', action: () => {
    window.openSettings();
    setTimeout(async () => {
      window._refreshStorageInfo();
      setTimeout(() => {
        const btns = document.querySelectorAll('#storageMigrateBlock .btn-primary');
        if (btns.length) btns[0].click();
      }, 400);
    }, 200);
  }});
  cmds.push({ id: 'nav-shortcuts', category: window.t('cmd.cat.nav'), title: window.t('cmd.nav.shortcuts'), keywords: 'shortcuts keys hotkeys', shortcut: '?', action: () => window.openShortcuts() });
  cmds.push({ id: 'nav-logs', category: window.t('cmd.cat.nav'), title: window.t('cmd.nav.logs'), keywords: 'logs history events', action: () => window.openLogs() });
  cmds.push({ id: 'nav-versions', category: window.t('cmd.cat.nav'), title: window.t('cmd.nav.versions'), keywords: 'versions changelog release', action: () => window.openVersions() });

  if (window.currentProjectId) {
    (window.projectTags || []).forEach(tag => {
      cmds.push({
        id: 'tag-filter-' + tag.id,
        category: 'Теги',
        title: `Фильтр: ${tag.name} (${tag.count})`,
        keywords: 'tag тег фильтр ' + tag.name,
        action: () => {
          if (window.activeTagIds.has(tag.id)) window.activeTagIds.delete(tag.id);
          else window.activeTagIds.add(tag.id);
          window.updateFilterBadge(); window.loadImages();
        },
      });
    });
    const cls = (window.currentProjectMeta && window.currentProjectMeta.object_class) || 'pig';
    cmds.push({
      id: 'class-show',
      category: 'Классы',
      title: `Текущий класс: ${cls}`,
      keywords: 'class класс object object_class ' + cls,
      action: () => { window.openProjectEdit(window.currentProjectId); },
    });
    (window.objectClassesCache.classes || []).slice(0, 30).forEach((name) => {
      if (name === cls) return;
      cmds.push({
        id: 'class-set-' + name,
        category: 'Классы',
        title: `Класс проекта: ${name}`,
        keywords: 'class класс ' + name,
        action: async () => {
          if (!window.currentProjectId) return;
          try {
            await window.api(`/api/projects/${window.currentProjectId}/settings`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ object_class: name, object_class_source: 'list' }),
            });
            await window.loadProjects();
            window.setStatus(`Класс проекта: ${name}`);
          } catch (e) { window.setError(String(e.message).slice(0, 160)); }
        },
      });
    });
  }
  if (_paletteHistory.length) {
    const byId = new Map(cmds.map(c => [c.id, c]));
    _paletteHistory.forEach(hid => {
      const c = byId.get(hid);
      if (!c) return;
      cmds.unshift({ ...c, category: 'Недавние' });
    });
  }
  return cmds;
}

export function openCommandPalette() {
  if (window.isModalOpen('commandPaletteModal')) return;
  const input = document.getElementById('commandInput');
  if (input) input.value = '';
  _paletteActiveIdx = 0;
  renderCommandPalette('');
  window.openModal('commandPaletteModal');
  setTimeout(() => { try { input.focus(); } catch (e) {} }, 60);
}

export function closeCommandPalette() { window.closeModal('commandPaletteModal'); }

export function _filterCommands(cmds, query) {
  if (!query) return cmds;
  const q = query.toLowerCase().trim();
  const scored = [];
  for (const c of cmds) {
    const title = (c.title || '').toLowerCase();
    const kw = (c.keywords || '').toLowerCase();
    const cat = (c.category || '').toLowerCase();
    let score = 0;
    if (title.startsWith(q)) score = 100;
    else if (title.includes(q)) score = 60;
    else if (kw.includes(q)) score = 40;
    else if (cat.includes(q)) score = 20;
    if (score > 0) scored.push({ c, score });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, 100).map(x => x.c);
}

export function renderCommandPalette(query) {
  const all = _getCommands();
  const filtered = _filterCommands(all, query);
  _paletteItems = filtered;
  if (_paletteActiveIdx >= filtered.length) _paletteActiveIdx = Math.max(0, filtered.length - 1);
  const list = document.getElementById('commandList');
  list.innerHTML = '';
  if (!filtered.length) {
    const e = document.createElement('div');
    e.className = 'command-empty';
    e.textContent = 'Ничего не найдено';
    list.appendChild(e);
    return;
  }
  const groups = new Map();
  filtered.forEach((c, idx) => {
    const cat = c.category || 'Прочее';
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat).push({ c, idx });
  });
  groups.forEach((items, cat) => {
    const groupEl = document.createElement('div');
    groupEl.className = 'command-group';
    const t = document.createElement('div');
    t.className = 'command-group-title'; t.textContent = cat;
    groupEl.appendChild(t);
    items.forEach(({ c, idx }) => {
      const row = document.createElement('div');
      row.className = 'command-item' + (idx === _paletteActiveIdx ? ' active' : '');
      row.dataset.idx = String(idx);
      row.setAttribute('role', 'option');
      const title = document.createElement('span');
      title.className = 'command-item-title'; title.textContent = c.title;
      row.appendChild(title);
      if (c.shortcut) {
        const s = document.createElement('kbd');
        s.className = 'command-item-shortcut'; s.textContent = c.shortcut;
        row.appendChild(s);
      }
      row.addEventListener('click', (e) => { e.stopPropagation(); _runCommand(idx); });
      row.addEventListener('mousemove', () => {
        if (_paletteActiveIdx !== idx) { _paletteActiveIdx = idx; _highlightPaletteItem(); }
      });
      groupEl.appendChild(row);
    });
    list.appendChild(groupEl);
  });
  _highlightPaletteItem();
}

export function _highlightPaletteItem() {
  const list = document.getElementById('commandList');
  list.querySelectorAll('.command-item').forEach(el => {
    const idx = parseInt(el.dataset.idx, 10);
    el.classList.toggle('active', idx === _paletteActiveIdx);
  });
  const active = list.querySelector('.command-item.active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

export function _runCommand(idx) {
  const cmd = _paletteItems[idx];
  if (!cmd) return;
  _pushPaletteHistory(cmd.id);
  closeCommandPalette();
  setTimeout(() => {
    try { cmd.action(); } catch (e) { console.error(e); window.setError('Ошибка: ' + String(e.message || e)); }
  }, 60);
}

export function _installCommandPaletteListeners() {
  const input = document.getElementById('commandInput');
  if (!input || input.__paletteBound) return;
  input.__paletteBound = true;
  input.addEventListener('input', () => {
    _paletteActiveIdx = 0;
    renderCommandPalette(input.value);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _paletteActiveIdx = Math.min(_paletteActiveIdx + 1, Math.max(0, _paletteItems.length - 1));
      _highlightPaletteItem();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _paletteActiveIdx = Math.max(_paletteActiveIdx - 1, 0);
      _highlightPaletteItem();
    } else if (e.key === 'Enter') {
      e.preventDefault(); e.stopPropagation();
      _runCommand(_paletteActiveIdx);
    } else if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      closeCommandPalette();
    } else if (e.key === 'Home') {
      e.preventDefault(); _paletteActiveIdx = 0; _highlightPaletteItem();
    } else if (e.key === 'End') {
      e.preventDefault(); _paletteActiveIdx = Math.max(0, _paletteItems.length - 1); _highlightPaletteItem();
    }
  });
  const backdrop = document.getElementById('commandPaletteModal');
  if (backdrop) {
    backdrop.addEventListener('mousedown', (e) => {
      if (e.target.id === 'commandPaletteModal') closeCommandPalette();
    });
  }
}
