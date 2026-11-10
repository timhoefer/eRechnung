// Update only agent settings. The invoice draft and archive selection stay put.
(() => {
  let busy = false;
  let refreshAfterClose = false;
  let opener = null;
  const boundDialogs = new WeakSet();
  const root = () => document.getElementById('agent-management');
  const restoreFocus = () => {
    if (opener?.isConnected) opener.focus();
    else if (opener?.id && document.getElementById(opener.id)) document.getElementById(opener.id).focus();
    else document.querySelector('#agent-access-card [role="switch"]')?.focus();
  };
  const headers = { 'X-Requested-With': 'fetch' };
  window.AgentAccess = { isBusy: () => busy };

  async function refresh() {
    if (window.refreshAgentSettings) await window.refreshAgentSettings();
    else if (root()) await update(root().dataset.refreshUrl);
  }

  function showError() {
    const source = document.querySelector('[data-agent-error]');
    const dialog = root()?.querySelector('dialog[open]');
    let error = dialog?.querySelector('[data-agent-error]');
    if (dialog && !error) {
      error = document.createElement('p');
      error.dataset.agentError = '';
      error.className = 'flash err';
      error.setAttribute('role', 'alert');
      error.textContent = source.textContent;
      dialog.append(error);
    }
    (error || source).hidden = false;
  }

  async function update(url, options = {}) {
    if (busy) return;
    busy = true;
    const section = root();
    section.querySelectorAll('[data-agent-error]').forEach(error => { error.hidden = true; });
    const buttons = [...section.querySelectorAll('button')].filter(button => !button.disabled);
    buttons.forEach(button => { button.disabled = true; });
    try {
      const response = await fetch(url, { ...options, headers, credentials: 'same-origin', cache: 'no-store' });
      const data = await response.json();
      if (data.confirmation && (response.ok || response.status === 409)) {
        const dialog = document.getElementById('agent-disable-dialog');
        dialog.innerHTML = data.confirmation;
        refreshAfterClose ||= Boolean(data.decided);
        if (!boundDialogs.has(dialog)) {
          boundDialogs.add(dialog);
          dialog.addEventListener('close', () => {
            dialog.replaceChildren();
            restoreFocus();
            if (refreshAfterClose) {
              refreshAfterClose = false;
              refresh();
            }
          });
        }
        if (!dialog.open) dialog.showModal();
        dialog.querySelector('[data-agent-cancel]')?.focus();
      } else {
        if (!response.ok || typeof data.management !== 'string' || typeof data.disclaimer !== 'string') {
          throw new Error('Agent settings update failed');
        }
        section.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
        section.outerHTML = data.management;
        const disclaimer = document.getElementById('disclaimer-text');
        if (disclaimer) disclaimer.textContent = data.disclaimer;
        window.AgentSettings?.init();
        window.AgentSetup?.init();
        if (!root().querySelector('dialog[open]')) restoreFocus();
      }
    } catch {
      // Keep the reviewed form on failure; never retry a mutation automatically.
      showError();
    } finally {
      buttons.forEach(button => { button.disabled = false; });
      busy = false;
    }
  }

  document.addEventListener('cancel', event => {
    if (busy && event.target.closest('#agent-management')) event.preventDefault();
  }, true);
  document.addEventListener('click', event => {
    if (event.target.closest('[data-agent-cancel]')) {
      if (!busy) document.getElementById('agent-disable-dialog')?.close();
      return;
    }
    const link = event.target.closest('[data-agent-review], [data-agent-refresh]');
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    opener = link;
    update(link.href);
  });
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!form.matches('.agent-access-form, .agent-management-form')) return;
    event.preventDefault();
    if (busy) return;
    opener = event.submitter;
    const body = new FormData(form);
    // FormData(form) omits the clicked button: approval must be explicit.
    if (event.submitter?.name) body.append(event.submitter.name, event.submitter.value);
    return update(form.getAttribute('action'), { method: 'POST', body });
  });
})();
