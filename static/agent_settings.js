(() => {
  const dialog = document.getElementById('agent-connection-dialog');
  const add = document.getElementById('agent-connection-add');
  if (dialog && add) {
    add.addEventListener('click', () => dialog.showModal());
    dialog.querySelectorAll('[data-close-connection]').forEach(button => {
      button.addEventListener('click', () => dialog.close());
    });
    dialog.addEventListener('close', () => add.focus());
  }
  const mode = document.getElementById('agent-customer-mode');
  if (mode) {
    const update = () => {
      document.querySelectorAll('[data-customer-mode]').forEach(element => {
        element.hidden = element.dataset.customerMode !== mode.value;
        if (element.tagName === 'FIELDSET') element.disabled = element.hidden;
      });
    };
    mode.addEventListener('change', update);
    update();
  }
  const tabs = document.getElementById('configuration-tabs');
  if (tabs) {
    const buttons = Array.from(tabs.querySelectorAll('[role="tab"]'));
    const activate = selected => {
      buttons.forEach(button => {
        const active = button === selected;
        button.setAttribute('aria-selected', String(active));
        button.tabIndex = active ? 0 : -1;
        document.getElementById(button.getAttribute('aria-controls')).hidden = !active;
      });
      document.getElementById('configuration-copy-status').textContent = '';
    };
    buttons.forEach((button, index) => {
      button.addEventListener('click', () => activate(button));
      button.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % buttons.length;
        else if (event.key === 'ArrowLeft') next = (index + buttons.length - 1) % buttons.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = buttons.length - 1;
        else return;
        event.preventDefault();
        activate(buttons[next]);
        buttons[next].focus();
      });
    });
    activate(buttons[0]);
    tabs.hidden = false;
  }
  const status = document.getElementById('configuration-copy-status');
  if (status) {
    document.querySelectorAll('[data-copy-target]').forEach(copy => {
      const target = document.getElementById(copy.dataset.copyTarget);
      if (!target) return;
      copy.hidden = false;
      copy.addEventListener('click', async () => {
        status.textContent = '';
        try {
          await navigator.clipboard.writeText(target.value ?? target.textContent);
          status.textContent = copy.dataset.success;
        } catch {
          status.textContent = copy.dataset.failure;
        }
      });
    });
  }
})();
