const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(clipboard) {
  const displayed = '{"mcpServers":{"erechnung":{"env":{"ERECHNUNG_MCP_TOKEN":"fictional-test-value"}}}}';
  const status = { textContent: '' };
  let click;
  const button = {
    hidden: true,
    dataset: { copyTarget: 'mcp-configuration', success: 'Copied', failure: 'Select and copy manually' },
    addEventListener: (_, handler) => { click = handler; },
  };
  const elements = { 'mcp-configuration': { textContent: displayed }, 'configuration-copy-status': status };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_settings.js'), 'utf8'), {
    window: {},
    document: { addEventListener: () => {}, getElementById: id => elements[id], querySelectorAll: selector => selector === '[data-copy-target]' ? [button] : [] },
    navigator: { clipboard },
  });
  return { button, status, displayed, click: () => click() };
}

test('configuration is copied only after a click, including on the separate setup page', async () => {
  const writes = [];
  let complete;
  const page = setup({ writeText: text => {
    writes.push(text);
    return new Promise(resolve => { complete = resolve; });
  } });
  assert.equal(page.button.hidden, false);
  assert.deepEqual(writes, []);
  const pending = page.click();
  assert.deepEqual(writes, [page.displayed]);
  assert.equal(page.status.textContent, '');
  complete();
  await pending;
  assert.equal(page.status.textContent, 'Copied');
});

for (const initial of ['json', 'values']) test(`tabs start on ${initial} and preserve values and keyboard navigation`, async () => {
  const elements = { 'configuration-copy-status': { textContent: 'Old message' } };
  const buttons = ['json', 'values'].map(name => {
    const panel = `configuration-${name}-panel`;
    elements[panel] = { hidden: false };
    return {
      id: `configuration-${name}-tab`, listeners: {}, attributes: { 'aria-controls': panel }, focused: false,
      addEventListener(name, fn) { this.listeners[name] = fn; },
      setAttribute(name, value) { this.attributes[name] = value; },
      getAttribute(name) { return this.attributes[name]; },
      focus() { this.focused = true; },
    };
  });
  elements['configuration-tabs'] = { hidden: true, dataset: { initialTab: `configuration-${initial}-tab` }, querySelectorAll: () => buttons };
  const writes = [];
  const targets = {
    command: { value: '/Applications/e Rechnung "Test".app/Contents/MacOS/eRechnung' },
    argument: { value: '--mcp' },
    name: { textContent: 'ERECHNUNG_MCP_TOKEN' },
    token: { value: 'fictional-key-with_underscore-and-hyphen' },
  };
  Object.assign(elements, targets);
  const copies = Object.keys(targets).map(target => ({
    hidden: true,
    dataset: { copyTarget: target, success: 'Copied', failure: 'Failed' },
    addEventListener(_, fn) { this.click = fn; },
  }));
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_settings.js'), 'utf8'), {
    window: {},
    document: { addEventListener: () => {}, getElementById: id => elements[id], querySelectorAll: selector => selector === '[data-copy-target]' ? copies : [] },
    navigator: { clipboard: { writeText: async text => { writes.push(text); } } },
  });
  function selected(index) {
    buttons.forEach((button, i) => {
      assert.equal(button.attributes['aria-selected'], String(i === index));
      assert.equal(button.tabIndex, i === index ? 0 : -1);
      assert.equal(elements[button.attributes['aria-controls']].hidden, i !== index);
    });
  }
  function key(index, key) {
    let prevented = false;
    buttons[index].listeners.keydown({ key, preventDefault: () => { prevented = true; } });
    assert.equal(prevented, true);
  }
  assert.equal(elements['configuration-tabs'].hidden, false);
  selected(initial === 'json' ? 0 : 1);
  buttons[1].listeners.click();
  selected(1);
  assert.equal(elements['configuration-copy-status'].textContent, '');
  key(1, 'ArrowRight'); selected(0);
  key(0, 'ArrowLeft'); selected(1);
  key(1, 'Home'); selected(0);
  key(0, 'End'); selected(1);
  assert.equal(buttons[1].focused, true);
  assert.deepEqual(writes, []);
  for (const button of copies) {
    assert.equal(button.hidden, false);
    await button.click();
  }
  assert.deepEqual(writes, Object.values(targets).map(target => target.value ?? target.textContent));
  buttons[0].listeners.click();
  selected(0);
  assert.equal(elements['configuration-copy-status'].textContent, '');
  await copies[3].click();
  assert.equal(writes.at(-1), targets.token.value);
});

