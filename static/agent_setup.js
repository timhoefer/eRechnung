(() => {
  const dialog = document.getElementById('agent-setup-dialog');
  if (!dialog) return;
  const content = document.getElementById('agent-setup-content');
  const error = document.getElementById('agent-setup-error');
  const title = document.getElementById('agent-setup-title');
  const originalLanguage = document.documentElement.lang;
  let language = originalLanguage;
  let views = null;
  let opener = null;
  let busy = false;

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
    title.textContent = language === 'de' ? 'Konfiguration einrichten' : 'Set up configuration';
    dialog.querySelector('nav.langswitch').setAttribute('aria-label', language === 'de' ? 'Sprache' : 'Language');
    dialog.querySelectorAll('[data-setup-language]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.setupLanguage === language));
    });
    dialog.querySelectorAll('[data-close-setup]').forEach(button => {
      if (button.textContent.trim() === '×') button.setAttribute('aria-label', language === 'de' ? 'Schließen' : 'Close');
    });
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
      views = result.views;
      render();
    } catch {
      showError(language === 'de'
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

  dialog.addEventListener('click', async event => {
    const close = event.target.closest('[data-close-setup]');
    if (close && !busy) { dialog.close(); return; }
    const button = event.target.closest('[data-setup-language]');
    if (!button || busy || button.dataset.setupLanguage === language || !views) return;
    setBusy(true);
    try {
      const response = await fetch(dialog.dataset.languageUrl, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        body: new URLSearchParams({ csrf: dialog.dataset.csrf, language: button.dataset.setupLanguage }),
      });
      if (!response.ok) throw new Error('Language unavailable');
      const result = await response.json();
      if (result.language !== button.dataset.setupLanguage) throw new Error('Unexpected language');
      language = result.language;
      render();
    } catch {
      showError(language === 'de' ? 'Die Sprache konnte nicht geändert werden. Deine Konfiguration bleibt erhalten.'
        : 'The language could not be changed. Your configuration is preserved.');
    } finally {
      setBusy(false);
    }
  });

  dialog.addEventListener('submit', event => {
    const form = event.target;
    event.preventDefault();
    if (busy) return;
    // Only the reviewed renewal form is submitted, never on open/language change.
    load(form.action, { method: 'POST', body: new FormData(form) });
  });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    views = null;
    content.replaceChildren();
    opener?.focus();
    if (language !== originalLanguage) {
      const anchor = opener?.closest('.agent-connection')?.id;
      window.location.assign(dialog.dataset.returnUrl + (anchor ? '#' + encodeURIComponent(anchor) : ''));
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
})();
