// Settings are loaded dynamically: delegate events and replace only the access
// card, keeping the invoice draft, archive scope and selection untouched.
(() => {
  let busy = false;
  const restoreFocus = () => document.querySelector('#agent-access-card [role="switch"]')?.focus();
  document.addEventListener('click', event => {
    if (!event.target.closest('[data-agent-cancel]')) return;
    document.getElementById('agent-disable-dialog')?.close();
    restoreFocus();
  });
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!form.matches('.agent-access-form')) return;
    event.preventDefault();
    if (busy) return;
    busy = true;
    const card = document.getElementById('agent-access-card');
    const dialog = document.getElementById('agent-disable-dialog');
    const error = card.querySelector('[data-agent-error]');
    const button = form.querySelector('[type="submit"]');
    error.hidden = true;
    button.disabled = true;
    try {
      const response = await fetch(form.getAttribute('action'), {
        method: 'POST', body: new FormData(form), headers: {'X-Requested-With': 'fetch'},
      });
      const data = await response.json();
      if (data.confirmation && (response.ok || response.status === 409)) {
        dialog.innerHTML = data.confirmation;
        if (!dialog.open) dialog.showModal();
        dialog.querySelector('[data-agent-cancel]')?.focus();
      } else {
        if (!response.ok || typeof data.controls !== 'string' || typeof data.disclaimer !== 'string') {
          throw new Error('Access update failed');
        }
        card.innerHTML = data.controls;
        const disclaimer = document.getElementById('disclaimer-text');
        if (disclaimer) disclaimer.textContent = data.disclaimer;
        if (dialog.open) dialog.close();
        restoreFocus();
      }
    } catch {
      if (dialog.open) dialog.close();
      error.hidden = false;
      restoreFocus();
    } finally {
      button.disabled = false;
      busy = false;
    }
  });
})();
