const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const listeners = {}, requests = [];
  const error = { hidden: true };
  const card = { innerHTML: 'Access is off', querySelector: () => error };
  const disclaimer = { textContent: 'Local data' };
  let focused = false;
  const toggle = { focus: () => { focused = true; } };
  const dialog = {
    open: false, innerHTML: '',
    showModal() { this.open = true; }, close() { this.open = false; },
    querySelector: () => ({ focus() {} }),
  };
  const elements = { 'agent-access-card': card, 'agent-disable-dialog': dialog, 'disclaimer-text': disclaimer };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/agent_access.js'), 'utf8'), {
    document: { addEventListener: (name, fn) => { listeners[name] = fn; },
      getElementById: id => elements[id], querySelector: () => toggle },
    FormData: class { constructor(form) { this.fields = form.fields; } },
    fetch: (url, options) => new Promise((resolve, reject) => { requests.push({ url, options, resolve, reject }); }),
  });
  const button = { disabled: false };
  // The hidden input named "action" masks HTMLFormElement.action in browsers.
  const form = { action: { value: 'enable' }, getAttribute: () => '/agents/settings', fields: { csrf: 'fictional', return_to: 'settings' },
    matches: () => true, querySelector: () => button };
  return { requests, card, dialog, error, disclaimer, button, focused: () => focused,
    submit: () => listeners.submit({ target: form, preventDefault() {} }),
    cancel: () => listeners.click({ target: { closest: () => true } }),
    respond(data, status = 200) { requests.at(-1).resolve({ ok: status < 400, status, json: async () => data }); },
  };
}

test('settings toggle waits for server, updates only controls/disclaimer and suppresses duplicate submissions', async () => {
  const page = setup();
  assert.equal(page.requests.length, 0);
  const pending = page.submit();
  await page.submit();
  assert.equal(page.requests.length, 1);
  assert.equal(page.requests[0].url, '/agents/settings');
  assert.equal(page.button.disabled, true);
  assert.equal(page.card.innerHTML, 'Access is off');
  assert.equal(page.requests[0].options.body.fields.csrf, 'fictional');
  assert.equal(page.requests[0].options.headers['X-Requested-With'], 'fetch');
  page.respond({ controls: 'Access is on', disclaimer: 'Agent data processing' });
  await pending;
  assert.equal(page.card.innerHTML, 'Access is on');
  assert.equal(page.disclaimer.textContent, 'Agent data processing');
  assert.equal(page.button.disabled, false);
  assert.equal(page.focused(), true);
});

test('destructive warning and stale warning require a new submit, while cancel sends nothing', async () => {
  const page = setup();
  let pending = page.submit();
  page.respond({ confirmation: 'Connections will be removed' });
  await pending;
  assert.equal(page.dialog.open, true);
  assert.equal(page.requests.length, 1);
  page.cancel();
  assert.equal(page.dialog.open, false);
  assert.equal(page.requests.length, 1);
  pending = page.submit();
  page.respond({ confirmation: 'Connections changed: review again' }, 409);
  await pending;
  assert.equal(page.dialog.open, true);
  assert.equal(page.dialog.innerHTML, 'Connections changed: review again');
  assert.equal(page.card.innerHTML, 'Access is off');
  pending = page.submit();
  page.respond({ controls: 'Access is off', disclaimer: 'Local data' });
  await pending;
  assert.equal(page.dialog.open, false);
});

test('a failed update never displays success or flips the switch and can be retried', async () => {
  const page = setup();
  const pending = page.submit();
  page.respond({}, 403);
  await pending;
  assert.equal(page.error.hidden, false);
  assert.equal(page.button.disabled, false);
  assert.equal(page.card.innerHTML, 'Access is off');
  assert.equal(page.disclaimer.textContent, 'Local data');
  const retry = page.submit();
  page.respond({ controls: 'Access is on', disclaimer: 'Agent data processing' });
  await retry;
  assert.equal(page.error.hidden, true);
  assert.equal(page.card.innerHTML, 'Access is on');
});
