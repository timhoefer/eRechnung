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
    dataset: { success: 'Copied', failure: 'Select and copy manually' },
    addEventListener: (_, handler) => { click = handler; },
  };
  const elements = { 'mcp-configuration': { textContent: displayed }, 'configuration-copy-status': status };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_settings.js'), 'utf8'), {
    document: { getElementById: id => elements[id], querySelector: () => button },
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
    document: { getElementById: id => elements[id], querySelector: () => null },
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
