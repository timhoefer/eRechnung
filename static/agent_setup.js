(() => {
  const initialized = new WeakSet();
  function init() {
    const dialog = document.getElementById('agent-setup-dialog');
    if (!dialog || initialized.has(dialog)) return;
    initialized.add(dialog);
    const content = document.getElementById('agent-setup-content');
    const error = document.getElementById('agent-setup-error');
    const language = document.documentElement.lang;
    let views = null;
    let opener = null;
    let busy = false;
    let refreshOnClose = false;

    function setBusy(value) {
      busy = value;
      dialog.setAttribute('aria-busy', String(value));
      dialog.querySelectorAll('button').forEach(button => { button.disabled = value; });
    }

    function showError(message) {
      error.textContent = message;
      error.hidden = false;
    }

    function render() {
      const selectedTab = content.querySelector('[role="tab"][aria-selected="true"]')?.id;
      const scroll = dialog.scrollTop;
      content.innerHTML = views[language];
      dialog.lang = language;
      error.hidden = true;
      document.dispatchEvent(new Event('agent-setup-rendered'));
      if (selectedTab) document.getElementById(selectedTab)?.click();
      dialog.scrollTop = scroll;
    }

    async function load(url, options = {}) {
      setBusy(true);
      error.hidden = true;
      try {
        const response = await fetch(url, {
          ...options, credentials: 'same-origin', cache: 'no-store',
          headers: { 'X-Requested-With': 'fetch' },
        });
        if (!response.ok && response.status !== 409) throw new Error('Setup unavailable');
        const result = await response.json();
        if (!result.views?.de || !result.views?.en) throw new Error('Incomplete setup');
        refreshOnClose ||= Boolean(result.updated);
        views = result.views;
        render();
      } catch {
        const editing = ['rename', 'permissions'].includes(options.body?.get('action'));
        // A lost response may follow a successful save. Refresh on close, never retry.
        refreshOnClose ||= editing;
        showError(editing ? (language === 'de'
          ? 'Das Speichern konnte nicht bestätigt werden. Öffne die Konfiguration erneut und prüfe den aktuellen Stand.'
          : 'Saving could not be confirmed. Reopen configuration and review its current settings.') : language === 'de'
          ? 'Die Konfiguration konnte nicht geladen werden. Falls du gerade einen Schlüssel erneuert hast, könnte der bisherige bereits ungültig sein. Öffne die Konfiguration erneut, um einen neuen Schlüssel einzurichten.'
          : 'The configuration could not be loaded. If you just renewed a credential, the previous one may already be invalid. Reopen configuration to set up a new credential.');
      } finally {
        setBusy(false);
      }
    }

    document.querySelectorAll('[data-open-setup]').forEach(link => {
      link.setAttribute('aria-haspopup', 'dialog');
      link.setAttribute('aria-controls', 'agent-setup-dialog');
      link.addEventListener('click', event => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        if (busy) return;
        opener = link;
        content.replaceChildren();
        dialog.showModal();
        load(link.href);
      });
    });

    dialog.addEventListener('click', event => {
      const close = event.target.closest('[data-close-setup]');
      if (close && !busy) dialog.close();
    });

    dialog.addEventListener('submit', event => {
      const form = event.target;
      event.preventDefault();
      if (busy) return;
      // Submit only the chosen action, never on open.
      // A named input "action" shadows the form.action DOM property.
      load(form.getAttribute('action'), { method: 'POST', body: new FormData(form) });
    });
    dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    dialog.addEventListener('close', () => {
      views = null;
      content.replaceChildren();
      opener?.focus();
      if (refreshOnClose) {
        refreshOnClose = false;
        if (window.refreshAgentSettings) window.refreshAgentSettings();
        else window.location.reload();
      }
    });

    const initial = document.getElementById('agent-setup-initial');
    if (initial) {
      views = JSON.parse(initial.textContent);
      initial.remove();
      render();
      dialog.removeAttribute('open'); // Server-rendered content also works without JS.
      dialog.showModal();
    }
  }
  window.AgentSetup = { init };
  init();
})();
