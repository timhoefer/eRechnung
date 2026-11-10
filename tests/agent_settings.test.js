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
    document: { addEventListener: () => {}, getElementById: id => elements[id], querySelectorAll: () => [button] },
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

test('tabs keep the same values and support arrow keys, Home and End without copying', async () => {
  const elements = { 'configuration-copy-status': { textContent: 'Old message' } };
  const buttons = ['json', 'values'].map(name => {
    const panel = `configuration-${name}-panel`;
    elements[panel] = { hidden: false };
    return {
      listeners: {}, attributes: { 'aria-controls': panel }, focused: false,
      addEventListener(name, fn) { this.listeners[name] = fn; },
      setAttribute(name, value) { this.attributes[name] = value; },
      getAttribute(name) { return this.attributes[name]; },
      focus() { this.focused = true; },
    };
  });
  elements['configuration-tabs'] = { hidden: true, querySelectorAll: () => buttons };
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
    document: { addEventListener: () => {}, getElementById: id => elements[id], querySelectorAll: () => copies },
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
  selected(0);
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
    document: { addEventListener: () => {}, getElementById: id => elements[id], querySelector: () => null },
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