test('onboarding never submits its first step, preserves drafts on Back and resets all grants on close', () => {
  const node = (properties = {}) => ({
    hidden: false, attributes: {}, listeners: {}, dataset: {},
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    dispatchEvent(event) { (this.listeners[event.type] || []).forEach(fn => fn(event)); },
    setAttribute(key, value) { this.attributes[key] = value; },
    removeAttribute(key) { delete this.attributes[key]; },
    focus() { this.focused = true; },
    ...properties,
  });
  const assistant = node({ value: 'codex', checked: false });
  const name = node({ value: '', placeholder: 'My connection' });
  const issuer = node({ checked: false });
  const customer = node({ checked: false });
  const mode = node({ value: 'none' });
  const location = node({ value: 'no' });
  const policy = node({ name: 'permission_save_customer', value: 'confirm', dataset: { operationLabel: 'Edit customers' } });
  const deletion = node({ name: 'permission_delete_customer', value: 'deny', dataset: { operationLabel: 'Delete customers' } });
  const details = node({ open: false });
  const selectionErrors = [node({ hidden: true }), node({ hidden: true })];
  const error = node({ hidden: true });
  const summary = node(), approvalSummary = node(), next = node(), back = node();
  const group = node({ tagName: 'FIELDSET', dataset: { customerMode: 'selected' } });
  const pages = [1, 2].map(step => node({ hidden: step === 2, dataset: { onboardingPage: String(step) }, querySelector: () => node() }));
  const steps = [1, 2, 3].map(step => node({ dataset: { setupStep: String(step) }, classList: { toggle() {} } }));
  const dialog = node({ querySelectorAll: () => steps });
  const single = {
    '[data-customer-access]': mode, 'input[name="name"]': name, '[data-assistant-error]': error,
    '[name="client_approvals"]': location, '[data-policy-summary]': summary, '[data-approval-summary]': approvalSummary,
    '[data-onboarding-next]': next, '[data-onboarding-back]': back,
    '[data-selection-error="issuers"]': selectionErrors[0], '[data-selection-error="customers"]': selectionErrors[1],
  };
  const lists = {
    'input[name="assistant"]': [assistant], 'input[name="issuers"]': [issuer], 'input[name="customers"]': [customer],
    '[data-operation-label]': [policy, deletion], '[data-onboarding-page]': pages, details: [details],
    '[data-customer-mode]': [group], '[data-selection-error]': selectionErrors, '[aria-invalid]': [issuer, customer],
  };
  const form = node({
    hasAttribute: () => true, closest: () => dialog,
    querySelector: selector => single[selector], querySelectorAll: selector => lists[selector] || [],
    reset() {
      this.dispatchEvent({ type: 'reset' });
      assistant.checked = issuer.checked = customer.checked = false;
      name.value = '';
      mode.value = 'none'; location.value = 'no'; policy.value = 'confirm'; deletion.value = 'deny';
    },
  });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_settings.js'), 'utf8'), {
    Event: class { constructor(type) { this.type = type; } }, window: {},
    document: { documentElement: { lang: 'en' }, addEventListener() {}, getElementById() {},
      querySelectorAll: selector => selector === 'form[data-agent-permissions]' ? [form] : [] },
  });
  function submit() {
    const event = { type: 'submit', prevented: false, stopped: false,
      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
    form.dispatchEvent(event);
    assert.equal(event.prevented, event.stopped);
    return event.prevented;
  }
  assert.equal(submit(), true);
  assert.equal(error.hidden, false);
  assert.equal(pages[1].hidden, true);
  assistant.checked = true;
  assert.equal(submit(), true); // Enter advances only; the grant POST cannot bubble.
  assert.equal(pages[1].hidden, false);
  assert.equal(steps[1].attributes['aria-current'], 'step');
  assert.equal(name.placeholder, 'Codex');
  assert.equal(submit(), true); // An issuer is still required.
  issuer.checked = true;
  mode.value = 'selected'; mode.dispatchEvent({ type: 'change' });
  assert.equal(group.disabled, false);
  assert.equal(submit(), true); // Empty customer selection stays blocked.
  customer.checked = true;
  policy.value = 'allow'; location.value = 'yes';
  name.value = 'Draft'; details.open = true;
  form.dispatchEvent({ type: 'change' });
  assert.match(summary.textContent, /Allowed: Edit customers/);
  assert.match(approvalSummary.textContent, /in your assistant/);
  back.dispatchEvent({ type: 'click' });
  assert.equal(pages[1].hidden, true);
  assert.equal(submit(), true);
  assert.equal(customer.checked, true);
  assert.equal(policy.value, 'allow');
  assert.equal(submit(), false); // Only the reviewed, valid second step may submit.
  dialog.dispatchEvent({ type: 'close' }); // X, Escape and Cancel share this event.
  assert.equal(pages[1].hidden, true);
  assert.equal(details.open, false);
  assert.equal(name.value, '');
  assert.equal(name.placeholder, 'My connection');
  assert.equal(mode.value, 'none');
  assert.equal(group.disabled, true);
  assert.equal(issuer.checked, false);
  assert.equal(customer.checked, false);
  assert.equal(policy.value, 'confirm');
  assert.equal(deletion.value, 'deny');
  assert.equal(location.value, 'no');
  assert.match(summary.textContent, /Deletion and deactivation: denied/);
  assert.match(approvalSummary.textContent, /in eRechnung/);
  assert.equal(submit(), true);
});

