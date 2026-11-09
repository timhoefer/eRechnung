(() => {
  const mode = document.getElementById('agent-customer-mode');
  if (!mode) return;
  const update = () => {
    document.querySelectorAll('[data-customer-mode]').forEach(element => {
      element.hidden = element.dataset.customerMode !== mode.value;
      if (element.tagName === 'FIELDSET') element.disabled = element.hidden;
    });
  };
  mode.addEventListener('change', update);
  update();
})();
