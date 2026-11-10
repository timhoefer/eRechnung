/* Selection is scoped to the displayed year and issuer filter. */
(() => {
  function capture(root = document) {
    const card = root.querySelector('.archive-card');
    if (!card || card.dataset.selecting !== 'true') return null;
    return {scope: card.dataset.archiveScope,
      entries: [...card.querySelectorAll('[data-archive-entry]:not(:disabled)')].filter(entry => entry.checked).map(entry => entry.value)};
  }

  function isSortChange(form) {
    const changed = [...form.querySelectorAll('select')].filter(select =>
      select.value !== [...select.options].find(option => option.defaultSelected)?.value);
    return changed.length === 1 && changed[0].name === 'sort';
  }

  // The standalone archive navigates to a new page. Carry its selection once,
  // confined to this tab, the exact destination, data folder, issuer and year.
  const storageKey = 'erechnung:archive-sort-selection';
  function rememberSort(form) {
    try {
      sessionStorage.removeItem(storageKey);
      const selection = isSortChange(form) ? capture() : null;
      if (!selection) return;
      const url = new URL(form.action, window.location.href);
      url.search = new URLSearchParams(new FormData(form)).toString();
      sessionStorage.setItem(storageKey, JSON.stringify({url: url.href, selection}));
    } catch { /* Sorting still works if browser storage is unavailable. */ }
  }
  function takeSavedSort() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey));
      sessionStorage.removeItem(storageKey);
      return saved?.url === window.location.href ? saved.selection : null;
    } catch { return null; }
  }

  function init(root = document, selection = null) {
    root.querySelectorAll('.archive-card').forEach(card => {
      if (card.dataset.selectionReady) return;
      card.dataset.selectionReady = 'true';
      const toggle = card.querySelector('[data-archive-select]');
      const form = card.querySelector('#archive-selection');
      if (!toggle || !form) return;
      const entries = [...card.querySelectorAll('[data-archive-entry]:not(:disabled)')];
      const quarters = [...card.querySelectorAll('[data-archive-quarter]')];
      const all = card.querySelector('[data-archive-all]');
      const count = card.querySelector('[data-archive-count]');
      const status = card.querySelector('[data-archive-export-status]');
      const submit = form.querySelector('button[type="submit"]');
      let busy = false;
      toggle.hidden = entries.length === 0;
      const mark = (checkbox, choices) => {
        const selected = choices.filter(entry => entry.checked).length;
        checkbox.checked = choices.length > 0 && selected === choices.length;
        checkbox.indeterminate = selected > 0 && selected < choices.length;
        checkbox.disabled = choices.length === 0;
      };
      const update = () => {
        const selected = entries.filter(entry => entry.checked).length;
        count.textContent = card.dataset.archiveCountLabel.replace('{n}', selected);
        submit.disabled = busy || selected === 0;
        mark(all, entries);
        quarters.forEach(q => mark(q, entries.filter(entry => entry.dataset.quarter === q.dataset.archiveQuarter)));
      };
      const setSelecting = active => {
        card.dataset.selecting = String(active);
        toggle.querySelector('[data-archive-select-text]').textContent = active ? card.dataset.archiveDoneLabel : card.dataset.archiveSelectLabel;
        toggle.setAttribute('aria-pressed', String(active));
        const hint = card.querySelector('[data-archive-hint]');
        if (hint) hint.textContent = active ? hint.dataset.selectLabel : hint.dataset.previewLabel;
        form.hidden = !active;
        if (!active) entries.forEach(entry => { entry.checked = false; });
        status.textContent = '';
        update();
      };
      toggle.addEventListener('click', () => setSelecting(card.dataset.selecting !== 'true'));
      const toggleRow = event => {
        if (card.dataset.selecting !== 'true') return;
        const row = event.target.closest('.arch-row');
        if (!row || event.target.closest('a, button, input, label, select, summary, details')) return;
        if (event.type === 'keydown' && (event.target !== row || !['Enter', ' '].includes(event.key))) return;
        const entry = row.querySelector('[data-archive-entry]');
        // A selection click must not bubble into the PDF-opening handler.
        event.preventDefault();
        event.stopPropagation();
        if (!entry || entry.disabled) return;
        entry.checked = !entry.checked;
        update();
      };
      card.addEventListener('click', toggleRow);
      card.addEventListener('keydown', toggleRow);
      all.addEventListener('change', () => {
        entries.forEach(entry => { entry.checked = all.checked; });
        update();
      });
      quarters.forEach(q => q.addEventListener('change', () => {
        entries.filter(entry => entry.dataset.quarter === q.dataset.archiveQuarter).forEach(entry => { entry.checked = q.checked; });
        update();
      }));
      entries.forEach(entry => entry.addEventListener('change', update));
      form.addEventListener('submit', async event => {
        event.preventDefault();
        event.stopPropagation();
        if (busy || !entries.some(entry => entry.checked)) return;
        busy = true;
        let failureMessage = card.dataset.exportFailed;
        status.textContent = '';
        update();
        try {
          // One JSON document avoids multipart's 1,000-field limit for large archives.
          const selected = entries.filter(entry => entry.checked).map(entry => JSON.parse(entry.value));
          const response = await fetch(form.action, {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({entries: selected})});
          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            if (typeof error.message === 'string') failureMessage = error.message;
            throw new Error('Export failed');
          }
          if (card.dataset.desktop === 'true') {
            if (!(await response.json()).ok) throw new Error('Export failed');
          } else {
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement('a');
            link.href = url;
            link.download = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || 'invoices.csv';
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          }
        } catch {
          status.textContent = failureMessage;
        } finally {
          busy = false;
          update();
        }
      });
      if (selection && selection.scope === card.dataset.archiveScope && Array.isArray(selection.entries)) {
        const selected = new Set(selection.entries);
        entries.forEach(entry => { entry.checked = selected.has(entry.value); });
        setSelecting(true);
      } else update();
    });
  }
  window.ArchiveSelection = {init, capture, isSortChange, rememberSort};
  init(document, takeSavedSort());
})();