for (const clipboard of [undefined, { writeText: async () => { throw new Error('Denied'); } }]) {
  test('clipboard failures offer manual copying without claiming success', async () => {
    const page = setup(clipboard);
    await page.click();
    assert.equal(page.status.textContent, 'Select and copy manually');
    assert.ok(page.displayed.includes('fictional-test-value'));
  });
}

test('new connection opens on demand and cancel/escape return focus without submitting', () => {
  const listeners = {};
  let focused = false;
  const add = { addEventListener: (_, fn) => { listeners.add = fn; }, focus: () => { focused = true; } };
  const cancel = { addEventListener: (_, fn) => { listeners.cancel = fn; } };
  const dialog = {
    open: false,
    showModal() { this.open = true; },
    close() { this.open = false; listeners.close(); },
    querySelectorAll: () => [cancel],
    addEventListener: (name, fn) => { listeners[name] = fn; },
  };
  const elements = { 'agent-connection-dialog': dialog, 'agent-connection-add': add };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_settings.js'), 'utf8'), {
    window: {},
    document: { addEventListener: () => {}, getElementById: id => elements[id], querySelector: () => null, querySelectorAll: () => [] },
  });
  assert.equal(dialog.open, false);
  listeners.add();
  assert.equal(dialog.open, true);
  listeners.cancel();
  assert.equal(dialog.open, false);
  assert.equal(focused, true);
  focused = false;
  listeners.add();
  dialog.close(); // native Escape closes a dialog and emits close
  assert.equal(focused, true);
});

test('empty issuer or selected-customer groups block submission and recover without resetting the form', () => {
  const listeners = {};
  const control = () => ({ checked: false, attributes: {}, focused: false,
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    focus() { this.focused = true; },
  });
  const issuer = control(), customer = control();
  const issuerError = { hidden: true }, customerError = { hidden: true };
  const mode = { value: 'selected', addEventListener() {} };
  const options = { hidden: false, disabled: false, tagName: 'FIELDSET', dataset: { customerMode: 'selected' } };
  const form = {
    hasAttribute: () => false,
    querySelector: selector => selector === '[data-customer-access]' ? mode
      : selector.includes('issuers') ? issuerError : customerError,
    querySelectorAll: selector => selector === 'input[name="issuers"]' ? [issuer]
      : selector === 'input[name="customers"]' ? [customer] : [options],
    addEventListener(name, fn) { listeners[name] = fn; },
  };
  const elements = { 'agent-connection-add': { addEventListener() {} },
    'agent-customer-mode': mode, 'agent-issuers-error': issuerError, 'agent-customers-error': customerError };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_settings.js'), 'utf8'), {
    window: {}, document: { addEventListener() {}, getElementById: id => elements[id], querySelectorAll: selector => selector === 'form[data-agent-permissions]' ? [form] : [] },
  });
  function submit() {
    const event = { prevented: false, stopped: false,
      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
    listeners.submit(event);
    assert.equal(event.prevented, event.stopped);
    return event.prevented;
  }
  assert.equal(issuerError.hidden, true);
  assert.equal(customerError.hidden, true);
  assert.equal(submit(), true);
  assert.equal(issuerError.hidden, false);
  assert.equal(customerError.hidden, false);
  assert.equal(issuer.focused, true);
  issuer.checked = true;
  listeners.change();
  assert.equal(issuerError.hidden, true);
  assert.equal(submit(), true);
  assert.equal(customer.focused, true);
  assert.equal(customer.attributes['aria-invalid'], 'true');
  customer.checked = true;
  listeners.change();
  assert.equal(customerError.hidden, true);
  assert.equal(customer.attributes['aria-invalid'], undefined);
  assert.equal(submit(), false);
  customer.checked = false;
  assert.equal(submit(), true);
  for (const value of ['none', 'all']) {
    mode.value = value;
    listeners.change();
    assert.equal(customerError.hidden, true);
    assert.equal(submit(), false);
  }
  assert.equal(issuer.checked, true);
  // A single active issuer is submitted as a fixed hidden value, without a checkbox.
  issuer.checked = false;
  issuer.type = 'hidden';
  issuer.value = 'default';
  assert.equal(submit(), false);
});
