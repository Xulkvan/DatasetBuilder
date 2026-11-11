// @ts-check
// File operations extracted from js/main.js.
// Functions exposed on window.* so `data-action` in index.html keeps working.
import { api, downloadFile } from './api.js';
import {
  haptic, pluralImages, pluralGroups, fmtSize,
} from './utils.js';
import {
  openModal, closeModal, showConfirm, showPrompt, _openCustomDialog,
} from './ui.js';


export async function openBulkRename() {
  const n = window.selectedForDelete.size;
  if (!n) { window.setStatus(window.t('msg_522181')); return; }
  const pattern = await showPrompt(
    window.t('prompt.bulkRename.title', { n }),
    {
      text: window.t('prompt.bulkRename.text'),
      defaultValue: 'image_{n:04d}',
      hint: window.t('prompt.bulkRename.hint'),
      okText: window.t('prompt.bulkRename.ok'),
    }
  );
  if (pattern === null) return;
  const startStr = await showPrompt(
    window.t('prompt.bulkRename.startTitle'),
    { defaultValue: '1', okText: window.t('common.ok') }
  );
  if (startStr === null) return;
  const start = parseInt(startStr, 10) || 1;
  try {
    const r = await api('/api/images/bulk_rename', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_ids: Array.from(window.selectedForDelete),
        pattern: String(pattern),
        start,
      }),
    });
    await window.loadImages();
    window.setStatus(
      window.t('msg.renamedCount', { n: r.renamed })
        + (r.failed_count ? ', ' + window.t('msg.skippedCount', { n: r.failed_count }) : ''),
      5000);
    haptic('success');
  } catch (e) {
    window.setError(window.t('error.prefix') + String(e.message).slice(0, 160));
  }
}


export async function openMoveCopyDialog(mode) {
  const n = window.selectedForDelete.size;
  if (!n) { window.setStatus(window.t('msg_522181')); return; }
  const projects = window._cachedProjectsList.filter(
    p => p.id !== window.currentProjectId);
  if (!projects.length) { window.setStatus(window.t('msg_7c394f')); return; }
  const sel = document.createElement('select');
  sel.style.cssText = 'width:100%; padding:10px 14px; border-radius:10px; ' +
    'border:1px solid var(--hairline-strong); background:var(--bg-surface); ' +
    'color:var(--text-primary); font-family:inherit; font-size:0.875rem;';
  projects.forEach(p => {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = `${p.name} (${p.object_class || 'pig'}) — ${p.images_count} фото`;
    sel.appendChild(o);
  });
  const wrap = document.createElement('div');
  wrap.appendChild(sel);
  const title = mode === 'copy'
    ? `Скопировать ${n} ${pluralImages(n)}`
    : `Переместить ${n} ${pluralImages(n)}`;
  const body = mode === 'copy'
    ? 'Будут созданы новые файлы, оригиналы останутся.'
    : 'Файлы переедут в другой проект. Разметка сохранится, класс будет перезаписан.';
  const res = await _openCustomDialog({
    title, bodyText: body, selectorEl: wrap,
    okText: mode === 'copy' ? 'Скопировать' : 'Переместить',
  });
  if (!res) return;
  const targetId = parseInt(sel.value, 10);
  try {
    const url = mode === 'copy'
      ? '/api/images/bulk_copy_to_project'
      : '/api/images/bulk_move_to_project';
    const r = await api(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_ids: Array.from(window.selectedForDelete),
        target_project_id: targetId,
      }),
    });
    window.selectedForDelete.clear();
    await window.loadProjects();
    await window.loadImages();
    window.setStatus(
      window.t('msg.doneCount', { n: r.moved, word: pluralImages(r.moved) }),
      5000);
    haptic('success');
  } catch (e) {
    window.setError(window.t('error.prefix') + String(e.message).slice(0, 180));
  }
}


