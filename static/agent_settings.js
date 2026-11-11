(() => {
  const initialized = new WeakSet();
  function init() {
    const dialog = document.getElementById('agent-connection-dialog');
    const add = document.getElementById('agent-connection-add');
    if (dialog && add && !initialized.has(dialog)) {
      initialized.add(dialog);
      add.addEventListener('click', () => dialog.showModal());
      dialog.querySelectorAll('[data-close-connection]').forEach(button => {
        button.addEventListener('click', () => dialog.close());
      });
      dialog.addEventListener('close', () => add.focus());
    }
    initPermissionForms();
  }
  function initPermissionForms() {
    document.querySelectorAll('form[data-agent-permissions]').forEach(form => {
      if (initialized.has(form)) return;
      initialized.add(form);
      let attempted = false;
      const mode = form.querySelector('[data-customer-access]');
      const validateSelections = () => {
        let firstInvalid = null;
        for (const name of ['issuers', 'customers']) {
          const error = form.querySelector(`[data-selection-error="${name}"]`);
          const options = [...form.querySelectorAll(`input[name="${name}"]`)];
          const required = name === 'issuers' || mode.value === 'selected';
          const invalid = required && !options.some(option => option.type === 'hidden' ? option.value : option.checked);
          error.hidden = !attempted || !invalid;
          options.forEach(option => {
            if (attempted && invalid) option.setAttribute('aria-invalid', 'true');
            else option.removeAttribute('aria-invalid');
          });
          if (invalid && !firstInvalid) firstInvalid = options[0] || error;
        }
        return firstInvalid;
      };
      form.addEventListener('submit', event => {
        attempted = true;
        const invalid = validateSelections();
        if (!invalid) return;
        event.preventDefault();
        event.stopPropagation(); // Do not send an incomplete grant to the server.
        invalid.focus();
      });
      form.addEventListener('change', validateSelections);
      const update = () => {
        form.querySelectorAll('[data-customer-mode]').forEach(element => {
          element.hidden = element.dataset.customerMode !== mode.value;
          if (element.tagName === 'FIELDSET') element.disabled = element.hidden;
        });
      };
      mode.addEventListener('change', update);
      update();
    });
  }
  function initializeConfiguration() {
    const tabs = document.getElementById('configuration-tabs');
    if (tabs && !initialized.has(tabs)) {
      initialized.add(tabs);
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
        if (!target || initialized.has(copy)) return;
        initialized.add(copy);
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
  }
  window.AgentSettings = { init };
  init();
  initializeConfiguration();
  document.addEventListener('agent-setup-rendered', () => {
    initPermissionForms();
    initializeConfiguration();
  });
})();
