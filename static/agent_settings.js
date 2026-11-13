(() => {
  const initialized = new WeakSet();
  function showSelectionError(form, name, options, error, invalid) {
    error.hidden = !invalid;
    const group = form.querySelector(`[data-selection-group="${name}"]`);
    [group, ...options].filter(Boolean).forEach(element => {
      if (invalid) element.setAttribute('aria-invalid', 'true');
      else element.removeAttribute('aria-invalid');
    });
  }
  function init() {
    const dialog = document.getElementById('agent-connection-dialog');
    const add = document.getElementById('agent-connection-add');
    if (dialog && add && !initialized.has(dialog)) {
      initialized.add(dialog);
      add.addEventListener('click', () => dialog.showModal());
      dialog.querySelectorAll('[data-close-connection]').forEach(button => {
        button.addEventListener('click', () => dialog.close());
      });
      dialog.addEventListener('close', () => add.focus({ preventScroll: true }));
    }
    initPermissionForms();
  }
  function initPermissionForms() {
    document.querySelectorAll('form[data-agent-permissions]').forEach(form => {
      if (initialized.has(form)) return;
      initialized.add(form);
      let attempted = false;
      const mode = form.querySelector('[data-customer-access]');
      const wizard = form.hasAttribute('data-agent-onboarding') ? initOnboarding(form) : null;
      form.addEventListener('reset', () => {
        attempted = false;
        form.querySelectorAll('[aria-invalid]').forEach(option => option.removeAttribute('aria-invalid'));
      });
      const validateSelections = () => {
        let firstInvalid = null;
        for (const name of ['issuers', 'customers']) {
          const error = form.querySelector(`[data-selection-error="${name}"]`);
          const options = [...form.querySelectorAll(`input[name="${name}"]`)];
          const required = name === 'issuers' || mode.value === 'selected';
          const invalid = required && !options.some(option => option.type === 'hidden' ? option.value : option.checked);
          showSelectionError(form, name, options, error, attempted && invalid);
          if (invalid && !firstInvalid) firstInvalid = options[0] || error;
        }
        return firstInvalid;
      };
      form.addEventListener('submit', event => {
        if (wizard && !wizard.ready()) {
          event.preventDefault();
          event.stopPropagation();
          wizard.next();
          return;
        }
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
  function initOnboarding(form) {
    const dialog = form.closest('dialog');
    const choices = [...form.querySelectorAll('input[name="assistant"]')];
    const name = form.querySelector('input[name="name"]');
    const placeholder = name.placeholder;
    const error = form.querySelector('[data-assistant-error]');
    const de = document.documentElement.lang === 'de';
    let step = 1;
    function showStep(value, focus = true) {
      step = value;
      form.querySelectorAll('[data-onboarding-page]').forEach(page => {
        page.hidden = Number(page.dataset.onboardingPage) !== step;
        if (!page.hidden && focus) page.querySelector('h3').focus({ preventScroll: true });
      });
      dialog.querySelectorAll('[data-setup-step]').forEach(item => {
        const number = Number(item.dataset.setupStep);
        if (number === step) item.setAttribute('aria-current', 'step');
        else item.removeAttribute('aria-current');
        item.classList.toggle('is-complete', number < step);
      });
      dialog.scrollTop = 0;
    }
    function next() {
      const choice = choices.find(input => input.checked);
      showSelectionError(form, 'assistant', choices, error, !choice);
      if (!choice) { choices[0].focus(); return; }
      name.placeholder = { chatgpt: 'ChatGPT', codex: 'Codex', claude: 'Claude' }[choice.value] || placeholder;
      showStep(2);
    }
    const policies = [...form.querySelectorAll('[data-operation-label]')];
    const location = form.querySelector('[name="client_approvals"]');
    function summary() {
      const labels = de ? { deny: 'Verboten', confirm: 'Nachfragen', allow: 'Erlaubt' }
        : { deny: 'Denied', confirm: 'Ask', allow: 'Allowed' };
      const defaults = policies.every(select => select.value ===
        (['permission_deactivate_issuer', 'permission_delete_customer', 'permission_delete_invoice'].includes(select.name) ? 'deny' : 'confirm'));
      form.querySelector('[data-policy-summary]').textContent = defaults
        ? (de ? 'Änderungen: nachfragen. Löschen und Deaktivieren: verboten.' : 'Changes: ask. Deletion and deactivation: denied.')
        : Object.entries(labels).flatMap(([value, label]) => {
          const names = policies.filter(select => select.value === value).map(select => select.dataset.operationLabel);
          return names.length ? [`${label}: ${names.join(', ')}.`] : [];
        }).join(' ');
      form.querySelector('[data-approval-summary]').textContent = location.value === 'yes'
        ? (de ? 'Bestätigungen im Assistenten, wenn unterstützt; sonst in eRechnung.' : 'Confirmations in your assistant when supported; otherwise in eRechnung.')
        : (de ? 'Bestätigungen erfolgen in eRechnung.' : 'Confirmations appear in eRechnung.');
    }
    form.querySelector('[data-onboarding-next]').addEventListener('click', next);
    form.querySelector('[data-onboarding-back]').addEventListener('click', () => showStep(1));
    form.addEventListener('change', () => {
      if (choices.some(input => input.checked)) showSelectionError(form, 'assistant', choices, error, false);
      summary();
    });
    // Cancelled drafts must not carry wider permissions into a later connection.
    dialog.addEventListener('close', () => {
      form.reset();
      form.querySelectorAll('details').forEach(details => { details.open = false; });
      form.querySelectorAll('[data-selection-error]').forEach(element => { element.hidden = true; });
      error.hidden = true;
      name.placeholder = placeholder;
      form.querySelector('[data-customer-access]').dispatchEvent(new Event('change'));
      summary();
      showStep(1, false);
    });
    return { ready: () => step === 2, next };
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
      activate(buttons.find(button => button.id === tabs.dataset?.initialTab) || buttons[0]);
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