export async function openDuplicatesModal() {
  if (!window.currentProjectId) {
    window.setStatus(window.t('toast.pickProject')); return;
  }
  const body = document.getElementById('duplicatesBody');
  if (!body) return;
  body.innerHTML = '<p style="color:var(--text-secondary);font-size:0.8125rem;' +
    'padding:8px 0;">Ищу дубликаты…</p>';
  openModal('duplicatesModal');
  try {
    const r = await api(`/api/projects/${window.currentProjectId}/duplicates`);
    body.innerHTML = '';
    if (!r.groups.length) {
      body.innerHTML = '<p style="color:var(--success);font-size:0.875rem;' +
        'text-align:center;padding:24px 0;">✓ Дубликатов не найдено</p>';
      return;
    }
    const head = document.createElement('p');
    head.style.cssText =
      'color:var(--text-secondary);font-size:0.75rem;margin:0 0 12px;';
    head.textContent = window.t('duplicates.found', {
      n: r.total, word: pluralGroups(r.total),
    });
    body.appendChild(head);
    r.groups.slice(0, 50).forEach((g, gi) => {
      const groupEl = document.createElement('div');
      groupEl.className = 'duplicates-group';
      const header = document.createElement('div');
      header.className = 'duplicates-group-header';
      header.textContent = window.t('duplicates.groupHeader', {
        gi: gi + 1, n: g.items.length,
      });
      groupEl.appendChild(header);
      const grid = document.createElement('div');
      grid.className = 'duplicates-grid';
      g.items.forEach(it => {
        const card = document.createElement('div');
        card.className = 'duplicates-card';
        if (it.id === g.representative_id) card.classList.add('representative');
        const img = document.createElement('img');
        img.className = 'duplicates-thumb'; img.loading = 'lazy'; img.alt = '';
        img.src = `/api/images/${it.id}/thumb`;
        card.appendChild(img);
        const name = document.createElement('div');
        name.className = 'duplicates-name'; name.textContent = it.filename;
        name.dataset.tooltip = it.filename;
        card.appendChild(name);
        const meta = document.createElement('div');
        meta.className = 'duplicates-meta';
        meta.textContent = fmtSize(it.file_size || 0);
        card.appendChild(meta);
        if (it.id === g.representative_id) {
          const badge = document.createElement('span');
          badge.className = 'duplicates-badge';
          badge.textContent = window.t('duplicates.representative');
          card.appendChild(badge);
        }
        const actions = document.createElement('div');
        actions.className = 'duplicates-actions';
        const delBtn = document.createElement('button');
        delBtn.className = 'btn btn-ghost btn-sm';
        delBtn.textContent = window.t('duplicates.toTrash');
        delBtn.onclick = async () => {
          await window.deleteImage(it.id, it.filename);
          card.style.opacity = '0.4';
          card.style.pointerEvents = 'none';
        };
        actions.appendChild(delBtn);
        const openBtn = document.createElement('button');
        openBtn.className = 'btn btn-ghost btn-sm';
        openBtn.textContent = window.t('duplicates.open');
        openBtn.onclick = async () => {
          window.closeDuplicatesModal();
          await window.selectImage(it.id, { skipDirtyCheck: true });
        };
        actions.appendChild(openBtn);
        card.appendChild(actions);
        grid.appendChild(card);
      });
      groupEl.appendChild(grid);
      body.appendChild(groupEl);
    });
  } catch (e) {
    body.innerHTML = '<p style="color:var(--danger);">Ошибка: ' +
      window.escapeHtml(String(e.message || e)) + '</p>';
  }
}


export function toggleFileOpsMenu(e, closeOnly) {
  if (e) e.stopPropagation();
  const menu = document.getElementById('fileOpsMenu');
  if (!menu) return;
  if (closeOnly) { menu.classList.remove('open'); return; }
  const btn = document.getElementById('fileOpsBtn');
  const isOpen = menu.classList.contains('open');
  window.closeAllPopovers(null);
  if (isOpen) return;
  const r = btn.getBoundingClientRect();
  const W = 240;
  let left = r.left;
  if (left + W > window.innerWidth - 8) {
    left = Math.max(8, window.innerWidth - W - 8);
  }
  menu.style.position = 'fixed';
  menu.style.left = left + 'px';
  menu.style.top = (r.bottom + 6) + 'px';
  menu.style.minWidth = W + 'px';
  menu.style.zIndex = '500';
  menu.classList.add('open');
}


export async function downloadFilesCsv() {
  if (!window.currentProjectId) {
    window.setStatus(window.t('toast.pickProject')); return;
  }
  await downloadFile(
    `/api/projects/${window.currentProjectId}/files.csv`,
    `files_project_${window.currentProjectId}.csv`);
}


export async function downloadBoxesCsv() {
  if (!window.currentProjectId) {
    window.setStatus(window.t('toast.pickProject')); return;
  }
  await downloadFile(
    `/api/projects/${window.currentProjectId}/boxes.csv`,
    `boxes_project_${window.currentProjectId}.csv`);
}


// ─── window bindings (index.html → data-action) ─────────────────────────
window.openBulkRename = openBulkRename;
window.openMoveCopyDialog = openMoveCopyDialog;
window.openDuplicatesModal = openDuplicatesModal;
window.toggleFileOpsMenu = toggleFileOpsMenu;
window.downloadFilesCsv = downloadFilesCsv;
window.downloadBoxesCsv = downloadBoxesCsv;

window.openBulkRenameFromMenu = function () {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.openBulkRename === 'function') window.openBulkRename();
};

window.openMoveCopyDialogFromMenu = function (mode) {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.openMoveCopyDialog === 'function') window.openMoveCopyDialog(mode);
};

window.openDuplicatesModalFromMenu = function () {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.openDuplicatesModal === 'function') window.openDuplicatesModal();
};

window.downloadFilesCsvFromMenu = function () {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.downloadFilesCsv === 'function') window.downloadFilesCsv();
};

window.downloadBoxesCsvFromMenu = function () {
  window.toggleFileOpsMenu(null, true);
  if (typeof window.downloadBoxesCsv === 'function') window.downloadBoxesCsv();
};
