/* Selection is scoped to the displayed year and issuer filter. */
(() => {
  function init(root = document) {
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
      toggle.addEventListener('click', () => {
        const active = card.dataset.selecting !== 'true';
        card.dataset.selecting = String(active);
        toggle.textContent = active ? card.dataset.archiveDoneLabel : card.dataset.archiveSelectLabel;
        toggle.setAttribute('aria-pressed', String(active));
        form.hidden = !active;
        card.querySelectorAll('[data-archive-group-heading]').forEach(heading => { heading.colSpan = active ? 5 : 4; });
        if (!active) entries.forEach(entry => { entry.checked = false; });
        status.textContent = '';
        update();
      });
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
        status.textContent = '';
        update();
        try {
          const response = await fetch(form.action, {method: 'POST', body: new FormData(form)});
          if (!response.ok) throw new Error('Export failed');
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
          status.textContent = card.dataset.exportFailed;
        } finally {
          busy = false;
          update();
        }
      });
      update();
    });
  }
  window.ArchiveSelection = {init};
  init();
})();
