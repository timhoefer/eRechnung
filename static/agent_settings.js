(() => {
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
  const copy = document.querySelector('[data-copy-configuration]');
  const configuration = document.getElementById('mcp-configuration');
  const status = document.getElementById('configuration-copy-status');
  if (copy && configuration && status) {
    copy.hidden = false;
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(configuration.textContent);
        status.textContent = copy.dataset.success;
      } catch {
        status.textContent = copy.dataset.failure;
      }
    });
  }
})();
