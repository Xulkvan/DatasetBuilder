// @ts-check

/**
 * @typedef {import('./types.js').BoxData} BoxData
 * @typedef {import('./types.js').AppState} AppState
 */

// V11.8.0: Extracted Keyboard Shortcuts

export function installKeyboardListeners() {
  document.addEventListener('keydown', e => {
    const isMod = e.ctrlKey || e.metaKey;

    if (window.samPreview && (e.code === 'Enter' || e.code === 'NumpadEnter')) {
      e.preventDefault(); e.stopPropagation(); window._confirmSamPreview(); return;
    }
    if (window.samPreview && e.code === 'Escape') {
      e.preventDefault(); e.stopPropagation(); window._clearSamPreview(); return;
    }

    if (window.isModalOpen('dialogModal') && e.code === 'Escape') {
      e.preventDefault(); e.stopPropagation(); window._skipFocusReturnOnce = true; window._closeDialog(null); return;
    }

    if (isMod && e.code === 'KeyK') {
      e.preventDefault();
      if (window.isModalOpen('commandPaletteModal')) window.closeCommandPalette();
      else window.openCommandPalette();
      return;
    }
    if (window.isModalOpen('commandPaletteModal')) return;

    if (isMod && e.shiftKey && e.code === 'KeyZ' && window.MODAL_STACK.length === 0) {
      e.preventDefault(); window.redoListAction(); return;
    }
    if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      if (e.code === 'ArrowRight') { e.preventDefault(); window._navigateWithAid('next'); return; }
      if (e.code === 'ArrowLeft')  { e.preventDefault(); window._navigateWithAid('prev'); return; }
    }
    if (isMod && e.code === 'Backslash') {
      e.preventDefault(); window.toggleFocusMode(); return;
    }

    {
      const _t = (e.target && e.target.tagName || '').toLowerCase();
      const _inInput = (_t === 'input' || _t === 'textarea' || _t === 'select');
      if (isMod && !_inInput) {
        if (e.code === 'KeyZ' && !e.shiftKey) {
          e.preventDefault();
          if (window.historyIndex > 0) window.undo();
          else if (window._listUndoStack.length) window.undoListAction();
          else window.undo();
          return;
        }
        if (e.code === 'KeyY' || (e.shiftKey && e.code === 'KeyZ')) {
          e.preventDefault();
          if (window._listRedoStack.length) window.redoListAction();
          else window.redo();
          return;
        }
      }
    }

    if (isMod && e.code === 'KeyS' && window.isModalOpen('settingsModal')) {
      e.preventDefault(); window.saveSettings(); return;
    }

    const tag = (e.target && e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      if (e.key === 'Escape') {
        const popover = document.querySelector('.sort-menu.open, .custom-select.open, .color-picker-menu.open, .class-search.open');
        if (popover) { e.preventDefault(); window.closeAllPopovers(null); return; }
      }
      return;
    }
    if (window.isModalOpen('dialogModal')) {
      if (e.code === 'Escape') { e.preventDefault(); window._skipFocusReturnOnce = true; window._closeDialog(null); return; }
      if (e.code === 'Enter' || e.code === 'NumpadEnter') {
        const _dlg = document.getElementById('dialogModal');
        const _act = document.activeElement;
        const _tag = (_act && _act.tagName || '').toLowerCase();
        const _onBtnInside = _dlg && _act && _dlg.contains(_act) && _tag === 'button';
        if (_onBtnInside) return;
        if (_tag !== 'input' && _tag !== 'textarea' && _tag !== 'select') {
          e.preventDefault(); window._closeDialog(true); return;
        }
      }
      return;
    }
    const isHKey = e.code === 'KeyH';
    const isQuestionByCode = e.code === 'Slash' && e.shiftKey;
    const isQuestionByKey = e.key === '?';
    if ((isHKey || isQuestionByCode || isQuestionByKey) && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (window.isModalOpen('shortcutsModal')) { e.preventDefault(); window.closeShortcuts(); return; }
      if (window.MODAL_STACK.length === 0) { e.preventDefault(); window.openShortcuts(); return; }
      return;
    }
    if (window.MODAL_STACK.length) {
      if (e.code === 'Enter' || e.code === 'NumpadEnter') {
        const _topId = window.MODAL_STACK[window.MODAL_STACK.length - 1];
        const _noEnter = { importModal: 1, importSourceModal: 1 };
        if (!_noEnter[_topId]) {
          const _topEl = document.getElementById(_topId);
          const _act = document.activeElement;
          const _tag = (_act && _act.tagName || '').toLowerCase();
          const _inField = _tag === 'input' || _tag === 'textarea' || _tag === 'select';
          const _onBtn = _topEl && _act && _topEl.contains(_act) && _tag === 'button';
          if (_topEl && !_inField && !_onBtn) {
            const _btn =
              _topEl.querySelector('.modal-actions .btn-primary:not([disabled])')
              || _topEl.querySelector('.modal-actions .btn-danger:not([disabled])')
              || _topEl.querySelector('.modal-actions .btn:not(.btn-ghost):not([disabled])')
              || _topEl.querySelector('[data-autofocus]:not([disabled])');
            if (_btn && typeof _btn.click === 'function') { e.preventDefault(); _btn.click(); return; }
          }
        }
      }
      if (e.code === 'Escape') {
        e.preventDefault();
        window._skipFocusReturnOnce = true;
        const top = window.MODAL_STACK[window.MODAL_STACK.length - 1];
        if (top === 'previewModal') window.closePreview();
        else if (top === 'statsModal') window.closeStats();
        else if (top === 'settingsModal') window.closeSettings();
        else if (top === 'exportModal') window.closeExportModal();
        else if (top === 'validateModal') window.closeValidateModal();
        else if (top === 'tagsManagerModal') window.closeTagsManager();
        else if (top === 'importModal') window.closeImportModal();
        else if (top === 'importSourceModal') window.closeImportSourceModal();
        else if (top === 'tracksModal') window.closeTracksModal();
        else if (top === 'trackPlayerModal') window.closeTrackPlayer();
        else if (top === 'trainModal') window.closeTrainModal();
        else if (top === 'similarModal') window.closeSimilarModal();
        else if (top === 'shortcutsModal') window.closeShortcuts();
        else if (top === 'tagCreateModal') window.closeTagCreate();
        else if (top === 'versionsModal') window.closeVersions();
        else if (top === 'logsModal') window.closeLogs();
        else if (top === 'metricsModal') window.closeMetricsModal();
        else if (top === 'duplicatesModal') window.closeDuplicatesModal();
        else if (top === 'projectModal') window.closeProjectModal();
        else if (top === 'ffmpegHelpModal') window.closeFfmpegHelp();
        else window.closeModal(top);
      }
      return;
    }

    if (e.key === 'Escape') {
      const openPopovers = document.querySelectorAll('.sort-menu.open, .custom-select.open, .color-picker-menu.open, .class-search.open');
      if (openPopovers.length) { e.preventDefault(); window.closeAllPopovers(null); return; }
    }
    const code = e.code || '';
    if (code === 'Space' && !window.spacePressed) {
      e.preventDefault(); window.spacePressed = true;
      document.getElementById('canvasViewport').classList.add('space-held');
      return;
    }
    if ((e.ctrlKey || e.metaKey) && code === 'KeyS') { e.preventDefault(); window.saveAnnotations(); return; }
    if ((e.ctrlKey || e.metaKey) && code === 'KeyZ' && !e.shiftKey) { e.preventDefault(); window.undo(); return; }
    if ((e.ctrlKey || e.metaKey) && (code === 'KeyY' || (e.shiftKey && code === 'KeyZ'))) { e.preventDefault(); window.redo(); return; }
    if ((e.ctrlKey || e.metaKey) && code === 'KeyA') {
      e.preventDefault();
      if (window.AppState.boxes.length) {
        window.AppState.multiSelected = new Set(window.AppState.boxes.map((_, i) => i));
        window.selectedIndex = -1;
        window.updateSelectionClasses();
        window.setStatus(`Выделено рамок: ${window.AppState.boxes.length}`);
      }
      return;
    }
    if (!e.ctrlKey && !e.metaKey && !e.altKey) {
      const BEH_KEYS = { Digit1: 'eat', Digit2: 'walk', Digit3: 'lie', Digit4: 'drink', Digit5: 'stand', Digit6: 'active' };
      if (BEH_KEYS[code] && !e.shiftKey) { e.preventDefault(); window._applyBehaviorToTargets(BEH_KEYS[code]); return; }
      if (code === 'Digit0' && e.shiftKey) { e.preventDefault(); window._applyAnimalIdToTargets(null); return; }
      if (code === 'Digit0' && !e.shiftKey) { e.preventDefault(); window._assignNextAnimalId(); return; }
      if (code === 'KeyA') { e.preventDefault(); window.autolabel(); return; }
      if (code === 'KeyS') { e.preventDefault(); window.saveAnnotations(); return; }
      if (code === 'KeyD') { e.preventDefault(); window.deleteSelectedBox(); return; }
      if (code === 'KeyC') { e.preventDefault(); window.clearBoxes(); return; }
      if (code === 'KeyF') { e.preventDefault(); window.toggleHardCurrent(); return; }
      if (code === 'KeyL') { e.preventDefault(); window.toggleFreezeSelected(); return; }
      if (code === 'KeyM') { e.preventDefault(); window.toggleSamMode(); return; }
      if (code === 'KeyZ') { e.preventDefault(); window.zoomToSelection(); return; }
      if (code === 'KeyG' && e.shiftKey) { e.preventDefault(); window.setDebugMode(!window.getDebugMode()); return; }
      if (code === 'KeyK' && e.shiftKey) { e.preventDefault(); window.toggleSkeletonMode(); return; }
      if (code === 'KeyN' && e.shiftKey) { e.preventDefault(); window.createBoxInCenter(); return; }
      if (code === 'KeyR') { e.preventDefault(); window.runAutolabel(); return; }
      if (code === 'KeyN') { e.preventDefault(); window.navigateToNextUnlabeled(); return; }
      if (code === 'KeyP') { e.preventDefault(); window.navigateToPrevUnlabeled(); return; }
      if (code === 'Enter' || code === 'NumpadEnter') { e.preventDefault(); window.acceptAndNext(); return; }
      if (code === 'Equal' || code === 'NumpadAdd') { e.preventDefault(); window.zoomToCenter(1.25); return; }
      if (code === 'Minus' || code === 'NumpadSubtract') { e.preventDefault(); window.zoomToCenter(0.8); return; }
      if (code === 'Digit0' || code === 'Numpad0') { e.preventDefault(); window.zoomReset(); return; }
      if (code === 'Escape') {
        if (window.samPreview) { e.preventDefault(); window._clearSamPreview(); return; }
        if (window.samMode) { e.preventDefault(); window.setSamMode(false); return; }
        window.selectedIndex = -1;
        window.AppState.multiSelected.clear();
        window.updateSelectionClasses();
        document.querySelectorAll('.sort-menu').forEach(m => m.classList.remove('open'));
        return;
      }
    }
    if (code.startsWith('Arrow')) {
      // V11.6.0: если фокус на рамке, принудительно выделяем её
      if (document.activeElement && document.activeElement.classList.contains('box')) {
        const idx = parseInt(document.activeElement.dataset.idx, 10);
        if (!isNaN(idx) && window.selectedIndex !== idx) {
          window.State.selectedIndex = idx;
          window.State.multiSelected.clear();
          window.updateSelectionClasses();
        }
      }

      const indices = window.getSelectedIndices().filter(i => !window.AppState.boxes[i].frozen);
      if (indices.length) {
        e.preventDefault();
        const step = e.shiftKey ? 0.02 : 0.005;
        let dx = 0, dy = 0;
        if (code === 'ArrowRight') dx = step;
        if (code === 'ArrowLeft') dx = -step;
        if (code === 'ArrowDown') dy = step;
        if (code === 'ArrowUp') dy = -step;
        const _keepAttrs = (b) => ({ behavior: b.behavior || null, animal_id: (b.animal_id != null) ? b.animal_id : null, keypoints: Array.isArray(b.keypoints) ? b.keypoints : [] });
        if (indices.length > 1) {
          indices.forEach(i => {
            const b = window.AppState.boxes[i];
            window.AppState.boxes[i] = window.clampBox({ x: b.x + dx, y: b.y + dy, w: b.w, h: b.h, label: b.label, confidence: null, frozen: false, ..._keepAttrs(b) });
          });
        } else if (e.shiftKey) {
          const i = indices[0]; const b = window.AppState.boxes[i];
          window.AppState.boxes[i] = window.clampBox({ x: b.x, y: b.y, w: b.w + dx, h: b.h + dy, label: b.label, confidence: null, frozen: false, ..._keepAttrs(b) });
        } else {
          const i = indices[0]; const b = window.AppState.boxes[i];
          window.AppState.boxes[i] = window.clampBox({ x: b.x + dx, y: b.y + dy, w: b.w, h: b.h, label: b.label, confidence: null, frozen: false, ..._keepAttrs(b) });
        }
        window.renderBoxes(); window.pushHistory(); window.markDirty();
        return;
      }
      if (code === 'ArrowRight' || code === 'ArrowDown') { e.preventDefault(); window.navigateImage(1); return; }
      if (code === 'ArrowLeft' || code === 'ArrowUp') { e.preventDefault(); window.navigateImage(-1); return; }
    }
    if (code === 'Delete' || code === 'Backspace') {
      const freezable = window.getSelectedIndices().filter(i => !window.AppState.boxes[i].frozen);
      if (freezable.length) { e.preventDefault(); window.deleteSelectedBox(); }
    }
  });

  document.addEventListener('keyup', e => {
    if (e.code === 'Space') { window.spacePressed = false; document.getElementById('canvasViewport').classList.remove('space-held'); }
  });
}
